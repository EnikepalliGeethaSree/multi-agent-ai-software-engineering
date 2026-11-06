"""Phase 2: suggested fixes (Ruff autofix + verified LLM fixes), actionability filter, type checking."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from marl_agents.agents.code_review.fixes import FixGenerator
from marl_agents.config import Settings
from marl_agents.core.fixes import TextEdit, apply_edits, make_fix, replace_lines
from marl_agents.core.schemas import Finding
from marl_agents.findings.actionability import assess, filter_actionable
from marl_agents.llm import MockLLMProvider
from marl_agents.static_analysis import RuffAnalyzer
from marl_agents.static_analysis.ruff_analyzer import find_ruff
from marl_agents.static_analysis.type_check import TypeCheckAnalyzer, mypy_available

needs_ruff = pytest.mark.skipif(find_ruff() is None, reason="ruff not installed")
needs_mypy = pytest.mark.skipif(not mypy_available(), reason="mypy not installed")


# ---- text edits & fix objects -------------------------------------------------------------------


def test_apply_edits_and_replace_lines() -> None:
    text = "import os\nimport sys\nx = 1\n"
    assert apply_edits(text, [TextEdit(1, 1, 2, 1, "")]) == "import sys\nx = 1\n"
    edits = [TextEdit(3, 5, 3, 6, "2"), TextEdit(1, 8, 1, 10, "re")]  # any order
    assert apply_edits(text, edits) == "import re\nimport sys\nx = 2\n"
    assert replace_lines("a\nb\nc\n", 2, 2, "B1\nB2") == "a\nB1\nB2\nc\n"
    assert replace_lines("a\nb\nc\n", 2, 1, "new") == "a\nnew\nb\nc\n"  # insertion


def test_make_fix_minimal_range_and_diff() -> None:
    fix = make_fix("m.py", "a\nb\nc\nd\n", "a\nB\nc\nd\n", "llm", checks=["parses"])
    assert fix is not None and (fix.start_line, fix.end_line, fix.replacement) == (2, 2, "B")
    assert "-b" in fix.diff and "+B" in fix.diff and fix.diff.startswith("--- a/m.py")
    assert make_fix("m.py", "same\n", "same\n", "llm") is None


@needs_ruff
def test_ruff_autofix_attached_safe_is_verified(make_index) -> None:  # type: ignore[no-untyped-def]
    index = make_index({"m.py": "import os\n\n\ndef f(x=[]):\n    return x\n"})
    out = RuffAnalyzer().analyze(index.repo, index, ["m.py"])
    by_rule = {f.rule_id: f for f in out.findings}
    f401 = by_rule["F401"].suggested_fix
    assert f401 is not None and f401.verified and f401.source == "ruff"
    assert "-import os" in f401.diff
    b006 = by_rule["B006"].suggested_fix
    assert b006 is not None and not b006.verified  # Ruff marks it unsafe: human review
    assert "used_coupons" not in b006.diff and "x=None" in b006.diff


# ---- actionability ------------------------------------------------------------------------------


def _llm(**kw: object) -> Finding:
    base: dict[str, object] = {
        "id": "X",
        "file": "a.py",
        "start_line": 1,
        "end_line": 1,
        "category": "bug",
        "severity": "high",
        "title": "Off-by-one skips the first item",
        "description": "order_total iterates from index 1, so the first item is never added.",
        "recommendation": "Iterate over all items: `for item in items:`.",
        "evidence": ["for i in range(1, len(items)):"],
        "confidence": 0.8,
        "sources": ["llm"],
    }
    base.update(kw)
    return Finding.model_validate(base)


def test_actionability_rules() -> None:
    assert assess(_llm()).problems == []
    vague = _llm(
        description="Consider improving this code, it might want better handling overall.",
        recommendation="Make sure to review this.",
    )
    assert "vague wording without a concrete code reference" in assess(vague).problems
    assert "no concrete fix" in assess(_llm(recommendation=None)).problems
    assert (
        "asks a question instead of stating a problem"
        in assess(_llm(title="Why is this here?")).problems
    )
    # tool findings are concrete by construction
    assert assess(_llm(sources=["ruff"], recommendation=None, description="x")).problems == []


def test_filter_actionable_drops_and_downgrades() -> None:
    good = _llm()
    one = _llm(recommendation=None)  # one problem -> kept as info
    two = _llm(recommendation=None, description="Bad code.")  # two problems -> dropped
    kept, dropped, downgraded = filter_actionable([good, one, two])
    assert (len(kept), dropped, downgraded) == (2, 1, 1)
    assert kept[1].severity.value == "info" and kept[1].notes[-1].startswith("downgraded to info")


# ---- verified LLM fixes -------------------------------------------------------------------------

CODE = """def apply_coupon(total, coupon, used=[]):
    if coupon in used:
        return total
    used.append(coupon)
    return total - 10


