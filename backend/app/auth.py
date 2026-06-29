"""
CodeScan Authentication Blueprint
=================================
Register, login, and logout endpoints.

Two-layer login defence (from the security doc):
    Layer 1 (IP): Flask-Limiter + Redis — blocks brute-force by IP address.
    Layer 2 (Account): failed_login_attempts + locked_until columns — locks
    the specific username after 5 failures, regardless of IP.

Design notes:
    * JSON API (no HTML forms) — React sends {username, password} as JSON.
    * SameSite=Lax cookies are the primary CSRF defence; no Flask-WTF needed
      for a JSON API.
    * Login failures return the SAME generic message whether the username
      exists or not — prevents username enumeration.
    * Account lockout returns 429 (Too Many Requests) with a clear message.
"""

from __future__ import annotations

from flask import Blueprint, jsonify, request
from flask_login import login_required, login_user, logout_user
from sqlalchemy.exc import IntegrityError

from . import limiter
from .models import User, db

auth_bp = Blueprint("auth", __name__, url_prefix="/api/v1/auth")


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #

def _get_credentials() -> tuple[str, str] | tuple[None, None]:
    """Extract and validate username + password from JSON body.

    Returns (username, password) on success, (None, None) on failure.
    """
    payload = request.get_json(silent=True) or {}
    username = str(payload.get("username", "")).strip()
    password = payload.get("password", "")
    if not username or not password:
        return None, None
    return username, password


# --------------------------------------------------------------------------- #
# POST /api/v1/auth/register
# --------------------------------------------------------------------------- #

@auth_bp.route("/register", methods=["POST"])
@limiter.limit("3 per minute")  # Prevent automated spam account creation
def register():
    """Create a new user account."""
    payload = request.get_json(silent=True) or {}
    username = str(payload.get("username", "")).strip()
    email = str(payload.get("email", "")).strip().lower()
    password = payload.get("password", "")

    # Basic validation
    if not username or not email or not password:
        return jsonify({"error": "username, email and password are required."}), 400
    if len(username) < 3 or len(username) > 50:
        return jsonify({"error": "username must be 3-50 characters."}), 400
    if "@" not in email or "." not in email.split("@")[-1]:
        return jsonify({"error": "invalid email address."}), 400
    if len(password) < 6:
        return jsonify({"error": "password must be at least 6 characters."}), 400

    # Uniqueness checks
    if User.query.filter_by(username=username).first():
        return jsonify({"error": "username already taken."}), 409
    if User.query.filter_by(email=email).first():
        return jsonify({"error": "email already registered."}), 409

    user = User(username=username, email=email)
    try:
        user.set_password(password)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400

    db.session.add(user)
    db.session.commit()
    return jsonify({"status": "success", "user": user.to_dict()}), 201


# --------------------------------------------------------------------------- #
# POST /api/v1/auth/login  (two-layer defence)
# --------------------------------------------------------------------------- #

@auth_bp.route("/login", methods=["POST"])
@limiter.limit("5 per minute")  # Layer 1: IP-based brute-force protection
def login():
    """Authenticate a user.

    Layer 1 (IP): handled by Flask-Limiter decorator on this route.
    Layer 2 (Account): checked here via user.is_locked.
    """
    username, password = _get_credentials()
    if username is None:
        return jsonify({"error": "username and password are required."}), 400

    user = User.query.filter_by(username=username).first()

    # Same generic message whether user exists or not — prevents enumeration.
    if user is None:
        return jsonify({"error": "invalid credentials."}), 401

    # Layer 2: account-level lockout
    if user.is_locked:
        return jsonify({"error": "account temporarily locked. try again later."}), 429

    if not user.check_password(password):
        user.register_failed_login()
        db.session.commit()
        return jsonify({"error": "invalid credentials."}), 401

    # Success — clear any stale lockout state and create session
    user.reset_login_state()
    db.session.commit()
    login_user(user)
    return jsonify({"status": "success", "user": user.to_dict()}), 200


# --------------------------------------------------------------------------- #
# POST /api/v1/auth/logout
# --------------------------------------------------------------------------- #

@auth_bp.route("/logout", methods=["POST"])
@login_required
def logout():
    """End the current session."""
    logout_user()
    return jsonify({"status": "success"}), 200
