from typing import Any

import pytest

from marl_agents.core.schemas import Category, Finding, FindingSource, Severity
from marl_agents.findings import (
    FindingValidator,
    RejectReason,
    ValidationStatus,
    apply_rubric,
    calibrate,
    deduplicate,
    is_duplicate,
    locate_evidence,
    passes_threshold,
    rank_and_number,
    validate_all,
)
from marl_agents.findings.redaction import mask_literals, redact_finding

CODE = """import os

def get_user(conn, name):
    q = f"SELECT * FROM users WHERE name = '{name}'"
    return conn.execute(q)

def average(xs):
    return sum(xs) / len(xs)

def spare():
    return 1
"""


def llm_finding(**kw: Any) -> Finding:
    data: dict[str, Any] = {
        "id": "TMP",
        "file": "app/db.py",
        "start_line": 4,
        "end_line": 4,
        "category": "security",
        "severity": "high",
        "title": "SQL injection",
        "description": "User input is interpolated into SQL.",
        "evidence": ["q = f\"SELECT * FROM users WHERE name = '{name}'\""],
        "confidence": 0.8,
        "sources": ["llm"],
    }
    data.update(kw)
    return Finding.model_validate(data)


@pytest.fixture
def repo(make_repo):  # type: ignore[no-untyped-def]
    return make_repo({"app/db.py": CODE})


# ---- evidence matching -----------------------------------------------------------------------


def test_locate_evidence_whitespace_gutter_and_partial_lines() -> None:
    lines = CODE.splitlines()
    assert locate_evidence(lines, "return   sum(xs)   /   len(xs)") == [(8, 8)]
    assert locate_evidence(lines, "  8 | return sum(xs) / len(xs)") == [(8, 8)]
    assert locate_evidence(lines, "> 8 | return sum(xs) / len(xs)") == [(8, 8)]
    multi = "def average(xs):\n    return sum(xs) / len(xs)"
    assert locate_evidence(lines, multi) == [(7, 8)]
    assert locate_evidence(lines, "```python\nreturn sum(xs) / len(xs)\n```") == [(8, 8)]
    assert locate_evidence(lines, "made_up_call()") == []
    assert locate_evidence(lines, "x") == []  # too short to be evidence
    assert len(locate_evidence(lines, "return")) == 3  # ambiguous: several hits


# ---- validation --------------------------------------------------------------------------------


def test_valid_llm_finding_passes(repo) -> None:  # type: ignore[no-untyped-def]
    out = FindingValidator(repo).validate(llm_finding())
    assert out.status is ValidationStatus.VALID and out.finding is not None


def test_unknown_file_rejected(repo) -> None:  # type: ignore[no-untyped-def]
    out = FindingValidator(repo).validate(llm_finding(file="app/ghost.py"))
    assert out.status is ValidationStatus.REJECTED and out.reason is RejectReason.UNKNOWN_FILE


def test_path_is_normalized(repo) -> None:  # type: ignore[no-untyped-def]
    out = FindingValidator(repo).validate(llm_finding(file=".\\app\\db.py"))
    assert out.status is ValidationStatus.REPAIRED and out.finding.file == "app/db.py"  # type: ignore[union-attr]


def test_hallucinated_evidence_rejected(repo) -> None:  # type: ignore[no-untyped-def]
    out = FindingValidator(repo).validate(llm_finding(evidence=["cursor.execute(raw_sql)"]))
    assert out.reason is RejectReason.EVIDENCE_NOT_FOUND


def test_missing_evidence_rejected(repo) -> None:  # type: ignore[no-untyped-def]
    out = FindingValidator(repo).validate(llm_finding(evidence=[]))
    assert out.reason is RejectReason.NO_EVIDENCE


def test_misplaced_lines_are_repaired_from_evidence(repo) -> None:  # type: ignore[no-untyped-def]
    f = llm_finding(
        start_line=10, end_line=10, evidence=["return sum(xs) / len(xs)"], category="edge_case"
    )
    out = FindingValidator(repo).validate(f)
    assert out.status is ValidationStatus.REPAIRED
    assert (out.finding.start_line, out.finding.end_line) == (8, 8)  # type: ignore[union-attr]
    assert any("lines moved" in n for n in out.finding.notes)  # type: ignore[union-attr]