def average(xs):
    return sum(xs) / len(xs)
"""


def _fix_reply(start: int, end: int, replacement: str) -> str:
    return json.dumps(
        {"start_line": start, "end_line": end, "replacement": replacement, "explanation": "fix"}
    )


@needs_ruff
@pytest.mark.parametrize(
    ("reply", "expect"),
    [
        (
            _fix_reply(
                1,
                1,
                "def apply_coupon(total, coupon, used=None):\n    used = [] if used is None else used",
            ),
            "verified",
        ),
        (
            _fix_reply(1, 1, "def apply_coupon(total, coupon, used=[], extra=[]):"),
            "introduces_issues",
        ),
        (_fix_reply(1, 1, "def apply_coupon(total, coupon, used=list()):"), "issue_still_present"),
        (_fix_reply(8, 9, "def average(xs):\n    return 0"), "outside_region"),
        (_fix_reply(1, 1, "def apply_coupon(total, coupon, used=None:"), "does_not_parse"),
    ],
)
def test_llm_fix_verification(make_index, settings: Settings, reply: str, expect: str) -> None:  # type: ignore[no-untyped-def]
    index = make_index({"coupons.py": CODE})
    static = RuffAnalyzer().analyze(index.repo, index, ["coupons.py"]).findings
    b006 = next(f for f in static if f.rule_id == "B006").model_copy(update={"suggested_fix": None})
    gen = FixGenerator(MockLLMProvider(responses=[reply]), index.repo, index, settings.ingestion)
    [out] = gen.run([b006])
    if expect == "verified":
        assert out.suggested_fix is not None and out.suggested_fix.verified
        assert "original issue (B006) no longer detected" in out.suggested_fix.checks
        assert gen.stats.verified == 1
    else:
        assert out.suggested_fix is None and gen.stats.rejected[expect] == 1


def test_llm_only_fix_is_checked_not_verified(make_index, settings: Settings) -> None:  # type: ignore[no-untyped-def]
    index = make_index({"coupons.py": CODE})
    finding = _llm(
        file="coupons.py",
        start_line=9,
        end_line=9,
        category="edge_case",
        severity="medium",
        evidence=["return sum(xs) / len(xs)"],
    )
    reply = _fix_reply(9, 9, "    return sum(xs) / len(xs) if xs else 0.0")
    llm = MockLLMProvider(responses=[reply])
    gen = FixGenerator(llm, index.repo, index, settings.ingestion)
    [out] = gen.run([finding])
    fix = out.suggested_fix
    assert fix is not None and not fix.verified and fix.source == "llm"
    assert "+    return sum(xs) / len(xs) if xs else 0.0" in fix.diff
    prompt = llm.calls[0][-1].content
    assert "Fix one review finding" in prompt and "    8 | def average(xs):" in prompt


def test_fix_candidates_skip_low_severity_tests_docs_and_secrets(
    make_index, settings: Settings
) -> None:  # type: ignore[no-untyped-def]
    index = make_index({"coupons.py": CODE})
    gen = FixGenerator(MockLLMProvider(), index.repo, index, settings.ingestion, max_fixes=10)
    cands = gen.candidates(
        [
            _llm(file="coupons.py", severity="low"),
            _llm(file="coupons.py", category="testing"),
            _llm(file="coupons.py", category="security", cwe="CWE-798"),
            _llm(file="coupons.py"),
        ]
    )
    assert len(cands) == 1


# ---- type checking ------------------------------------------------------------------------------

TYPED = """from typing import Optional


