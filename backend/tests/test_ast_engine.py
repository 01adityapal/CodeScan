"""
Tests for CodeScan AST engine.

Covers every detection rule, the complexity estimator, and the
"stay silent when uncertain" policy.

Run from codescan/backend/:    pytest -q tests/test_ast_engine.py
"""

import sys
from pathlib import Path

# Make `app` importable when pytest is invoked from codescan/backend/
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest

from app.ast_engine import (
    analyze,
    ISSUE_NESTED_LOOP,
    ISSUE_TRIPLE_NESTED,
    ISSUE_INEFFICIENT_LOOKUP,
    ISSUE_UNOPTIMISED_RECURSION,
    ISSUE_BLOCKING_IO,
    SEVERITY_HIGH,
    SEVERITY_MED,
    SEVERITY_LOW,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def types(result):
    return sorted(i["type"] for i in result["issues"])


def severities(result):
    return sorted(i["severity"] for i in result["issues"])


# ---------------------------------------------------------------------------
# Rule 1 + 2: Nested loops
# ---------------------------------------------------------------------------

class TestNestedLoops:

    def test_single_variable_loop_is_NOT_flagged(self):
        code = "for i in items:\n    print(i)\n"
        r = analyze(code)
        assert r["status"] == "success"
        assert r["issues"] == []
        assert r["complexity"] == "Likely O(n)"

    def test_constant_loop_is_NOT_flagged(self):
        # range(10) is O(1) — must NOT be flagged
        code = "for i in range(10):\n    print(i)\n"
        r = analyze(code)
        assert r["issues"] == []
        assert r["complexity"] == "Likely O(1) or better"

    def test_nested_constant_loops_are_NOT_flagged(self):
        code = "for i in range(10):\n    for j in range(10):\n        print(i, j)\n"
        r = analyze(code)
        assert r["issues"] == []
        assert r["complexity"] == "Likely O(1) or better"

    def test_two_nested_variable_loops_are_flagged(self):
        code = "for i in items:\n    for j in items:\n        print(i, j)\n"
        r = analyze(code)
        assert r["complexity"] == "Likely O(n^2)"
        assert len(r["issues"]) == 1
        assert r["issues"][0]["type"] == ISSUE_NESTED_LOOP
        assert r["issues"][0]["severity"] == SEVERITY_HIGH

    def test_triple_nested_variable_loops_are_flagged(self):
        code = (
            "for i in a:\n"
            "    for j in b:\n"
            "        for k in c:\n"
            "            print(i, j, k)\n"
        )
        r = analyze(code)
        assert r["complexity"] == "Likely O(n^3)"
        # innermost two loops get flagged (depth 2 and depth 3)
        flagged_types = [i["type"] for i in r["issues"]]
        assert ISSUE_TRIPLE_NESTED in flagged_types

    def test_mixed_constant_and_variable_loop(self):
        # Inner loop is range(10) -> O(1); outer loop is variable -> O(n). Not nested.
        code = "for i in items:\n    for j in range(10):\n        print(i, j)\n"
        r = analyze(code)
        assert r["complexity"] == "Likely O(n)"
        assert r["issues"] == []

    def test_range_len_is_variable(self):
        # range(len(items)) is input-dependent
        code = "for i in items:\n    for j in range(len(items)):\n        pass\n"
        r = analyze(code)
        assert r["complexity"] == "Likely O(n^2)"

    def test_range_of_variable_is_variable(self):
        # range(n) where n is a name -> variable
        code = "for i in range(n):\n    for j in range(n):\n        pass\n"
        r = analyze(code)
        assert r["complexity"] == "Likely O(n^2)"


# ---------------------------------------------------------------------------
# Rule 3: Inefficient list/tuple lookup inside a loop
# ---------------------------------------------------------------------------

class TestInefficientLookup:

    def test_list_lookup_with_in(self):
        code = "items = [1, 2, 3]\nfor x in data:\n    if x in items:\n        pass\n"
        r = analyze(code)
        assert any(i["type"] == ISSUE_INEFFICIENT_LOOKUP for i in r["issues"])

    def test_list_literal_in_loop(self):
        code = "for x in data:\n    if x in [1, 2, 3]:\n        pass\n"
        r = analyze(code)
        assert any(i["type"] == ISSUE_INEFFICIENT_LOOKUP for i in r["issues"])

    def test_list_constructor_in_loop(self):
        code = "for x in data:\n    if x in list(other):\n        pass\n"
        r = analyze(code)
        assert any(i["type"] == ISSUE_INEFFICIENT_LOOKUP for i in r["issues"])

    def test_index_call_in_loop(self):
        code = "items = [1, 2, 3]\nfor x in data:\n    items.index(x)\n"
        r = analyze(code)
        assert any(i["type"] == ISSUE_INEFFICIENT_LOOKUP for i in r["issues"])

    def test_count_call_in_loop(self):
        code = "items = [1, 2, 3]\nfor x in data:\n    items.count(x)\n"
        r = analyze(code)
        assert any(i["type"] == ISSUE_INEFFICIENT_LOOKUP for i in r["issues"])

    def test_set_lookup_is_NOT_flagged(self):
        # Sets have O(1) lookup — must NOT be flagged
        code = "seen = {1, 2, 3}\nfor x in data:\n    if x in seen:\n        pass\n"
        r = analyze(code)
        assert ISSUE_INEFFICIENT_LOOKUP not in types(r)

    def test_dict_lookup_is_NOT_flagged(self):
        code = "lookup = {'a': 1, 'b': 2}\nfor x in keys:\n    if x in lookup:\n        pass\n"
        r = analyze(code)
        assert ISSUE_INEFFICIENT_LOOKUP not in types(r)

    def test_set_constructor_is_NOT_flagged(self):
        code = "for x in data:\n    if x in set(other):\n        pass\n"
        r = analyze(code)
        assert ISSUE_INEFFICIENT_LOOKUP not in types(r)

    def test_unknown_container_is_NOT_flagged(self):
        # We can't determine the type of `items` -> stay silent (honesty policy)
        code = "for x in data:\n    if x in items:\n        pass\n"
        r = analyze(code)
        assert ISSUE_INEFFICIENT_LOOKUP not in types(r)

    def test_lookup_OUTSIDE_loop_is_NOT_flagged(self):
        code = "items = [1, 2, 3]\nx in items\n"
        r = analyze(code)
        assert r["issues"] == []


# ---------------------------------------------------------------------------
# Rule 4: Unoptimised recursion
# ---------------------------------------------------------------------------

class TestRecursion:

    def test_plain_recursion_is_flagged(self):
        code = (
            "def fib(n):\n"
            "    if n < 2: return n\n"
            "    return fib(n-1) + fib(n-2)\n"
        )
        r = analyze(code)
        assert any(i["type"] == ISSUE_UNOPTIMISED_RECURSION for i in r["issues"])

    def test_lru_cache_decorator_suppresses(self):
        code = (
            "from functools import lru_cache\n"
            "@lru_cache\n"
            "def fib(n):\n"
            "    if n < 2: return n\n"
            "    return fib(n-1) + fib(n-2)\n"
        )
        r = analyze(code)
        assert ISSUE_UNOPTIMISED_RECURSION not in types(r)

    def test_lru_cache_with_args_suppresses(self):
        code = (
            "from functools import lru_cache\n"
            "@lru_cache(maxsize=None)\n"
            "def fib(n):\n"
            "    if n < 2: return n\n"
            "    return fib(n-1) + fib(n-2)\n"
        )
        r = analyze(code)
        assert ISSUE_UNOPTIMISED_RECURSION not in types(r)

    def test_cache_decorator_suppresses(self):
        code = (
            "from functools import cache\n"
            "@cache\n"
            "def fib(n):\n"
            "    if n < 2: return n\n"
            "    return fib(n-1) + fib(n-2)\n"
        )
        r = analyze(code)
        assert ISSUE_UNOPTIMISED_RECURSION not in types(r)

    def test_memo_parameter_suppresses(self):
        code = (
            "def fib(n, memo=None):\n"
            "    if memo is None: memo = {}\n"
            "    if n in memo: return memo[n]\n"
            "    if n < 2: return n\n"
            "    memo[n] = fib(n-1, memo) + fib(n-2, memo)\n"
            "    return memo[n]\n"
        )
        r = analyze(code)
        assert ISSUE_UNOPTIMISED_RECURSION not in types(r)

    def test_non_recursive_function_is_NOT_flagged(self):
        code = "def add(a, b):\n    return a + b\n"
        r = analyze(code)
        assert r["issues"] == []


# ---------------------------------------------------------------------------
# Rule 5: Blocking I/O inside a loop
# ---------------------------------------------------------------------------

class TestBlockingIO:

    def test_requests_get_in_loop(self):
        code = "import requests\nfor u in urls:\n    requests.get(u)\n"
        r = analyze(code)
        assert any(i["type"] == ISSUE_BLOCKING_IO for i in r["issues"])

    def test_requests_post_in_loop(self):
        code = "import requests\nfor u in urls:\n    requests.post(u)\n"
        r = analyze(code)
        assert any(i["type"] == ISSUE_BLOCKING_IO for i in r["issues"])

    def test_time_sleep_in_loop(self):
        code = "import time\nfor _ in items:\n    time.sleep(1)\n"
        r = analyze(code)
        assert any(i["type"] == ISSUE_BLOCKING_IO for i in r["issues"])

    def test_open_read_in_loop(self):
        code = "for p in paths:\n    open(p).read()\n"
        r = analyze(code)
        assert any(i["type"] == ISSUE_BLOCKING_IO for i in r["issues"])

    def test_urllib_urlopen_in_loop(self):
        code = "import urllib\nfor u in urls:\n    urllib.urlopen(u)\n"
        r = analyze(code)
        assert any(i["type"] == ISSUE_BLOCKING_IO for i in r["issues"])

    def test_requests_OUTSIDE_loop_is_NOT_flagged(self):
        code = "import requests\nrequests.get('https://example.com')\n"
        r = analyze(code)
        assert r["issues"] == []


# ---------------------------------------------------------------------------
# Parse errors
# ---------------------------------------------------------------------------

class TestParseErrors:

    def test_invalid_syntax_returns_parse_error(self):
        r = analyze("def bad syntax(:\n")
        assert r["status"] == "parse_error"
        assert r["issues"] == []
        assert r["parse_error"] is not None

    def test_empty_code_is_valid(self):
        r = analyze("")
        assert r["status"] == "success"
        assert r["issues"] == []


# ---------------------------------------------------------------------------
# Complexity estimator
# ---------------------------------------------------------------------------

class TestComplexity:

    def test_no_loops(self):
        r = analyze("x = 1 + 2\nprint(x)\n")
        assert r["complexity"] == "Likely O(1) or better"

    def test_single_variable_loop(self):
        r = analyze("for x in data:\n    print(x)\n")
        assert r["complexity"] == "Likely O(n)"

    def test_two_nested_variable_loops(self):
        r = analyze("for x in data:\n    for y in data:\n        pass\n")
        assert r["complexity"] == "Likely O(n^2)"

    def test_three_nested_variable_loops(self):
        code = "for x in a:\n    for y in b:\n        for z in c:\n            pass\n"
        r = analyze(code)
        assert r["complexity"] == "Likely O(n^3)"


# ---------------------------------------------------------------------------
# Integration: real-ish code snippets
# ---------------------------------------------------------------------------

class TestIntegration:

    def test_real_world_nested_loop(self):
        code = (
            "def find_pairs(items):\n"
            "    pairs = []\n"
            "    for a in items:\n"
            "        for b in items:\n"
            "            if a != b:\n"
            "                pairs.append((a, b))\n"
            "    return pairs\n"
        )
        r = analyze(code)
        assert r["complexity"] == "Likely O(n^2)"
        assert ISSUE_NESTED_LOOP in types(r)

    def test_real_world_with_multiple_issues(self):
        code = (
            "items = [1, 2, 3, 4]\n"
            "for x in data:\n"
            "    for y in data:\n"
            "        if x in items:\n"
            "            pass\n"
        )
        r = analyze(code)
        # Should flag: nested loop + inefficient lookup
        assert ISSUE_NESTED_LOOP in types(r)
        assert ISSUE_INEFFICIENT_LOOKUP in types(r)

    def test_clean_code_produces_no_issues(self):
        code = (
            "from functools import lru_cache\n\n"
            "@lru_cache\n"
            "def fib(n):\n"
            "    if n < 2: return n\n"
            "    return fib(n-1) + fib(n-2)\n\n"
            "seen = set()\n"
            "for x in data:\n"
            "    if x not in seen:\n"
            "        seen.add(x)\n"
        )
        r = analyze(code)
        assert r["issues"] == []
        assert r["complexity"] == "Likely O(n)"
