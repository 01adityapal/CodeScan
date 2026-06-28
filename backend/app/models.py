"""
CodeScan database models
========================
Four tables backing the application:

    users          accounts + account-level login lockout
    scans          one row per analysis request (500-char code preview only)
    scan_results   individual issues found within a scan
    login_attempts audit trail of every login attempt

Key schema decisions (verified correct in the project doc):
    * UNIQUE(scan_id, line_number, issue_type) — NOT (scan_id, line_number) —
      so a single line may legitimately carry several different issues.
    * ON DELETE CASCADE on every foreign key, so deleting a user wipes their
      scans, results and login attempts with no orphans.
    * INDEX on login_attempts.user_id for fast account-lockout queries.

Security:
    * Full source code is NEVER persisted — only a 500-character preview.
    * Passwords are hashed with bcrypt (72-byte limit enforced) — never stored
      in plaintext.
"""

from __future__ import annotations

from datetime import datetime, timezone

import bcrypt
from flask_login import UserMixin
from flask_sqlalchemy import SQLAlchemy

# The shared SQLAlchemy instance. The app factory calls db.init_app(app).
db = SQLAlchemy()

# bcrypt silently truncates passwords longer than 72 bytes; we reject them
# explicitly so a user never gets a weaker hash than they expect.
BCRYPT_MAX_BYTES = 72
# Account-level lockout policy (Layer 2 of the two-layer login defence).
MAX_FAILED_ATTEMPTS = 5
LOCKOUT_MINUTES = 15


def _now() -> datetime:
    """Return the current UTC time. (datetime.utcnow is deprecated in 3.12.)"""
    return datetime.now(timezone.utc)


def _naive_utc(dt: datetime) -> datetime:
    """Normalise a datetime to a naive UTC value for safe comparison.

    We store timezone-aware UTC datetimes (correct for Postgres). SQLite,
    however, strips tzinfo on reload, so comparing an aware `_now()` against a
    value just read from SQLite raises "can't compare offset-naive and
    offset-aware datetimes". Normalising both sides to naive UTC fixes this
    and works identically on Postgres.
    """
    if dt.tzinfo is not None:
        return dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


# --------------------------------------------------------------------------- #
# USERS
# --------------------------------------------------------------------------- #

class User(UserMixin, db.Model):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50), unique=True, nullable=False, index=True)
    email = db.Column(db.String(100), unique=True, nullable=False)
    password_hash = db.Column(db.Text, nullable=False)
    failed_login_attempts = db.Column(db.Integer, nullable=False, default=0)
    locked_until = db.Column(db.DateTime(timezone=True), nullable=True)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=_now)

    # cascade="all, delete-orphan" makes the ORM delete a user's scans/attempts
    # when the user is deleted. The ON DELETE CASCADE clause in the FK is a
    # backstop for direct SQL deletes on Postgres. (We deliberately do NOT use
    # passive_deletes=True, because that relies on DB-level cascade which SQLite
    # does not enforce unless the foreign_keys pragma is enabled.)
    scans = db.relationship(
        "Scan",
        backref="user",
        cascade="all, delete-orphan",
    )
    login_attempts = db.relationship(
        "LoginAttempt",
        backref="user",
        cascade="all, delete-orphan",
    )

    # ----- password handling (bcrypt) ----- #

    def set_password(self, raw_password: str) -> None:
        """Hash and store a password. Raises ValueError if too long for bcrypt."""
        pw_bytes = raw_password.encode("utf-8")
        if len(pw_bytes) > BCRYPT_MAX_BYTES:
            raise ValueError(
                f"Password is too long (max {BCRYPT_MAX_BYTES} bytes for bcrypt)."
            )
        self.password_hash = bcrypt.hashpw(pw_bytes, bcrypt.gensalt()).decode("utf-8")

    def check_password(self, raw_password: str) -> bool:
        """Return True if the password matches the stored hash."""
        if not self.password_hash:
            return False
        return bcrypt.checkpw(
            raw_password.encode("utf-8"),
            self.password_hash.encode("utf-8"),
        )

    # ----- account-level login lockout (Layer 2) ----- #

    @property
    def is_locked(self) -> bool:
        """True if the account is currently in a temporary lockout window."""
        if self.locked_until is None:
            return False
        return _naive_utc(self.locked_until) > _naive_utc(_now())

    def register_failed_login(self) -> None:
        """Increment failures and lock the account once the threshold is reached."""
        self.failed_login_attempts += 1
        if self.failed_login_attempts >= MAX_FAILED_ATTEMPTS:
            from datetime import timedelta
            self.locked_until = _now() + timedelta(minutes=LOCKOUT_MINUTES)

    def reset_login_state(self) -> None:
        """Clear failed attempts + lockout after a successful login."""
        self.failed_login_attempts = 0
        self.locked_until = None

    # ----- serialisation ----- #

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "username": self.username,
            "email": self.email,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


