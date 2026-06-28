"""
CodeScan Groq client
====================
Wraps the Groq AI API to produce plain-English explanations of the issues
the AST engine detected. Groq is treated as an ENHANCEMENT, never a
dependency — if it's unavailable, the endpoint still returns the AST
analysis with `ai_status: unavailable`.

Resilience via the Circuit Breaker pattern (pybreaker):
    - After 3 consecutive Groq failures, the breaker TRIPS OPEN for 60s.
    - While open, we stop hitting Groq immediately (saving latency and
      Groq free-tier quota) and return None.
    - After 60s the breaker enters HALF-OPEN and probes with one call.
    - A successful probe CLOSES the breaker; a failure re-opens it.

Key decisions:
    * No API key configured  -> returns None immediately (NO breaker trip;
      this is a configuration fact, not a transient failure).
    * No issues to explain    -> returns a short "clean code" message.
    * Any transient failure   -> caught and surfaced as None, breaker trips.
    * Code truncated to 4000 chars in the prompt (free-tier token budget).

Usage from a route:
    explanation = explain_issues(code, issues, complexity)
    # explanation is str or None
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from pybreaker import CircuitBreaker, CircuitBreakerError

logger = logging.getLogger("codescan.groq")

# --------------------------------------------------------------------------- #
# Circuit breaker — module-level singleton (shared across all requests)
# fail_max=3: after 3 consecutive failures the breaker trips open
# reset_timeout=60: wait 60 seconds before half-open probe
# --------------------------------------------------------------------------- #
groq_breaker = CircuitBreaker(
    fail_max=3,
    reset_timeout=60,
    name="groq",
)

# Guardrails for the prompt: keeps us inside Groq's free-tier token budget.
MAX_CODE_CHARS_IN_PROMPT = 4000
MAX_EXPLANATION_TOKENS = 500

# Default system prompt — the "senior dev" persona.
SYSTEM_PROMPT = (
    "You are a senior Python engineer reviewing code for performance. "
    "Be concise. Use plain English, not jargon. "
    "For each issue, give a 1-2 sentence explanation of WHY it's slow, "
    "then a concrete fix as a short code snippet when helpful. "
    "Keep the total response under 300 words. "
    "Do not invent issues the AST did not report."
)


# --------------------------------------------------------------------------- #
# Prompt builder — pure function, easy to unit-test
# --------------------------------------------------------------------------- #

def build_prompt(
    code: str,
    issues: List[Dict[str, Any]],
    complexity: Optional[str],
) -> List[Dict[str, str]]:
    """Construct the messages list for the Groq chat API.

    Separate from the API call so tests can assert on prompt content without
    hitting the network.
    """
    # Truncate very long code to protect token budget.
    if len(code) > MAX_CODE_CHARS_IN_PROMPT:
        truncated = code[:MAX_CODE_CHARS_IN_PROMPT] + "\n# ... (truncated)"
    else:
        truncated = code

    if not issues:
        user = (
            "Here is the code I'm reviewing:\n```\n" + truncated + "\n```\n\n"
            "AST analysis found NO issues. Estimated complexity: "
            + (complexity or "unknown") + ".\n\n"
            "Confirm in 2-3 sentences that the code looks clean."
        )
    else:
        issue_lines = []
        for i in issues:
            issue_lines.append(
                f"- line {i.get('line', '?')}: "
                f"{i.get('type', 'Issue')} "
                f"[{i.get('severity', 'unknown')}] — "
                f"{i.get('message', '')}"
            )
        issues_block = "\n".join(issue_lines)

        user = (
            "Here is the code I'm reviewing:\n```\n" + truncated + "\n```\n\n"
            "AST analysis found these issues:\n" + issues_block + "\n\n"
            "Estimated complexity: " + (complexity or "unknown") + ".\n\n"
            "For each issue, give me a 1-2 sentence explanation of WHY it's slow "
            "and a concrete fix. Keep the total response under 300 words."
        )

    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user},
    ]


# --------------------------------------------------------------------------- #
# The actual Groq call — wrapped by the circuit breaker
# --------------------------------------------------------------------------- #

def _raw_groq_call(api_key: str, model: str, messages: List[Dict[str, str]]) -> str:
    """Make a single blocking call to Groq. Raises on any failure.

    The circuit breaker decorator catches these exceptions and counts them.
    """
    # Imported inside the function so the module still imports cleanly if
    # the groq SDK is not installed (tests / offline dev).
    from groq import Groq

    client = Groq(api_key=api_key)
    completion = client.chat.completions.create(
        model=model,
        messages=messages,
        temperature=0.3,
        max_tokens=MAX_EXPLANATION_TOKENS,
    )
    content = completion.choices[0].message.content
    if not content:
        raise RuntimeError("Groq returned an empty response.")
    return content.strip()


# The breaker-wrapped version. Any exception inside _raw_groq_call increments
# the failure counter; after 3 in a row the breaker opens for 60s.
_guarded_groq_call = groq_breaker(_raw_groq_call)


# --------------------------------------------------------------------------- #
# Public entry point
# --------------------------------------------------------------------------- #

def explain_issues(
    code: str,
    issues: List[Dict[str, Any]],
    complexity: Optional[str],
    *,
    api_key: str = "",
    model: str = "llama-3.1-8b-instant",
) -> Optional[str]:
    """Ask Groq for a plain-English explanation of the detected issues.

    Returns:
        A string explanation on success, or None if:
          - no API key is configured (config, not a failure -> no breaker trip)
          - the circuit breaker is OPEN (we're cooling off after failures)
          - the Groq API call fails (counts toward the breaker)
          - any unexpected error occurs (counts toward the breaker)

    Callers should treat None as "AI unavailable" and render the AST-only view.
    """
    # --- Configuration guard: don't trip the breaker on a missing key ---
    if not api_key:
        logger.info("groq_skip_no_key")
        return None

    messages = build_prompt(code, issues, complexity)

    try:
        return _guarded_groq_call(api_key, model, messages)
    except CircuitBreakerError:
        # Breaker is OPEN — Groq has failed 3 times recently, we're cooling off.
        logger.warning("groq_circuit_open")
        return None
    except Exception as exc:
        # Any other failure (timeout, auth, network, SDK bug, rate limit, ...).
        # The breaker has already counted this one.
        logger.warning("groq_call_failed", extra={"error": str(exc)})
        return None
