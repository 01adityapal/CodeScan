"""
CodeScan Groq Client + Circuit Breaker
=======================================
Wraps the Groq API for plain-English explanations of detected issues.

Key design decisions:
    1. Groq is an ENHANCEMENT, never a dependency.
       If it fails for any reason, AST results still return with
       ai_status: "unavailable". The endpoint never breaks.
    2. Circuit Breaker (pybreaker): after 3 consecutive failures, the
       breaker opens for 60 seconds and stops calling Groq entirely.
       Prevents cascading timeouts when Groq is down.
    3. The prompt is crafted to get concise, student-friendly explanations.
    4. Full code is sent to Groq (it's ephemeral, never stored).
       Only a 500-char preview is persisted in the DB (by the route handler).
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

import pybreaker

logger = logging.getLogger(__name__)

# The groq SDK is imported conditionally so tests can run without it.
try:
    from groq import Groq
    _GROQ_SDK_AVAILABLE = True
except ImportError:
    _GROQ_SDK_AVAILABLE = False

# Truncate code in the prompt to this many characters to stay within
# Groq token limits even for large snippets.
_MAX_CODE_CHARS = 3000

# Max tokens for the response (keeps explanation concise).
_MAX_TOKENS = 500


class GroqClient:
    """Stateful wrapper around the Groq API with circuit-breaker protection.

    One instance per app (created by the route handler or app factory).
    The breaker is per-instance; in Gunicorn each worker has its own instance,
    so each worker trips independently — which is the correct conservative
    behaviour (no cross-process state needed).

    If you later want all Gunicorn workers to share breaker state, back it
    with Redis: pybreaker.CircuitRedisStorage(redis_url).
    """

    def __init__(
        self,
        api_key: str,
        model: str = "llama-3.1-8b-instant",
        fail_max: int = 3,
        reset_timeout: int = 60,
    ):
        # Only create the real Groq client if a key is provided AND the SDK
        # is available. Otherwise explain() returns unavailable immediately.
        self._client: Optional[Groq] = (
            Groq(api_key=api_key)
            if (api_key and _GROQ_SDK_AVAILABLE)
            else None
        )
        self._model = model
        self._breaker = pybreaker.CircuitBreaker(
            fail_max=fail_max,
            reset_timeout=reset_timeout,
            name="groq_api",
        )

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #

    def explain(
        self,
        code: str,
        issues: List[Dict[str, Any]],
        complexity: str,
    ) -> Dict[str, Optional[str]]:
        """Ask Groq for a plain-English explanation of the detected issues.

        Always returns a dict; never raises.

        Returns:
            {"explanation": "...", "ai_status": "available"}     — success
            {"explanation": None,   "ai_status": "unavailable"}  — any failure
        """
        if self._client is None:
            return {"explanation": None, "ai_status": "unavailable"}

        prompt = _build_prompt(code, issues, complexity)

        try:
            text = self._breaker.call(self._call_groq, prompt)
            return {"explanation": text, "ai_status": "available"}
        except pybreaker.CircuitBreakerError:
            logger.warning("Groq circuit breaker is OPEN. Skipping API call.")
            return {"explanation": None, "ai_status": "unavailable"}
        except Exception as exc:
            # Log the real error so it shows up in the Flask terminal.
            # Still return unavailable gracefully (Groq is an enhancement only).
            logger.error("Groq API call failed: %s", exc, exc_info=True)
            return {"explanation": None, "ai_status": "unavailable"}

    # ------------------------------------------------------------------ #
    # Internals
    # ------------------------------------------------------------------ #

    def _call_groq(self, prompt: str) -> str:
        """The actual Groq API call. Protected by the circuit breaker.

        On success returns the explanation text.
        On failure raises an exception (which the breaker counts).
        """
        response = self._client.chat.completions.create(
            model=self._model,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are a senior Python developer reviewing code "
                        "for a student. Be concise and practical. "
                        "Speak directly to the reader. "
                        "Do NOT mention that an analyzer found these issues."
                    ),
                },
                {"role": "user", "content": prompt},
            ],
            temperature=0.3,   # low temperature for deterministic code advice
            max_tokens=_MAX_TOKENS,
        )
        return response.choices[0].message.content.strip()


# ------------------------------------------------------------------ #
# Prompt builder (module-level — no state, independently testable)
# ------------------------------------------------------------------ #

def _build_prompt(
    code: str,
    issues: List[Dict[str, Any]],
    complexity: str,
) -> str:
    """Build the user-message prompt sent to Groq.

    Structure:
        1. State the overall complexity estimate
        2. List each issue with its line, type, severity, and message
        3. Include the (possibly truncated) code
        4. Ask for a concise explanation + concrete fix per issue
    """
    # Truncate long code to stay within token budget.
    truncated = code[:_MAX_CODE_CHARS]
    if len(code) > _MAX_CODE_CHARS:
        truncated += "\n# ... (code truncated)"

    # Format the issue list.
    if not issues:
        issues_text = "No specific performance issues detected."
    else:
        issues_text = "\n".join(
            f"- Line {i['line']}: {i['type']} ({i['severity']}) — {i['message']}"
            for i in issues
        )

    return f"""Here is a Python snippet with the following analysis:

Overall complexity: {complexity}

Issues found:
{issues_text}

The code:
```python
{truncated}
```

For each issue found, explain:
1. What the problem is and why it matters for performance
2. A concrete fix (show improved code if applicable)

Keep it concise — like a helpful code review comment. Do NOT mention any analyzer."""
