"""
CodeScan AST Engine v1.0
========================
Walks the Python AST and detects real performance problems.

Design principles (from the project doc):
  1. We NEVER execute user code — we only READ the syntax tree.
  2. We are HONEST about complexity — we only flag O(n²) when loops iterate
     over input-dependent data, not over `range(10)` (which is O(1)).
  3. When we can't prove a container's type, we stay silent rather than mislead.

Detection rules:
  - Nested loop over variables              → HIGH  "Likely O(n²)"
  - Triple nested loop over variables       → HIGH  "Likely O(n³)"
  - Inefficient lookup (.index/.count/in) on list/tuple → MED
  - Unoptimised recursion (no @lru_cache, no memo)      → MED
  - Blocking I/O in loop (requests/urllib/open/time.sleep) → LOW

Public API:
  analyze(code: str) -> dict
    Returns: {
        "status": "success" | "parse_error",
        "complexity": "Likely O(n^2)" | ...,
        "issues": [ {"line": int, "type": str, "severity": str, "message": str}, ... ],
        "duration_ms": int,
        "parse_error": str | None
    }
"""

from __future__ import annotations

import ast
import time
from typing import Any, Dict, List, Optional

# ---------------------------------------------------------------------------
# Public constants — used by tests and by the API response
# ---------------------------------------------------------------------------

ISSUE_NESTED_LOOP = "Nested Loop"
ISSUE_TRIPLE_NESTED = "Triple Nested Loop"
ISSUE_INEFFICIENT_LOOKUP = "Inefficient Lookup"
ISSUE_UNOPTIMISED_RECURSION = "Unoptimised Recursion"
ISSUE_BLOCKING_IO = "Blocking I/O in Loop"

SEVERITY_HIGH = "High"
SEVERITY_MED = "Med"
SEVERITY_LOW = "Low"

# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def analyze(code: str) -> Dict[str, Any]:
    """Run all detection rules on the given Python source code.

    Returns a dict with status, issues, complexity, duration_ms and
    (optionally) a parse_error message.  Never raises for bad input —
    parse errors are surfaced via `status: parse_error`.
    """
    t0 = time.perf_counter()

    try:
        tree = ast.parse(code)
    except SyntaxError as exc:
        return {
            "status": "parse_error",
            "complexity": None,
            "issues": [],
            "duration_ms": _ms_since(t0),
            "parse_error": str(exc.msg) if exc.msg else "Invalid Python code.",
        }

    issues: List[Dict[str, Any]] = []
    issues.extend(_detect_nested_loops(tree))
    issues.extend(_detect_inefficient_lookup(tree))
    issues.extend(_detect_unoptimised_recursion(tree))
    issues.extend(_detect_blocking_io_in_loop(tree))

    complexity = _compute_complexity(tree)

    return {
        "status": "success",
        "complexity": complexity,
        "issues": issues,
        "duration_ms": _ms_since(t0),
        "parse_error": None,
    }

# ---------------------------------------------------------------------------
# Rule 1 + 2: Nested / triple nested loops over variables
# ---------------------------------------------------------------------------

def _detect_nested_loops(tree: ast.AST) -> List[Dict[str, Any]]:
    """Flag every For loop over a variable iterable whose parent chain
    contains at least one other For loop over a variable iterable.

    depth == 2  -> "Nested Loop"        Likely O(n²)
    depth >= 3  -> "Triple Nested Loop" Likely O(n³)
    """
    parents = _build_parent_map(tree)
    issues: List[Dict[str, Any]] = []

    for node in ast.walk(tree):
        if not isinstance(node, ast.For):
            continue
        if not _is_variable_iterable(node.iter):
            continue

        depth = _variable_for_depth(node, parents)
        if depth < 2:
            continue

        if depth >= 3:
            issues.append({
                "line": node.lineno,
                "type": ISSUE_TRIPLE_NESTED,
                "severity": SEVERITY_HIGH,
                "message": "Three or more nested loops over variables. Likely O(n³).",
            })
        else:
            issues.append({
                "line": node.lineno,
                "type": ISSUE_NESTED_LOOP,
                "severity": SEVERITY_HIGH,
                "message": "Nested loop over variables. Likely O(n²).",
            })

    return issues

# ---------------------------------------------------------------------------
# Rule 3: Inefficient list/tuple lookup inside a loop
# ---------------------------------------------------------------------------

