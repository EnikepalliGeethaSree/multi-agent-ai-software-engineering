"""Evaluation framework: detection metrics, v1 baseline, timing runner, adapters and tables."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from marl_agents.config import Settings
from marl_agents.core.schemas import Finding
from marl_agents.evaluation.framework import (
    collect_records,
    results_table_md,
    summary_md,
    timing_table_md,
)
from marl_agents.evaluation.metrics import ExpectedIssue, detection_metrics
from marl_agents.evaluation.recorder import RunRecorder
from marl_agents.evaluation.runners import timing as tm
from marl_agents.evaluation.runners.risk_v1 import score_v1
from marl_agents.llm import MockLLMProvider
from tests.conftest import llm_json


def _f(i: int, file: str, line: int, category: str) -> Finding:
    return Finding(
        id=f"CR-{i}", file=file, start_line=line, end_line=line, category=category,  # type: ignore[arg-type]
        severity="high", title="t", description="d", confidence=0.8, sources=["ruff"],  # type: ignore[list-item]
    )  # fmt: skip


# ---- 1. detection --------------------------------------------------------------------------------


def test_detection_tp_fp_fn_f1_hand_computed() -> None:
    expected = [
        ExpectedIssue(id="P1", file="a.py", line=10, category="bug"),
        ExpectedIssue(id="P2", file="a.py", line=30, category="security"),
        ExpectedIssue(id="P3", file="b.py", line=5, category="bug"),
    ]
    findings = [
        _f(1, "a.py", 11, "bug"),  # TP (P1, within 2 lines)
        _f(2, "a.py", 30, "security"),  # TP (P2)
        _f(3, "b.py", 50, "bug"),  # FP (no planted issue near)
        _f(4, "b.py", 5, "documentation"),  # not a defect finding: ignored by precision
    ]
    m = detection_metrics(findings, expected)
    assert (m.tp, m.fp, m.fn) == (2, 1, 1)
    assert m.precision == pytest.approx(2 / 3) and m.recall == pytest.approx(2 / 3)
    assert m.f1 == pytest.approx(2 / 3)  # 2PR/(P+R) with P = R
    assert m.precision == m.defect_precision  # same definition as before, new name


def test_f1_zero_without_matches() -> None:
    m = detection_metrics(
        [_f(1, "z.py", 1, "bug")], [ExpectedIssue(id="P", file="a.py", line=1, category="bug")]
    )
    assert (m.tp, m.fp, m.fn, m.f1) == (0, 1, 1, 0.0)


# ---- 4. risk v1 baseline ---------------------------------------------------------------------------


def test_risk_v1_frozen_points() -> None:
    from marl_agents.agents.code_review.risk import HunkView

    view = HunkView("a.py", 10, 12, ["x = eval(s)", "try:", "    pass"], 0, "@@")
    # high finding inside (20) + sensitive eval (15) + error handling (5) = 40
    assert score_v1(view, [_f(1, "a.py", 10, "bug")], []) == 40
    big = HunkView("a.py", 1, 60, ["x = 1"] * 60, 0, "@@")
    assert score_v1(big, [], []) == 10  # >50 changed lines


# ---- 5. timing runner (mock LLM, no network) ----------------------------------------------------


@pytest.fixture
def tiny_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "tiny"
    repo.mkdir()
    (repo / "app.py").write_text(
        "def total(items):\n    return sum(i['price'] for i in items) / len(items)\n",
        encoding="utf-8",
    )
    return repo


def test_timing_runner_aggregates_and_rag_overhead(
    settings: Settings, tiny_repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(tm, "_vector_store", lambda: "memory")
    settings.review.type_check = False
    rec = RunRecorder("timing_test", settings, base_dir=tmp_path / "runs")
    m = tm.run_timing(
        settings, MockLLMProvider(default=llm_json()), rec,
        [tm.TimingInput("tiny", tiny_repo)], ["static_only", "llm_rag", "llm_no_rag"], repeats=2,
    )  # fmt: skip
    rec.finish(m, tm.timing_summary_md(m, "t"))
    cfgs = m["results"]["tiny"]["configs"]
    assert {c: cfgs[c]["complete_runs"] for c in cfgs} == {
        "static_only": 2,
        "llm_rag": 2,
        "llm_no_rag": 2,
    }
    assert cfgs["static_only"]["llm_inference_sec"]["median"] == 0.0
    assert cfgs["llm_rag"]["rag_sec"]["median"] > 0 and cfgs["llm_no_rag"]["rag_sec"]["median"] == 0
    assert cfgs["llm_rag"]["report_generation_sec"]["n"] == 2
    assert cfgs["llm_rag"]["conditions"]["llm_calls"] >= 1
    ov = m["results"]["tiny"]["rag_overhead"]
    expected = (
        (ov["median_active_sec_with_rag"] - ov["median_active_sec_without_rag"])
        / ov["median_active_sec_without_rag"]
        * 100
    )
    assert ov["overhead_pct"] == pytest.approx(expected, abs=0.1)
    assert ov["rag_direct_median_sec"] == cfgs["llm_rag"]["rag_sec"]["median"]
    assert ov["rag_direct_share_pct"] == pytest.approx(
        ov["rag_direct_median_sec"] / ov["median_active_sec_with_rag"] * 100, abs=0.1
    )
    assert cfgs["llm_rag"]["llm_retries"]["median"] == 0  # mock replies are valid JSON
    assert cfgs["llm_rag"]["llm_calls"]["median"] == cfgs["llm_rag"]["conditions"]["review_units"]
    assert len((rec.dir / "predictions.jsonl").read_text(encoding="utf-8").splitlines()) == 6
    assert m["conditions"]["concurrency"] == 1 and "cpu_count" in m["conditions"]["hardware"]


def test_incomplete_llm_runs_are_excluded(
    settings: Settings, tiny_repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(tm, "_vector_store", lambda: "memory")
    settings.review.type_check = False
    rec = RunRecorder("timing_fail", settings, base_dir=tmp_path / "runs")
    broken = MockLLMProvider(default="not json")  # every LLM unit fails
    m = tm.run_timing(
        settings, broken, rec, [tm.TimingInput("tiny", tiny_repo)], ["llm_rag", "llm_no_rag"], 1
    )
    cfgs = m["results"]["tiny"]["configs"]
    assert cfgs["llm_rag"]["complete_runs"] == 0 and cfgs["llm_rag"]["total_sec"]["n"] == 0
    assert m["results"]["tiny"]["rag_overhead"] is None  # never computed from partial runs


def test_llm_configs_need_a_provider(settings: Settings, tiny_repo: Path, tmp_path: Path) -> None:
    rec = RunRecorder("t", settings, base_dir=tmp_path / "runs")
    with pytest.raises(ValueError, match="need an LLM provider"):
        tm.run_timing(settings, None, rec, [tm.TimingInput("tiny", tiny_repo)], ["llm_rag"], 1)


# ---- adapters, collection, tables -----------------------------------------------------------------


def _run(root: Path, name: str, metrics: dict, meta: dict | None = None) -> None:  # type: ignore[type-arg]
    d = root / name
    d.mkdir(parents=True)
    (d / "metrics.json").write_text(json.dumps(metrics), encoding="utf-8")
    (d / "meta.json").write_text(json.dumps(meta or {}), encoding="utf-8")


def test_records_from_saved_runs_and_not_run_placeholders(tmp_path: Path) -> None:
    root = tmp_path / "results"
    # older planted layout (no tp/fp/f1): derived exactly from the stored counts
    _run(root, "20260101T000000Z_planted_static_only", {"detection": {
        "expected": 17, "matched": 16, "recall": 16 / 17,
        "defect_true_positives": 13, "defect_findings": 13, "defect_precision": 1.0}})  # fmt: skip
    _run(root, "20260102T000000Z_codereviewer_cls_test_static_only_n100", {
        "task": "cls", "n_evaluated": 100, "default": {"precision": 0.4}, "roc_auc": 0.45,
        "sensitivity_without_cross_hunk_rules": {"default": {"precision": 0.6}, "roc_auc": 0.55},
    })  # fmt: skip
    _run(root, "20260103T000000Z_codereviewer_msg_test_full_n40", {
        "task": "msg", "n_evaluated": 36, "n_failed": 4, "comment_coverage": 0.78,
        "text_metrics": {"title_fix": {"chrf": 13.6, "bleu4_smoothed": 2.1}},
    }, {"llm_model": "qwen", "limit": 40, "seed": 42})  # fmt: skip
    _run(root, "20260104T000000Z_retrieval_src", {
        "repo": "src", "n_queries": 277, "n_chunks": 500,
        "random_baseline": {"recall@10": 0.03}, "hashing": {"recall@10": 0.438}})  # fmt: skip
    _run(root, "20260105T000000Z_hunkrisk_cls_test_n10", {
        "n_evaluated": 10, "base_rate": 0.5, "random_baseline": {"precision_at_top": 0.5, "auc": 0.5},
        "precision_at_top": {"hunk_risk": {"10%": 0.7}, "size_baseline": {"10%": 0.6},
                             "risk_v1_baseline": {"10%": 0.4}},
        "auc": {"hunk_risk": {"auc": 0.62}, "size_baseline": {"auc": 0.6}, "risk_v1_baseline": {"auc": 0.43}},
    })  # fmt: skip
    _run(
        root, "20260106T000000Z_hunkrisk_cls_valid_n10", {"n_evaluated": 1}
    )  # calibration: ignored
    (root / "20260107T000000Z_codereviewer_msg_test_full_n40").mkdir()  # no metrics: skipped
    records = collect_records(root)
    by = {(r.component, r.benchmark, r.configuration): r for r in records}

    det = by[("detection", "Planted issues", "static only")]
    assert det.counts == {"tp": 13, "fp": 0, "fn": 1, "expected_issues": 17}
    assert det.quality_metrics["f1"] == pytest.approx(round(2 * 1 * (16 / 17) / (1 + 16 / 17), 3))
    cls = by[("codereviewer", "CodeReviewer cls (test, Python)", "static only")]
    assert (
        cls.quality_metrics["precision"] == 0.4
        and cls.quality_metrics["auc_cross_hunk_rules_excluded"] == 0.55
    )
    msg = by[("codereviewer", "CodeReviewer msg (test, Python)", "static + LLM (qwen)")]
    assert msg.quality_metrics == {"coverage": 0.78, "chrf": 13.6} and msg.n == 36
    assert any("n=40" in n for n in msg.notes)
    rag = by[("rag", "Call-graph retrieval (src)", "hashing embedder")]
    assert rag.quality_metrics["recall@10 (hashing)"] == 0.438 and rag.n == 277
    risk = next(r for r in records if r.component == "risk_ranking")
    assert risk.quality_metrics["precision@top10% risk v1 (hand-set)"] == 0.4
    assert risk.quality_metrics["precision@top10% random (expected)"] == 0.5

    missing = {(r.component, r.configuration) for r in records if r.status == "not_run"}
    assert ("detection", "static + LLM") in missing and (
        "efficiency",
        "static / LLM+RAG / LLM no RAG",
    ) in missing
    table = results_table_md(records)
    assert "**not run**" in table and "| 0.438 |" in table and "eval timing --repeats 3" in table
    assert "not run" in timing_table_md(records)
    assert "BLEU-4 (approved-deck metric, still computed): 2.1" in summary_md(records)


def test_efficiency_records_and_timing_table(tmp_path: Path) -> None:
    root = tmp_path / "results"
    cell = {"n": 3, "mean": 1.0, "median": 1.0, "min": 0.9, "max": 1.1}
    cfg = {
        "runs": 3, "complete_runs": 3, "conditions": {"files": 8}, "static_tools_sec": {},
        **{k: cell for k in tm.COMPONENTS}, "active_sec": cell,
    }  # fmt: skip
    _run(root, "20260108T000000Z_timing_r3", {
        "results": {"planted_repo": {"configs": {"static_only": cfg, "llm_rag": cfg},
                                     "rag_overhead": {"overhead_pct": 4.9}}},
        "conditions": {"provider": "groq"},
    })  # fmt: skip
    records = collect_records(root)
    eff = [r for r in records if r.component == "efficiency" and r.status == "ok"]
    assert {r.configuration for r in eff} == {"static_only", "llm_rag"}
    assert eff[0].timing["total_sec"] == 1.0 and eff[0].n == 3  # type: ignore[index]
    table = timing_table_md(records)
    assert "| Static analysis | 1.000 | 1.000 |" in table and "planted_repo" in table
    assert any("planted_repo: RAG latency overhead +4.9%" in n for r in eff for n in r.notes)
    assert "| Complete runs | 3 | 3 |" in table and "Active time" in table