# --------------------------------------------------------------------------- #
# SCANS
# --------------------------------------------------------------------------- #

class Scan(db.Model):
    __tablename__ = "scans"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(
        db.Integer,
        db.ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    code_preview = db.Column(db.String(500))         # first 500 chars only
    complexity_score = db.Column(db.String(30))       # "Likely O(n^2)"
    issue_count = db.Column(db.Integer)
    analysis_duration_ms = db.Column(db.Integer)
    analysis_version = db.Column(db.String(10), default="1.0", nullable=False)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=_now)

    results = db.relationship(
        "ScanResult",
        backref="scan",
        cascade="all, delete-orphan",
    )

    def to_dict(self, include_results: bool = False) -> dict:
        data = {
            "id": self.id,
            "user_id": self.user_id,
            "code_preview": self.code_preview,
            "complexity_score": self.complexity_score,
            "issue_count": self.issue_count,
            "analysis_duration_ms": self.analysis_duration_ms,
            "analysis_version": self.analysis_version,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }
        if include_results:
            data["results"] = [r.to_dict() for r in self.results]
        return data


# --------------------------------------------------------------------------- #
# SCAN RESULTS  (the fixed UNIQUE constraint lives here)
# --------------------------------------------------------------------------- #

class ScanResult(db.Model):
    __tablename__ = "scan_results"

    # FIXED: (scan_id, line_number, issue_type) — allows multiple DIFFERENT
    # issues on the same line, while still deduping identical retries.
    __table_args__ = (
        db.UniqueConstraint(
            "scan_id", "line_number", "issue_type",
            name="uq_scan_line_issue_type",
        ),
    )

    id = db.Column(db.Integer, primary_key=True)
    scan_id = db.Column(
        db.Integer,
        db.ForeignKey("scans.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    line_number = db.Column(db.Integer, nullable=False)
    issue_type = db.Column(db.String(50), nullable=False)   # "Nested Loop", ...
    severity = db.Column(db.String(10))                      # High / Med / Low
    groq_suggestion = db.Column(db.Text)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=_now)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "scan_id": self.scan_id,
            "line_number": self.line_number,
            "issue_type": self.issue_type,
            "severity": self.severity,
            "groq_suggestion": self.groq_suggestion,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


# --------------------------------------------------------------------------- #
# LOGIN ATTEMPTS  (audit + powers account lockout)
# --------------------------------------------------------------------------- #

class LoginAttempt(db.Model):
    __tablename__ = "login_attempts"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(
        db.Integer,
        db.ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,   # speeds up account-lockout lookups
    )
    attempted_at = db.Column(db.DateTime(timezone=True), nullable=False, default=_now)
    ip_address = db.Column(db.String(45))   # IPv4 or IPv6
    success = db.Column(db.Boolean, nullable=False)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "user_id": self.user_id,
            "attempted_at": self.attempted_at.isoformat() if self.attempted_at else None,
            "ip_address": self.ip_address,
            "success": self.success,
        }
