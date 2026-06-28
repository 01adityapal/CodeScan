"""
CodeScan configuration
=====================
All environment-driven configuration in one place.

Three environments are supported:
    - DevelopmentConfig  : local laptop, SQLite fallback, debug on
    - ProductionConfig   : EC2/Gunicorn, Neon Postgres, debug off
    - TestingConfig      : in-memory SQLite, no CSRF, fast

CORRECTED DECISIONS (vs the original v2 doc):
    * FLASK_DEBUG is used, NOT FLASK_ENV (FLASK_ENV was removed in Flask 2.3).
    * For Neon (Postgres) we use QueuePool + pool_pre_ping=True. NullPool is for
      ephemeral functions (Lambda) — on a long-lived Gunicorn server it would
      add a full TCP+auth handshake on every request, so we do NOT use it here.
    * pool_pre_ping validates the connection before use, which handles Neon's
      cold starts (compute suspend) gracefully.

Usage:
    app.config.from_object(Config)              # or one of the subclasses
    # Flask-Migrate / Alembic should run against the DIRECT (non-pooler) URL.
"""

import os
from datetime import timedelta

from dotenv import load_dotenv

# Load variables from backend/.env (if present). Safe to call in every env.
load_dotenv()


def _env(key: str, default: str = "") -> str:
    """Read an environment variable, treating empty/whitespace values as unset.

    os.environ.get("DATABASE_URL", fallback) returns "" when the variable
    EXISTS but is blank (e.g. `DATABASE_URL=` in .env) — which would silently
    bypass the fallback. This helper normalises that so a blank line behaves
    exactly like the variable never being set.
    """
    value = os.environ.get(key)
    if value is None:
        return default
    value = value.strip()
    return value if value else default


def _build_engine_options(database_uri: str) -> dict:
    """Return SQLAlchemy engine options appropriate for the database type.

    Postgres (Neon) -> QueuePool with pre-ping + recycle (the corrected choice).
    SQLite          -> default pool (SQLite manages its own connections).
    """
    if database_uri.startswith("sqlite"):
        return {}
    return {
        # Validate the connection before handing it out — survives Neon
        # suspending its compute (cold starts).
        "pool_pre_ping": True,
        # Close idle connections before Neon's / network's idle timeout can.
        "pool_recycle": 300,
        # Explicitly use a small QueuePool — NOT NullPool. NullPool opens a
        # fresh connection per request, which is wasteful on a long-lived server.
        "pool_size": 5,
        "max_overflow": 5,
    }


class Config:
    """Base configuration shared by every environment."""

    # ------------------------------------------------------------------ #
    # Flask core
    # ------------------------------------------------------------------ #
    # FLASK_ENV was removed in Flask 2.3. We control debug via FLASK_DEBUG.
    DEBUG = _env("FLASK_DEBUG", "0") == "1"

    SECRET_KEY = _env("SECRET_KEY")
    if not SECRET_KEY:
        # Fail loudly in production; in dev fall back to a clearly-insecure key.
        if _env("FLASK_ENV_MODE", "dev") == "production":
            raise RuntimeError("SECRET_KEY must be set in production.")
        SECRET_KEY = "dev-only-insecure-secret-key-key-change-me"

    # ------------------------------------------------------------------ #
    # Request size limit — 1 MB hard cap. Protects the server from huge
    # payloads (the AST engine is then guaranteed to parse quickly).
    # ------------------------------------------------------------------ #
    MAX_CONTENT_LENGTH = 1 * 1024 * 1024  # 1,048,576 bytes

    # ------------------------------------------------------------------ #
    # Database (Neon Postgres in prod, SQLite fallback in dev)
    # ------------------------------------------------------------------ #
    SQLALCHEMY_DATABASE_URI = _env(
        "DATABASE_URL",
        "sqlite:///" + os.path.join(os.path.abspath(os.path.dirname(__file__)), "..", "codescan_dev.db"),
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_ENGINE_OPTIONS = _build_engine_options(SQLALCHEMY_DATABASE_URI)

    # ------------------------------------------------------------------ #
    # Session & cookie security
    # SameSite=Lax is the PRIMARY CSRF defence; Flask-WTF adds a second layer.
    # ------------------------------------------------------------------ #
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    # SECURE should be True only behind HTTPS. Subclasses override this.
    SESSION_COOKIE_SECURE = False
    PERMANENT_SESSION_LIFETIME = timedelta(hours=2)
    SESSION_REFRESH_EACH_REQUEST = True

    # ------------------------------------------------------------------ #
    # Redis — cache + Flask-Limiter storage backend
    # ------------------------------------------------------------------ #
    REDIS_URL = _env("REDIS_URL", "redis://localhost:6379/0")
    RATELIMIT_STORAGE_URI = _env("REDIS_URL", "redis://localhost:6379/0")
    RATELIMIT_HEADERS_ENABLED = True

    # ------------------------------------------------------------------ #
    # Groq AI (enhancement only — never a hard dependency)
    # ------------------------------------------------------------------ #
    GROQ_API_KEY = _env("GROQ_API_KEY", "")
    GROQ_MODEL = _env("GROQ_MODEL", "llama-3.1-8b-instant")

    # ------------------------------------------------------------------ #
    # Frontend origin for CORS (env-driven so dev & prod differ)
    # ------------------------------------------------------------------ #
    FRONTEND_ORIGIN = _env("FRONTEND_ORIGIN", "http://localhost:5173")

    # ------------------------------------------------------------------ #
    # Application constants
    # ------------------------------------------------------------------ #
    ANALYSIS_VERSION = "1.0"
    # How much of the scanned code is persisted as a preview (never full code).
    CODE_PREVIEW_LENGTH = 500
    # Safety-net timeout for ast.parse (it is bounded by MAX_CONTENT_LENGTH,
    # so this rarely triggers — but we never wait forever).
    ANALYSIS_TIMEOUT_SECONDS = 2.0


class DevelopmentConfig(Config):
    """Local laptop development."""
    DEBUG = True
    SESSION_COOKIE_SECURE = False  # localhost is HTTP


class ProductionConfig(Config):
    """EC2 + Gunicorn + Neon."""
    DEBUG = False
    SESSION_COOKIE_SECURE = True   # behind Nginx HTTPS / CloudFront


class TestingConfig(Config):
    """Fast, isolated test runs."""
    TESTING = True
    DEBUG = False
    # In-memory SQLite — no filesystem, no pool options needed.
    SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"
    SQLALCHEMY_ENGINE_OPTIONS = {}
    WTF_CSRF_ENABLED = False
    RATELIMIT_ENABLED = False


# Lookup table used by the app factory:  app.config.from_object(config[mode])
config = {
    "development": DevelopmentConfig,
    "production": ProductionConfig,
    "testing": TestingConfig,
    "default": DevelopmentConfig,
}


def get_config():
    """Return the config class for the current FLASK_ENV_MODE (or default)."""
    mode = _env("FLASK_ENV_MODE", "development")
    return config.get(mode, config["default"])
