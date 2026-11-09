"""Duplicate-function, naming and endless-loop checks, on small synthetic files.

Synthetic fixtures show each rule fires where it should and stays quiet where it should. They do not
show how well the rules generalise to real code.
"""

from __future__ import annotations

from typing import Any

import pytest

from marl_agents.core.schemas import Category, Severity
from marl_agents.static_analysis.design_checks import DesignChecksAnalyzer, naming_problem
from marl_agents.static_analysis.loop_checks import LoopAnalyzer

BODY = """
    total = 0
    for item in items:
        if item > limit:
            total += item
    count = len(items)
    return total / count
"""


def findings(make_index: Any, files: dict[str, str], analyzer: Any) -> list[Any]:
    index = make_index(files)
    return analyzer.analyze(index.repo, index, sorted(files)).findings


def rule(found: list[Any], rule_id: str) -> list[Any]:
    return [f for f in found if f.rule_id == rule_id]


# ---- duplicated functions -----------------------------------------------------------------------


def test_a_renamed_copy_is_still_a_duplicate(make_index: Any) -> None:
    other = BODY.replace("total", "acc").replace("item", "x").replace("items", "values")
    files = {
        "a.py": f"def sum_over(items, limit):{BODY}",
        "b.py": f"def add_above(values, limit):{other.replace('xs', 'values')}",
    }
    dup = rule(findings(make_index, files, DesignChecksAnalyzer()), "AST-DUPLICATE-FUNCTION")
    assert len(dup) == 1
    f = dup[0]
    assert (f.file, f.start_line, f.category, f.severity) == (
        "b.py", 1, Category.MAINTAINABILITY, Severity.LOW,
    )  # fmt: skip
    assert "a.py:1" in f.title and f.evidence == ["def add_above(values, limit):"]
    assert f.recommendation and 0 < f.confidence <= 1


def test_different_logic_is_not_a_duplicate(make_index: Any) -> None:
    files = {
        "a.py": f"def sum_over(items, limit):{BODY}",
        "b.py": f"def other(items, limit):{BODY.replace('item > limit', 'item < limit')}",
    }
    assert not rule(findings(make_index, files, DesignChecksAnalyzer()), "AST-DUPLICATE-FUNCTION")


def test_small_lookalike_helpers_are_ignored(make_index: Any) -> None:
    small = "def a(x):\n    return x + 1\n\ndef b(y):\n    return y + 1\n"
    assert not rule(
        findings(make_index, {"a.py": small}, DesignChecksAnalyzer()), "AST-DUPLICATE-FUNCTION"
    )


def test_a_docstring_does_not_hide_a_duplicate(make_index: Any) -> None:
    files = {"a.py": f"def f(items, limit):{BODY}\n\ndef g(items, limit):\n    '''Doc.'''{BODY}"}
    assert (
        len(rule(findings(make_index, files, DesignChecksAnalyzer()), "AST-DUPLICATE-FUNCTION"))
        == 1
    )


# ---- naming -------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("kind", "name", "bad"),
    [
        ("function", "computeTotal", True), ("function", "compute_total", False),
        ("function", "_private_helper", False), ("function", "__init__", False),
        ("function", "visit_Name", False), ("function", "setUp", False),
        ("argument", "userName", True), ("argument", "user_name", False),
        ("class", "order_service", True), ("class", "OrderService", False),
        ("class", "_Internal", False),
    ],
)  # fmt: skip
def test_naming_follows_pep8(kind: str, name: str, bad: bool) -> None:
    assert (naming_problem(kind, name) is not None) is bad


def test_naming_findings_have_location_and_fix(make_index: Any) -> None:
    code = "class order_service:\n    def computeTotal(self, userName):\n        return userName\n"
    found = rule(findings(make_index, {"a.py": code}, DesignChecksAnalyzer()), "AST-NAMING")
    assert sorted((f.start_line, f.title) for f in found) == [
        (1, "Naming: class `order_service`"),
        (2, "Naming: function `computeTotal`, argument `userName`"),
    ]
    assert all(f.category is Category.STANDARDS and f.recommendation for f in found)


def test_clean_code_gets_no_design_findings(make_index: Any) -> None:
    code = "class Order:\n    def total(self, items):\n        return sum(items)\n"
    assert findings(make_index, {"a.py": code}, DesignChecksAnalyzer()) == []


# ---- endless loops ------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "code",
    [
        "def f():\n    while True:\n        print('tick')\n",
        "def f(n):\n    i = 0\n    while i < n:\n        total = i * 2\n",
        "def f(done):\n    while not done:\n        print('waiting')\n",
    ],
)
def test_loops_that_cannot_end_are_found(make_index: Any, code: str) -> None:
    found = findings(make_index, {"a.py": code}, LoopAnalyzer())
    assert [f.rule_id for f in found] == ["BUG-INFINITE-LOOP"]
    f = found[0]
    assert f.category is Category.BUG and f.severity is Severity.HIGH
    assert (
        f.start_line
        == code.splitlines().index(next(ln for ln in code.splitlines() if "while" in ln)) + 1
    )
    assert f.evidence and "while" in f.evidence[0] and f.recommendation


@pytest.mark.parametrize(
    "code",
    [
        "def f():\n    while True:\n        if ready():\n            break\n",
        "def f(n):\n    i = 0\n    while i < n:\n        i += 1\n",
        "def f(q):\n    while q:\n        q.pop()\n",
        "def f(q):\n    while q:\n        consume(q)\n",
        "def f():\n    while True:\n        return 1\n",
        "def f():\n    while True:\n        raise StopIteration\n",
        "def f():\n    while True:\n        sys.exit(0)\n",
        "def f():\n    while True:\n        yield 1\n",
        "def f(obj):\n    while obj.running:\n        pass\n",
        "def f():\n    while check():\n        pass\n",
        "async def f(done):\n    while not done:\n        await step()\n",
        "def f(xs):\n    while True:\n        for x in xs:\n            break\n        return\n",
    ],
)
def test_loops_that_can_end_are_left_alone(make_index: Any, code: str) -> None:
    assert findings(make_index, {"a.py": code}, LoopAnalyzer()) == []


def test_a_break_in_an_inner_loop_does_not_end_the_outer_one(make_index: Any) -> None:
    code = "def f(xs):\n    while True:\n        for x in xs:\n            break\n"
    assert [f.rule_id for f in findings(make_index, {"a.py": code}, LoopAnalyzer())] == [
        "BUG-INFINITE-LOOP"
    ]


def test_a_file_with_a_syntax_error_is_skipped(make_index: Any) -> None:
    assert findings(make_index, {"a.py": "def f(:\n    while True: pass\n"}, LoopAnalyzer()) == []


def test_passing_the_condition_variable_to_a_call_counts_as_a_possible_change(
    make_index: Any,
) -> None:
    # Conservative on purpose: a call could mutate a list the condition reads (`consume(q)`), so
    # the rule stays quiet rather than risk a false positive. An int passed to print is missed.
    code = "def f(n):\n    i = 0\n    while i < n:\n        print(i)\n"
    assert findings(make_index, {"a.py": code}, LoopAnalyzer()) == []
