"""
CodeScan Flask application factory
==================================
The spine of the backend. `create_app()` wires together:

    1. Configuration   -> loaded from app.config (env-driven)
    2. Database        -> SQLAlchemy `db` from app.models
    3. Authentication  -> Flask-Login LoginManager
    4. SQLite safety   -> enables PRAGMA foreign_keys=ON in dev
    5. Health check    -> GET /health
    6. Error handlers  -> generic JSON responses (no tracebacks leaked)

Production uses Flask-Migrate (Alembic) for the schema; tables are only
auto-created in development/testing mode here for convenience.

Usage:
    from app import create_app
    app = create_app()
    app.run(debug=True)
"""

from __future__ import annotations

from flask import Flask, jsonify
from flask_login import LoginManager
from sqlalchemy import event, text
from sqlalchemy.exc import SQLAlchemyError

from .config import get_config, config
from .models import db, User

# Shared across the package. The app factory calls login_manager.init_app(app).
login_manager = LoginManager()


# --------------------------------------------------------------------------- #
# Flask-Login: how to load a user from the session cookie
# --------------------------------------------------------------------------- #

@login_manager.user_loader
def load_user(user_id: str):
    """Reload a User by primary key on each authenticated request."""
    if not user_id or not str(user_id).isdigit():
        return None
    return db.session.get(User, int(user_id))


# --------------------------------------------------------------------------- #
# SQLite helper: enforce foreign keys in development
# --------------------------------------------------------------------------- #

def _enable_sqlite_foreign_keys() -> None:
    """Run `PRAGMA foreign_keys=ON` on every new SQLite connection.

    Postgres enforces FK constraints by default; SQLite does not unless this
    pragma is set per-connection. Enabling it makes dev behave like prod.
    """
    @event.listens_for(db.engine, "connect")
    def _set_pragma(dbapi_connection, _connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()


# --------------------------------------------------------------------------- #
# Error handlers: always return JSON, never leak internal tracebacks
# --------------------------------------------------------------------------- #

def _register_error_handlers(app: Flask) -> None:
    @app.errorhandler(404)
    def _not_found(_err):
        return jsonify({"error": "Resource not found."}), 404

    @app.errorhandler(405)
    def _method_not_allowed(_err):
        return jsonify({"error": "Method not allowed."}), 405

    @app.errorhandler(413)
    def _too_large(_err):
        return jsonify({"error": "Payload too large. Maximum size is 1MB."}), 413

    @app.errorhandler(500)
    def _server_error(err):
        app.logger.exception("Unhandled server error")
        return jsonify({"error": "Internal server error."}), 500


# --------------------------------------------------------------------------- #
# The factory
# --------------------------------------------------------------------------- #

def create_app(config_name: str | None = None) -> Flask:
    """Create and configure the Flask application."""
    app = Flask(__name__)

    # 1. Configuration -------------------------------------------------------
    if config_name is None:
        cfg = get_config()
    else:
        cfg = config.get(config_name, config["default"])
    app.config.from_object(cfg)

    # 2. Extensions ----------------------------------------------------------
    db.init_app(app)
    login_manager.init_app(app)

    # API returns JSON 401 for unauthenticated requests — no HTML login page.
    @login_manager.unauthorized_handler
    def _unauthorized():
        return jsonify({"error": "Authentication required."}), 401

    # 3. SQLite foreign keys (dev convenience) -------------------------------
    if str(app.config["SQLALCHEMY_DATABASE_URI"]).startswith("sqlite"):
        with app.app_context():
            _enable_sqlite_foreign_keys()

    # 4. Auto-create tables in dev/test (production uses Alembic migrations) -
    if app.config.get("DEBUG") or app.config.get("TESTING"):
        with app.app_context():
            db.create_all()

    # 5. Error handlers ------------------------------------------------------
    _register_error_handlers(app)

    # 6. Health check --------------------------------------------------------
    @app.route("/health")
    def health():
        try:
            db.session.execute(text("SELECT 1"))
            db_ok = True
        except SQLAlchemyError:
            db_ok = False
        body = {
            "status": "ok" if db_ok else "degraded",
            "db": "ok" if db_ok else "down",
        }
        return jsonify(body), (200 if db_ok else 503)

    # 7. Routes (registered in a later file via Blueprint) -------------------
    # from .routes import api_bp
    # app.register_blueprint(api_bp)

    return app