def find(name: str) -> Optional[str]:
    return None if name == "" else name


def shout(name: str) -> str:
    return find(name).upper()


def add(a: int, b: int) -> int:
    return a + b


def total() -> int:
    return add(1)
"""


@needs_mypy
def test_mypy_finds_cross_function_contract_errors(make_index) -> None:  # type: ignore[no-untyped-def]
    index = make_index({"app.py": TYPED})
    out = TypeCheckAnalyzer().analyze(index.repo, index, ["app.py"])
    rules = {(f.rule_id, f.start_line) for f in out.findings}
    assert ("TYPE-union-attr", 9) in rules  # Optional used without a None check
    assert ("TYPE-call-arg", 17) in rules  # missing argument
    assert all(f.sources[0].value == "mypy" for f in out.findings)


@needs_mypy
def test_mypy_never_loads_repo_plugins(make_index, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    marker = tmp_path / "PLUGIN_RAN"
    plugin = f"open(r'{marker}', 'w').write('x')\ndef plugin(version):\n    raise SystemExit\n"
    index = make_index(
        {
            "app.py": TYPED,
            "evil_plugin.py": plugin,
            "mypy.ini": "[mypy]\nplugins = evil_plugin\n",
            "pyproject.toml": "[tool.mypy]\nplugins = ['evil_plugin']\n",
        }
    )
    out = TypeCheckAnalyzer().analyze(index.repo, index, ["app.py"])
    assert not marker.exists(), "mypy loaded a plugin from the analyzed repository"
    assert out.findings  # still analyzed normally


def test_type_checker_ignored_when_unavailable(make_index, monkeypatch: pytest.MonkeyPatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr("marl_agents.static_analysis.type_check.mypy_available", lambda: False)
    out = TypeCheckAnalyzer().analyze(
        make_index({"a.py": "x = 1\n"}).repo, make_index({"a.py": "x = 1\n"}), ["a.py"]
    )
    assert out.skipped and "mypy is not installed" in out.errors[0]


@needs_ruff
def test_fix_verification_on_a_later_line_regression(make_index, settings: Settings) -> None:  # type: ignore[no-untyped-def]
    # Windows bug: re-materialised files had CRLF translated twice, doubling every line number,
    # so every fix below line 1 was rejected as "issue_still_present".
    code = '"""Module."""\n\nimport json\n\n\ndef apply_coupon(total, coupon, used=[]):\n    used.append(coupon)\n    return json.dumps(used)\n'
    index = make_index({"coupons.py": code})
    b006 = next(
        f
        for f in RuffAnalyzer().analyze(index.repo, index, ["coupons.py"]).findings
        if f.rule_id == "B006"
    ).model_copy(update={"suggested_fix": None})
    assert b006.start_line == 6
    reply = _fix_reply(
        6, 6, "def apply_coupon(total, coupon, used=None):\n    used = [] if used is None else used"
    )
    gen = FixGenerator(MockLLMProvider(responses=[reply]), index.repo, index, settings.ingestion)
    [out] = gen.run([b006])
    assert out.suggested_fix is not None and out.suggested_fix.verified, gen.stats.as_dict()


def test_materialised_files_keep_exact_bytes(settings: Settings) -> None:
    from marl_agents.ingestion import load_files

    text = "a = 1\nb = 2\r\nc = 3\n"
    repo = load_files({"m.py": text}, settings.ingestion)
    again = load_files({"m.py": repo.read_text("m.py")}, settings.ingestion)
    on_disk = (again.root / "m.py").read_bytes()
    assert on_disk.count(b"\n") == 3 and b"\r\r" not in on_disk
