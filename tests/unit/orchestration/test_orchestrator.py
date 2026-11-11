"""Part 5: Result Aggregator rules and the LangGraph orchestrator, with the mock LLM only."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from marl_agents.core.schemas import Category, Finding, FindingSource, Severity
from marl_agents.orchestration.aggregator import aggregate, same_issue


def f(fid: str, file: str = "a.py", start: int = 1, end: int = 2, cat: Category = Category.BUG,
      sev: Severity = Severity.MEDIUM, conf: float = 0.5, ev: str = "x") -> Finding:  # fmt: skip
    return Finding(id=fid, file=file, start_line=start, end_line=end, category=cat, severity=sev,
                   title=f"t-{fid}", description="d", evidence=[ev], confidence=conf,
                   sources=[FindingSource.AST])  # fmt: skip


def test_same_issue_needs_file_overlap_and_category() -> None:
    base = f("a", start=10, end=12)
    assert same_issue(base, f("b", start=12, end=15))
    assert not same_issue(base, f("c", start=13, end=15))  # no overlap
    assert not same_issue(base, f("d", file="b.py", start=10, end=12))
    assert not same_issue(base, f("e", start=10, end=12, cat=Category.SECURITY))


def test_merge_keeps_higher_severity_and_confidence_and_records_agents() -> None:
    cr = [f("CR-001", sev=Severity.MEDIUM, conf=0.9, ev="code a"),
          f("CR-002", start=40, end=41, cat=Category.QUALITY)]  # fmt: skip
    bd = [f("BD-001", sev=Severity.HIGH, conf=0.6, ev="code b"),
          f("BD-002", start=70, end=70)]  # fmt: skip
    agg = aggregate({"code_review": cr, "bug_detection": bd})
    s = agg.summary
    assert (s.total, s.shared, s.merged) == (3, 1, 1)
    assert s.unique == {"code_review": 1, "bug_detection": 1}
    assert s.findings_in == {"code_review": 2, "bug_detection": 2}
    shared = next(x for x in agg.findings if len(x.raised_by) == 2)
    assert shared.raised_by == ["bug_detection", "code_review"]
    assert shared.finding.severity is Severity.HIGH and shared.finding.confidence == 0.9
    assert shared.finding.title == "t-BD-001"  # the more severe finding leads
    assert shared.finding.evidence == ["code b", "code a"]  # evidence of both kept
    assert set(shared.merged_ids) == {"CR-001", "BD-001"} and "CR-001" in shared.finding.related
    assert [x.finding.id for x in agg.findings] == ["AG-001", "AG-002", "AG-003"]


def _repo(tmp_path: Path) -> Path:
    root = tmp_path / "proj"
    (root / "app").mkdir(parents=True)
    (root / "app" / "calc.py").write_text(
        "def ratio(values):\n    try:\n        return sum(values) / len(values)\n"
        "    except:\n        return None\n",
        encoding="utf-8",
    )
    return root


def test_graph_runs_both_agents_in_parallel_and_aggregates(settings, tmp_path) -> None:  # type: ignore[no-untyped-def]
    pytest.importorskip("langgraph")
    from marl_agents.agents.bug_detection import BugDetectionAgent
    from marl_agents.agents.code_review import CodeReviewAgent
    from marl_agents.core.schemas import AgentRequest
    from marl_agents.llm import MockLLMProvider
    from marl_agents.orchestration.graph import run_orchestrated

    settings.review.mode = "full"
    llm = MockLLMProvider()  # replies with no LLM findings: only static findings are merged
    request = AgentRequest(repo_path=str(_repo(tmp_path)))
    cr, bd = CodeReviewAgent(llm, settings=settings), BugDetectionAgent(llm, settings=settings)
    alone_cr, alone_bd = cr.run(request), bd.run(request)
    result = run_orchestrated(cr, bd, request)
    agg = result.stats["aggregation"]
    assert result.agent == "orchestrator" and result.findings
    assert agg["findings_in"] == {"code_review": len(alone_cr.findings),
                                  "bug_detection": len(alone_bd.findings)}  # fmt: skip
    assert agg["total"] == len(result.findings)
    assert (
        agg["total"]
        == agg["unique"]["code_review"] + agg["unique"]["bug_detection"] + agg["shared"]
    )
    assert all(any(n.startswith("raised by:") for n in x.notes) for x in result.findings)
    assert set(result.stats["raised_by"]) == {x.id for x in result.findings}
    assert result.stats["review_status"] == "complete"
    assert len(llm.calls) > 0  # both agents really ran through the (mock) LLM path


def _result(folder: Path) -> dict:  # type: ignore[type-arg]
    """The review result inside the JSON report (the folder also holds other JSON files)."""
    for path in folder.glob("*.json"):
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict) and "result" in data:
            return dict(data["result"])
    raise AssertionError(f"no JSON report in {folder}")


def test_review_orchestrated_cli_and_single_agent_path(tmp_path: Path, capsys) -> None:  # type: ignore[no-untyped-def]
    pytest.importorskip("langgraph")
    from marl_agents.cli import main

    repo = _repo(tmp_path)
    out = tmp_path / "out"
    args = ["review", str(repo), "--mode", "static_only", "--formats", "json", "--out", str(out),
            "--store", "memory"]  # fmt: skip
    assert main([*args, "--orchestrated"]) == 0
    printed = capsys.readouterr().out
    assert "orchestrated: code review" in printed and "after aggregation" in printed
    report = _result(out)
    assert report["agent"] == "orchestrator" and "aggregation" in report["stats"]
    single = tmp_path / "single"
    assert main(["review", str(repo), "--mode", "static_only", "--formats", "json", "--out",
                 str(single), "--store", "memory"]) == 0  # fmt: skip
    plain = _result(single)
    assert plain["agent"] == "code_review"  # the single-agent path is unchanged


def test_concurrent_writers_of_one_cache_entry_do_not_collide(tmp_path: Path) -> None:
    from concurrent.futures import ThreadPoolExecutor

    from marl_agents.core.atomic import write_atomic

    target = tmp_path / "entry.json"
    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(lambda _: write_atomic(target, b'{"same": true}'), range(64)))
    assert target.read_bytes() == b'{"same": true}'
    assert not list(tmp_path.glob("*.tmp"))  # no temporary file left behind
