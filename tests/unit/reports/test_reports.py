import json
from pathlib import Path

from marl_agents.core.schemas import Finding, ReviewResult, RunMetadata
from marl_agents.reports import summarize, to_json, to_markdown, write_reports


def _result(findings: list[Finding], lines: int = 1000) -> ReviewResult:
    return ReviewResult(
        agent="code_review",
        findings=findings,
        metadata=RunMetadata(agent="code_review", provider="mock", model="m", rag_enabled=True),
        files_analyzed=3,
        lines_analyzed=lines,
        stats={"mode": "full", "llm_rejection_rate": 0.25},
    )


def _f(i: int, severity: str, category: str, file: str = "a.py") -> Finding:
    return Finding(
        id=f"CR-{i:03d}",
        file=file,
        start_line=i,
        end_line=i + 1,
        category=category,  # type: ignore[arg-type]
        severity=severity,
        title=f"Issue <{i}> | pipe",
        description="desc & more",  # type: ignore[arg-type]
        evidence=[f"x = {i}"],
        recommendation="fix it",
        test_recommendation="test it",
        confidence=0.7,
        sources=["ruff", "llm"],  # type: ignore[list-item]
    )


FINDINGS = [
    _f(1, "critical", "security"),
    _f(2, "high", "bug", "b.py"),
    _f(3, "low", "quality"),
    _f(4, "info", "testing"),
]


def test_summary_counts_and_issue_density() -> None:
    s = summarize(_result(FINDINGS, lines=1000))
    assert s.by_severity == {"critical": 1, "high": 1, "medium": 0, "low": 1, "info": 1}
    assert s.security_issues == 1 and s.potential_bugs == 1 and s.testing_gaps == 1
    # D = 10 + 5 + 0.5 = 15.5 per KLOC -> 100 * exp(-15.5 / 50)
    assert s.weighted_density_per_kloc == 15.5
    assert not hasattr(s, "quality_index")  # removed: a heuristic score, not an evaluation
    assert s.top_files[0] == ("a.py", 10.5)


def test_clean_result_has_zero_density() -> None:
    assert summarize(_result([])).weighted_density_per_kloc == 0.0


def test_json_and_markdown_render_everything() -> None:
    result = _result(FINDINGS)
    payload = json.loads(to_json(result))
    assert payload["summary"]["total_findings"] == 4
    assert payload["result"]["findings"][0]["id"] == "CR-001"
    md = to_markdown(result)
    for needle in (
        "CR-001",
        "[CRITICAL]",
        "`a.py:1-2`",
        "**Fix:** fix it",
        "**Test:** test it",
        "Issue <1> \\| pipe",
        "LLM rejection rate 25.0%",
    ):
        assert needle in md
    assert "No findings" in to_markdown(_result([]))


def test_write_reports_including_pdf(tmp_path: Path) -> None:
    written = write_reports(_result(FINDINGS), tmp_path / "out")
    assert set(written) == {"json", "md", "pdf"}
    pdf = written["pdf"].read_bytes()
    assert pdf.startswith(b"%PDF") and len(pdf) > 2000


def test_markdown_flags_a_partial_llm_review() -> None:
    result = _result(FINDINGS)
    assert "Partial review" not in to_markdown(result)
    result.stats.update(units_failed=2, units_total=5)
    result.errors.append("[a.py:1-9] LLM review failed: quota")
    assert "the LLM could not review 2 of 5 part(s)" in to_markdown(result)
    result.stats["mode"] = "static_only"
    assert "Partial review" not in to_markdown(result)