def test_line_past_end_of_file_relocated_or_rejected(repo) -> None:  # type: ignore[no-untyped-def]
    fixed = FindingValidator(repo).validate(llm_finding(start_line=99, end_line=99))
    assert fixed.finding is not None and fixed.finding.start_line == 4
    static = llm_finding(start_line=99, end_line=99, sources=["ruff"], evidence=[])
    out = FindingValidator(repo).validate(static)
    assert out.reason is RejectReason.LINE_OUT_OF_RANGE


def test_evidence_far_away_and_ambiguous_is_rejected(repo) -> None:  # type: ignore[no-untyped-def]
    # 'return' appears 3 times, none near line 1 -> cannot tell which one is meant
    out = FindingValidator(repo).validate(
        llm_finding(start_line=1, end_line=1, evidence=["return"])
    )
    assert out.finding is None


def test_unverified_evidence_kept_when_not_required_but_capped(repo) -> None:  # type: ignore[no-untyped-def]
    v = FindingValidator(repo, require_llm_evidence=False)
    out = v.validate(llm_finding(evidence=["nonexistent()"]))
    assert out.finding is not None and "evidence could not be verified" in out.finding.notes


def test_scope_restricts_to_changed_lines(repo) -> None:  # type: ignore[no-untyped-def]
    v = FindingValidator(repo, scope={"app/db.py": [(8, 8)]}, scope_slack=0)
    assert v.validate(llm_finding()).reason is RejectReason.OUTSIDE_SCOPE
    ok = llm_finding(start_line=8, end_line=8, evidence=["return sum(xs) / len(xs)"])
    assert v.validate(ok).finding is not None


def test_static_findings_are_not_evidence_checked_but_clamped(repo) -> None:  # type: ignore[no-untyped-def]
    f = llm_finding(sources=["radon"], evidence=["cyclomatic complexity = 12"], end_line=500)
    out = FindingValidator(repo).validate(f)
    assert out.finding is not None and out.finding.end_line == len(CODE.splitlines())


def test_validate_all_reports_counts(repo) -> None:  # type: ignore[no-untyped-def]
    report = validate_all(
        FindingValidator(repo),
        [llm_finding(), llm_finding(file="nope.py"), llm_finding(evidence=["fake()"])],
    )
    assert len(report.accepted) == 1
    assert report.rejected_by_reason == {"unknown_file": 1, "evidence_not_found": 1}


# ---- dedup -----------------------------------------------------------------------------------


def f(**kw: Any) -> Finding:
    base: dict[str, Any] = {
        "id": "TMP",
        "file": "a.py",
        "start_line": 10,
        "end_line": 10,
        "category": "error_handling",
        "severity": "medium",
        "title": "t",
        "description": "d",
        "evidence": ["x"],
        "confidence": 0.6,
        "sources": ["ruff"],
    }
    base.update(kw)
    return Finding.model_validate(base)


def test_equivalent_rules_from_different_tools_merge() -> None:
    a = f(rule_id="E722", title="E722: Do not use bare except", confidence=0.9)
    b = f(
        rule_id="AST-SWALLOWED-EXCEPTION",
        sources=["ast"],
        end_line=11,
        title="Broad exception swallowed",
        description="A broad except catches every error and neither logs nor re-raises it.",
        confidence=0.8,
    )
    report = deduplicate([a, b])
    assert report.merged == 1
    m = report.findings[0]
    assert set(m.sources) == {FindingSource.RUFF, FindingSource.AST}
    assert m.confidence == pytest.approx(1 - 0.1 * 0.2)  # independent agreement
    assert (m.start_line, m.end_line) == (10, 11)
    assert "Related: E722" in m.description  # the merged finding's info is kept


def test_llm_and_tool_same_category_overlap_merge() -> None:
    tool = f(rule_id="S608", category="security", title="S608: Possible SQL injection")
    llm = f(
        sources=["llm"],
        category="security",
        title="Unsanitised input reaches the query",
        description="The name parameter is formatted into SQL.",
    )
    assert is_duplicate(tool, llm)