def _detect_inefficient_lookup(tree: ast.AST) -> List[Dict[str, Any]]:
    """Flag three patterns when they occur inside a For loop body:
        1. `x in items`          — where items is a list or tuple
        2. `items.index(x)`     — always a linear scan
        3. `items.count(x)`     — always a linear scan

    Sets and dicts have O(1) lookup (or close to it) — we do NOT flag them.
    When we can't determine the container's type, we stay silent (honesty).
    """
    parents = _build_parent_map(tree)
    type_map = _collect_name_types(tree)
    issues: List[Dict[str, Any]] = []

    for node in ast.walk(tree):
        if not _is_inside_for(node, parents):
            continue

        # Pattern 1: `x in items` / `x not in items`
        if isinstance(node, ast.Compare):
            if any(isinstance(op, (ast.In, ast.NotIn)) for op in node.ops):
                # `in` with multiple comparators is `a in b in c`;
                # check the right side of each op for list/tuple.
                for comparator in node.comparators:
                    if _is_list_or_tuple(comparator, type_map):
                        issues.append({
                            "line": node.lineno,
                            "type": ISSUE_INEFFICIENT_LOOKUP,
                            "severity": SEVERITY_MED,
                            "message": "Membership test (`in`) on a list/tuple inside a loop. Use a set or dict for O(1) lookup.",
                        })
                        break

        # Pattern 2 + 3: `.index(...)` or `.count(...)` on a list/tuple
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            if node.func.attr in ("index", "count"):
                if _is_list_or_tuple(node.func.value, type_map):
                    method = node.func.attr
                    issues.append({
                        "line": node.lineno,
                        "type": ISSUE_INEFFICIENT_LOOKUP,
                        "severity": SEVERITY_MED,
                        "message": "`." + method + "()` on a list/tuple inside a loop. Use a dict/set for O(1) lookup.",
                    })

    return issues

# ---------------------------------------------------------------------------
# Rule 4: Unoptimised recursion
# ---------------------------------------------------------------------------

def _detect_unoptimised_recursion(tree: ast.AST) -> List[Dict[str, Any]]:
    """Flag a FunctionDef that:
        1. Calls itself (directly, by name), AND
        2. Has NO `@lru_cache` / `@cache` decorator, AND
        3. Has NO `memo` or `cache` parameter.
    """
    issues: List[Dict[str, Any]] = []

    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef):
            continue
        if not _is_recursive(node):
            continue
        if _is_memoized(node):
            continue
        issues.append({
            "line": node.lineno,
            "type": ISSUE_UNOPTIMISED_RECURSION,
            "severity": SEVERITY_MED,
            "message": f"Function `{node.name}` is recursive with no memoization. Use @functools.lru_cache or a memo dict to avoid exponential work.",
        })

    return issues

# ---------------------------------------------------------------------------
# Rule 5: Blocking I/O inside a loop
# ---------------------------------------------------------------------------

_BLOCKING_ATTRS = {
    # requests library
    "get", "post", "put", "delete", "patch", "head", "request",
    # urllib / generic
    "urlopen",
    # stdlib
    "sleep",
}

def _detect_blocking_io_in_loop(tree: ast.AST) -> List[Dict[str, Any]]:
    """Flag `requests.get/post/...`, `urllib.request.urlopen`, `time.sleep`,
    and `open(...).read()` when they appear inside a For loop body.
    """
    parents = _build_parent_map(tree)
    issues: List[Dict[str, Any]] = []

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if not _is_inside_for(node, parents):
            continue

        kind = _classify_blocking_call(node)
        if kind is None:
            continue

        issues.append({
            "line": node.lineno,
            "type": ISSUE_BLOCKING_IO,
            "severity": SEVERITY_LOW,
            "message": kind,
        })

    return issues

# ---------------------------------------------------------------------------
# Complexity estimator
# ---------------------------------------------------------------------------

def _compute_complexity(tree: ast.AST) -> str:
    """Honest complexity estimate based on the deepest nesting of
    variable-iterable For loops."""
    parents = _build_parent_map(tree)
    max_depth = 0

    for node in ast.walk(tree):
        if isinstance(node, ast.For) and _is_variable_iterable(node.iter):
            depth = _variable_for_depth(node, parents)
            if depth > max_depth:
                max_depth = depth

    if max_depth >= 3:
        return "Likely O(n^3)"
    if max_depth == 2:
        return "Likely O(n^2)"
    if max_depth == 1:
        return "Likely O(n)"
    return "Likely O(1) or better"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _ms_since(t0: float) -> int:
    return int((time.perf_counter() - t0) * 1000)


def _build_parent_map(tree: ast.AST) -> Dict[int, ast.AST]:
    """Map id(child) -> parent for every node in the tree."""
    parents: Dict[int, ast.AST] = {}
    for node in ast.walk(tree):
        for child in ast.iter_child_nodes(node):
            parents[id(child)] = node
    return parents


def _is_constant_range(node: ast.expr) -> bool:
    """True if `node` is a compile-time constant integer expression.

    Covers:
        - Literal integers:            10, 0xFF
        - Negations:                   -5
        - Constant arithmetic:         2 * 5, 10 + 2
        - range(constant):             range(10), range(2, 20, 2)
    """
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float, complex)):
        return True
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
        return _is_constant_range(node.operand)
    if isinstance(node, ast.BinOp):
        return _is_constant_range(node.left) and _is_constant_range(node.right)
    if isinstance(node, ast.Call):
        func = node.func
        if isinstance(func, ast.Name) and func.id == "range":
            return bool(node.args) and all(_is_constant_range(a) for a in node.args)
    return False


