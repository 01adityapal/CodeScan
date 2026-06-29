"""
CodeScan API routes (Blueprint)
===============================
The endpoints that make the product work:

    POST /api/v1/analyze       -> the core analysis endpoint
    GET  /api/v1/scans         -> current user's scan history
    GET  /api/v1/scans/<id>    -> one scan + its results (IDOR-protected)

How /analyze ties everything together:
    request body (code)  ->  ast_engine.analyze()  ->  issues + complexity
                          ->  groq_client.explain() ->  ai_status + explanation
                          ->  models (if logged in) ->  save scan + results
                          ->  JSON response (matches the v3 API contract)

Design notes:
    * Works with OR without login. Logged-in users get history saved;
      anonymous users still receive full analysis (better demo UX).
    * Groq failure never breaks the endpoint — ai_status reflects it.
    * Scan history is strictly filtered by current_user.id (IDOR-safe).
    * Only the first 500 chars of code are persisted — never the full code.
"""

from __future__ import annotations

import time
from typing import Any, Dict, List, Optional, Tuple

from flask import Blueprint, current_app, jsonify, request
from flask_login import current_user, login_required
from sqlalchemy.exc import IntegrityError

from .ast_engine import analyze
from .groq_client import GroqClient
from .models import Scan, ScanResult, db

api_bp = Blueprint("api", __name__, url_prefix="/api/v1")


# --------------------------------------------------------------------------- #
# Groq client — lazy singleton (one instance per Gunicorn worker)
# --------------------------------------------------------------------------- #

_groq_client: Optional[GroqClient] = None


def get_groq_client() -> GroqClient:
    """Return a process-wide GroqClient, created on first use.

    Created lazily so it picks up config at request time (not import time),
    and so the circuit breaker persists across requests in the same worker.
    """
    global _groq_client
    if _groq_client is None:
        _groq_client = GroqClient(
            api_key=current_app.config.get("GROQ_API_KEY", ""),
            model=current_app.config.get("GROQ_MODEL", "llama-3.1-8b-instant"),
        )
    return _groq_client


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #

def _extract_code() -> Tuple[Optional[str], Optional[Tuple]]:
    """Read & validate the 'code' field from the JSON request body.

    Returns (code, error_response):
        - (code_string, None)        on success
        - (None, (jsonify, status))  on validation failure
    """
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return None, (jsonify({"error": "Request body must be JSON."}), 400)

    code = payload.get("code")
    if code is None:
        return None, (jsonify({"error": "Missing 'code' field."}), 400)
    if not isinstance(code, str):
        return None, (jsonify({"error": "'code' must be a string."}), 400)
    if not code.strip():
        return None, (jsonify({"error": "Code cannot be empty."}), 400)
    return code, None


def _dedupe_issues(issues: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Remove duplicate (line, type) pairs so the DB UNIQUE constraint holds.

    The engine rarely produces dupes, but a defensive dedupe guarantees the
    UNIQUE(scan_id, line_number, issue_type) constraint never fails on insert.
    """
    seen = set()
    unique = []
    for issue in issues:
        key = (issue["line"], issue["type"])
        if key in seen:
            continue
        seen.add(key)
        unique.append(issue)
    return unique


# --------------------------------------------------------------------------- #
# POST /api/v1/analyze
# --------------------------------------------------------------------------- #

@api_bp.route("/analyze", methods=["POST"])
def analyze_code():
    t0 = time.perf_counter()

    code, err = _extract_code()
    if err is not None:
        return err

    # 1. AST analysis (never executes code; bounded by 1MB limit upstream)
    result = analyze(code)

    if result["status"] == "parse_error":
        # SyntaxError message is safe to surface (it's not a traceback).
        return jsonify({
            "status": "error",
            "error": "Invalid Python code.",
            "detail": result.get("parse_error"),
        }), 400

    issues = _dedupe_issues(result["issues"])
    complexity = result["complexity"]

    # 2. Groq explanation (enhancement only — never blocks the response)
    groq = get_groq_client().explain(code, issues, complexity)
    groq_explanation = groq["explanation"]
    ai_status = groq["ai_status"]

    # Total duration = AST + Groq (the user-perceived latency)
    duration_ms = int((time.perf_counter() - t0) * 1000)

    # 3. Persist to history if the user is logged in
    scan_id = None
    if current_user.is_authenticated:
        scan_id = _save_scan(
            code=code,
            issues=issues,
            complexity=complexity,
            duration_ms=duration_ms,
            groq_explanation=groq_explanation,
        )

    # 4. Build the v3 API-contract response
    return jsonify({
        "status": "success",
        "complexity": complexity,
        "issues": issues,
        "groq_explanation": groq_explanation,
        "ai_status": ai_status,
        "analysis_duration_ms": duration_ms,
        "scan_id": scan_id,
    }), 200


def _save_scan(code, issues, complexity, duration_ms, groq_explanation) -> Optional[int]:
    """Insert a Scan + its ScanResults. Returns the scan id, or None on failure."""
    try:
        scan = Scan(
            user_id=current_user.id,
            code_preview=code[: current_app.config["CODE_PREVIEW_LENGTH"]],
            complexity_score=complexity,
            issue_count=len(issues),
            analysis_duration_ms=duration_ms,
            analysis_version=current_app.config["ANALYSIS_VERSION"],
        )
        db.session.add(scan)
        db.session.flush()  # assigns scan.id without committing yet

        for issue in issues:
            db.session.add(ScanResult(
                scan_id=scan.id,
                line_number=issue["line"],
                issue_type=issue["type"],
                severity=issue["severity"],
                groq_suggestion=groq_explanation,
            ))

        db.session.commit()
        return scan.id
    except IntegrityError:
        # Defensive: a duplicate slipped past dedupe. Roll back but keep serving.
        db.session.rollback()
        return None


# --------------------------------------------------------------------------- #
# GET /api/v1/scans  (history — login required)
# --------------------------------------------------------------------------- #

@api_bp.route("/scans", methods=["GET"])
@login_required
def list_scans():
    """Return the current user's scan history, newest first."""
    limit = min(request.args.get("limit", default=20, type=int), 50)
    scans = (
        Scan.query
        .filter_by(user_id=current_user.id)
        .order_by(Scan.created_at.desc())
        .limit(limit)
        .all()
    )
    return jsonify({
        "status": "success",
        "count": len(scans),
        "scans": [s.to_dict() for s in scans],
    }), 200


# --------------------------------------------------------------------------- #
# GET /api/v1/scans/<id>  (one scan + results — login + IDOR-safe)
# --------------------------------------------------------------------------- #

@api_bp.route("/scans/<int:scan_id>", methods=["GET"])
@login_required
def get_scan(scan_id: int):
    """Return one scan and its results.

    IDOR protection: the query is filtered by BOTH scan_id AND current_user.id,
    so a user can never read another user's scan by guessing the id.
    """
    scan = (
        Scan.query
        .filter_by(id=scan_id, user_id=current_user.id)
        .first()
    )
    if scan is None:
        return jsonify({"error": "Scan not found."}), 404

    return jsonify({
        "status": "success",
        "scan": scan.to_dict(include_results=True),
    }), 200