def test_llm_and_tool_compatible_categories_merge() -> None:
    tool = f(
        rule_id="F401",
        category="quality",
        start_line=3,
        end_line=3,
        title="F401: `os` imported but unused",
    )
    llm = f(sources=["llm"], category="standards", start_line=3, end_line=3, title="Unused import")
    assert is_duplicate(tool, llm)
    # but never across incompatible categories, e.g. a security issue next to a style issue
    sec = f(
        sources=["llm"], category="security", start_line=3, end_line=3, title="Hard-coded secret"
    )
    assert not is_duplicate(tool, sec)


def test_distinct_issues_are_not_merged() -> None:
    assert not is_duplicate(f(rule_id="F401"), f(rule_id="F401", start_line=20, end_line=20))
    assert not is_duplicate(
        f(category="security", rule_id="S105"), f(category="performance", rule_id="PERF401")
    )
    assert not is_duplicate(f(file="a.py"), f(file="b.py"))


def test_merge_keeps_highest_severity_and_is_transitive() -> None:
    a = f(rule_id="RADON-CC", category="maintainability", sources=["radon"], severity="medium")
    b = f(rule_id="AST-DEEP-NESTING", category="maintainability", sources=["ast"], severity="low")
    c = f(
        rule_id="AST-TOO-MANY-PARAMS", category="maintainability", sources=["ast"], severity="low"
    )
    report = deduplicate([a, b, c])
    assert len(report.findings) == 1 and report.merged == 2
    assert report.findings[0].severity is Severity.MEDIUM


# ---- severity rubric -----------------------------------------------------------------------------


def test_rubric_caps_and_floors() -> None:
    assert apply_rubric(f(category="standards", severity="high")).severity is Severity.LOW
    assert apply_rubric(f(category="documentation", severity="critical")).severity is Severity.LOW
    assert (
        apply_rubric(f(category="maintainability", severity="critical")).severity is Severity.MEDIUM
    )
    raised = apply_rubric(f(category="security", severity="low", sources=["llm"]))
    assert raised.severity is Severity.MEDIUM and raised.proposed_severity is Severity.LOW
    unsure = apply_rubric(f(category="bug", severity="critical", sources=["llm"], confidence=0.3))
    assert unsure.severity is Severity.MEDIUM
    no_ev = apply_rubric(f(category="bug", severity="high", evidence=[]))
    assert no_ev.severity is Severity.LOW
    # static tools keep their rule-table severity (e.g. S311 low security stays low)
    assert (
        apply_rubric(f(category="security", severity="low", rule_id="S311")).severity
        is Severity.LOW
    )


# ---- confidence & ranking --------------------------------------------------------------------


def test_calibration() -> None:
    assert calibrate(f(sources=["llm"], confidence=1.0)).confidence == 0.8
    assert calibrate(f(confidence=0.6, notes=["llm: false positive"])).confidence == 0.3
    assert calibrate(f(confidence=0.6, notes=["llm: confirmed"])).confidence == pytest.approx(0.72)
    moved = calibrate(f(sources=["llm"], confidence=0.5, notes=["lines moved from 1-1 to 3-3"]))
    assert moved.confidence == pytest.approx(0.34)


def test_rank_and_threshold() -> None:
    items = [
        f(severity="low", confidence=0.9),
        f(severity="critical", confidence=0.1),
        f(severity="high"),
    ]
    ranked = rank_and_number(items)
    assert [x.id for x in ranked] == ["CR-001", "CR-002", "CR-003"]
    assert [x.severity for x in ranked] == [Severity.CRITICAL, Severity.HIGH, Severity.LOW]
    assert passes_threshold(f(severity="critical", confidence=0.01), 0.5)
    assert not passes_threshold(f(severity="high", confidence=0.2), 0.5)


# ---- redaction ---------------------------------------------------------------------------------


def test_secret_evidence_is_masked() -> None:
    finding = f(category="security", cwe="CWE-798", evidence=['DB_PASSWORD = "sup3r-s3cret-pw"'])
    assert redact_finding(finding).evidence == ['DB_PASSWORD = "su****"']
    other = f(evidence=['name = "hello world"'])
    assert redact_finding(other) is other  # only credential findings are masked
    assert mask_literals("token: abcdefghijklmnopqrstuvwxyz") == "token: abcd****"
    assert Category.SECURITY  # keep import used