def _is_variable_iterable(node: ast.expr) -> bool:
    """A For-loop's `iter` is variable iff it's NOT a constant range."""
    return not _is_constant_range(node)


def _variable_for_depth(for_node: ast.For, parents: Dict[int, ast.AST]) -> int:
    """How many variable-iterable For loops (including `for_node` itself)
    contain `for_node`."""
    depth = 1
    cur = parents.get(id(for_node))
    while cur is not None:
        if isinstance(cur, ast.For) and _is_variable_iterable(cur.iter):
            depth += 1
        cur = parents.get(id(cur))
    return depth


def _is_inside_for(node: ast.AST, parents: Dict[int, ast.AST]) -> bool:
    """True if `node` sits (directly or transitively) inside any For body.

    We skip the node itself via the parent walk.
    """
    cur = parents.get(id(node))
    while cur is not None:
        if isinstance(cur, ast.For):
            return True
        cur = parents.get(id(cur))
    return False


def _collect_name_types(tree: ast.AST) -> Dict[str, str]:
    """Best-effort mapping of Name.id -> container type based on creation sites.

    Only records names assigned via a literal (`[1,2]`, `{1,2}`, `{'a':1}`, `(1,2)`)
    or a constructor (`list(...)`, `tuple(...)`, `set(...)`, `dict(...)`).
    Names with unknown/ambiguous creation are omitted — we stay silent for them.
    """
    mapping: Dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            target = node.targets[0]
            if isinstance(target, ast.Name):
                inferred = _infer_container_type(node.value)
                if inferred:
                    mapping[target.id] = inferred
    return mapping


def _infer_container_type(node: ast.expr) -> Optional[str]:
    if isinstance(node, ast.List):
        return "list"
    if isinstance(node, ast.Tuple):
        return "tuple"
    if isinstance(node, ast.Set):
        return "set"
    if isinstance(node, ast.Dict):
        return "dict"
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
        if node.func.id in ("list", "tuple", "set", "dict"):
            return node.func.id
    return None


def _is_list_or_tuple(node: ast.expr, type_map: Dict[str, str]) -> bool:
    """True if we can confidently say `node` evaluates to a list or tuple."""
    # Literal list / tuple
    if isinstance(node, (ast.List, ast.Tuple)):
        return True
    # list(...) / tuple(...) call
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
        if node.func.id in ("list", "tuple"):
            return True
    # Named variable whose creation we tracked
    if isinstance(node, ast.Name):
        return type_map.get(node.id) in ("list", "tuple")
    return False


def _is_recursive(func: ast.FunctionDef) -> bool:
    """True if the function body contains a Call to the function's own name."""
    for node in ast.walk(func):
        if node is func:
            continue
        if isinstance(node, ast.Call):
            fn = node.func
            if isinstance(fn, ast.Name) and fn.id == func.name:
                return True
    return False


def _is_memoized(func: ast.FunctionDef) -> bool:
    """True if the function has a recognised cache decorator or parameter."""
    for dec in func.decorator_list:
        if isinstance(dec, ast.Name) and dec.id in ("lru_cache", "cache"):
            return True
        if isinstance(dec, ast.Call) and isinstance(dec.func, ast.Name):
            if dec.func.id in ("lru_cache", "cache"):
                return True
        if isinstance(dec, ast.Attribute) and dec.attr in ("lru_cache", "cache"):
            return True
    for arg in func.args.args + func.args.kwonlyargs:
        if arg.arg in ("memo", "cache"):
            return True
    return False


def _classify_blocking_call(call: ast.Call) -> Optional[str]:
    """Return a human-readable message if `call` is a blocking I/O pattern."""
    fn = call.func

    # `requests.get / post / put / delete / patch / head / request`
    if isinstance(fn, ast.Attribute) and fn.attr in _BLOCKING_ATTRS:
        if isinstance(fn.value, ast.Name):
            if fn.value.id == "requests" and fn.attr in {
                "get", "post", "put", "delete", "patch", "head", "request",
            }:
                return f"`requests.{fn.attr}()` inside a loop is blocking. Consider batching or async I/O."
            if fn.value.id == "time" and fn.attr == "sleep":
                return "`time.sleep()` inside a loop blocks the whole thread."
            if fn.value.id == "urllib" and fn.attr == "urlopen":
                return "`urllib.request.urlopen()` inside a loop is blocking."

    # `open(...).read()` — open returns a file object whose `.read()` is called
    if isinstance(fn, ast.Attribute) and fn.attr == "read":
        if isinstance(fn.value, ast.Call) and isinstance(fn.value.func, ast.Name):
            if fn.value.func.id == "open":
                return "`open(...).read()` inside a loop — read once and process, or cache the data."

    return None
