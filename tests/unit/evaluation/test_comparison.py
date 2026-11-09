"""Baseline comparison: metrics (hand-computed), N/A handling, pairing, repeats, compatibility."""

from __future__ import annotations

import json
import statistics
from pathlib import Path
from typing import Any

import pytest
import yaml

from marl_agents.evaluation.comparison import build_summary, summary_md, table_md
from marl_agents.evaluation.comparison.baselines import _active, planted_timing_table
from marl_agents.evaluation.comparison.common import compare, prf
from marl_agents.evaluation.comparison.detection import (
    cls_metrics,
    codereviewer_tables,
    msg_metrics,
    planted_table,
)
from marl_agents.evaluation.metrics import chrf, corpus_bleu_avg, rouge_l
from marl_agents.evaluation.metrics.efficiency import mean_sd, overhead_pct
from marl_agents.evaluation.runs import load_runs

CFG = {
    "A": {"review": {"mode": "static_only", "min_confidence": 0.3}, "rag": {"enabled": True}},
    "B": {"review": {"mode": "llm_only", "min_confidence": 0.3}, "rag": {"enabled": False}},
    "C": {"review": {"mode": "full", "min_confidence": 0.3}, "rag": {"enabled": False}},
    "D": {"review": {"mode": "full", "min_confidence": 0.3}, "rag": {"enabled": True}},
}
GROQ = {"provider": "groq", "model": "m", "temperature": 0.0}


def save(
    root: Path,
    name: str,
    metrics: dict[str, Any],
    meta: dict[str, Any] | None = None,
    config: dict[str, Any] | None = None,
    predictions: list[dict[str, Any]] | None = None,
) -> Path:
    d = root / name
    d.mkdir(parents=True)
    (d / "metrics.json").write_text(json.dumps(metrics), encoding="utf-8")
    (d / "meta.json").write_text(json.dumps(meta or {}), encoding="utf-8")
    if config is not None:
        (d / "config.yaml").write_text(yaml.safe_dump(config), encoding="utf-8")
    if predictions is not None:
        (d / "predictions.jsonl").write_text(
            "".join(json.dumps(p) + "\n" for p in predictions), encoding="utf-8"
        )
    return d


def detection(tp: int, fp: int, matched: int, expected: int = 17) -> dict[str, Any]:
    return {
        "expected": expected, "matched": matched, "tp": tp, "fp": fp, "fn": expected - matched,
        "recall": matched / expected, "recall_static": 1.0, "recall_llm": 0.0,
        "negative_file_false_positives": 0, "mean_line_error": 0.5,
    }  # fmt: skip


def llm_cfg(letter: str) -> dict[str, Any]:
    return {**CFG[letter], "llm": GROQ}


# ---- metric arithmetic ---------------------------------------------------------------------------


def test_precision_recall_f1_hand_computed() -> None:
    p, r, f1 = prf(tp=3, fp=1, fn=2)
    assert p == pytest.approx(0.75) and r == pytest.approx(0.6)
    assert f1 == pytest.approx(2 * 0.75 * 0.6 / 1.35)


def test_division_by_zero_is_na_not_a_number() -> None:
    assert prf(0, 0, 4) == (None, 0.0, None)  # no predictions: precision undefined
    assert prf(0, 3, 0) == (0.0, None, None)  # no positives: recall undefined
    assert prf(0, 2, 2) == (0.0, 0.0, 0.0)  # both defined and zero: F1 = 0


def test_cls_metrics_raw_and_adjusted_hand_computed() -> None:
    preds = [
        {"sample_id": "s1", "label": 1,
         "findings": [{"severity": "info", "confidence": 0.9, "rule": "AST-MISSING-DOCSTRING"}]},
        {"sample_id": "s2", "label": 0,
         "findings": [{"severity": "low", "confidence": 0.9, "rule": "F401"}]},
    ]  # fmt: skip
    m = cls_metrics(preds)
    # raw: s1 not flagged (info) = FN, s2 flagged = FP -> P = 0/1, R = 0/1, F1 = 0
    assert (m["precision"], m["recall"], m["f1"]) == (0.0, 0.0, 0.0)
    assert m["roc_auc"] == 0.0  # positive scored 0.18 < negative 0.38
    # adjusted: F401 dropped -> nothing flagged -> precision undefined (N/A), not 0 or 1
    assert m["adj_precision"] is None and m["adj_recall"] == 0.0 and m["adj_f1"] is None
    assert m["adj_roc_auc"] == 1.0  # positive 0.18 > negative 0.0


def test_msg_metrics_match_the_runner_functions() -> None:
    preds = [
        {"reference": "add a null check here", "comment": "Add a null check. Guard x."},
        {"reference": "rename this variable", "comment": ""},
    ]
    m = msg_metrics(preds)
    refs, hyps = [p["reference"] for p in preds], [p["comment"] for p in preds]
    assert m["bleu4"] == pytest.approx(corpus_bleu_avg(refs, hyps))
    assert m["rouge_l"] == pytest.approx(100 * (rouge_l(refs[0], hyps[0]) + 0) / 2)
    assert m["chrf"] == pytest.approx(100 * (chrf(refs[0], hyps[0]) + 0) / 2)
    assert m["coverage"] == 0.5
    assert 0 <= m["bleu4"] <= 100 and 0 <= m["chrf"] <= 100  # documented 0-100 scale


def test_rag_overhead_formula() -> None:
    assert overhead_pct(12.0, 10.0) == pytest.approx(20.0)
    assert overhead_pct(9.0, 10.0) == pytest.approx(-10.0)
    assert overhead_pct(None, 10.0) is None and overhead_pct(5.0, 0.0) is None


def test_mean_sd() -> None:
    assert mean_sd([1.0, 3.0]) == (2.0, statistics.stdev([1.0, 3.0]), 2)
    assert mean_sd([2.0, None]) == (2.0, None, 1)
    assert mean_sd([]) == (None, None, 0)


def test_observation_wording_is_neutral() -> None:
    assert compare("recall", "A", 0.941, "C", 0.941) == "A and C have the same recall (0.941)."
    assert compare("ROC-AUC", "risk", 0.644, "size", 0.651) == (
        "Size has a higher ROC-AUC than risk (0.651 vs 0.644)."
    )
    assert compare("F1", "A", None, "B", 0.5) is None


# ---- planted table ---------------------------------------------------------------------------------


def test_planted_table_missing_configurations_are_na_with_commands(tmp_path: Path) -> None:
    save(tmp_path, "20260101T000000Z_planted_static_only",
         {"detection": detection(13, 0, 16)}, config=CFG["A"])  # fmt: skip
    table = planted_table(load_runs(tmp_path))
    by = {r.configuration.key: r for r in table.rows if r.configuration}
    a = by["static_only"]
    assert a.status == "ok" and a.values["precision"] == 1.0
    assert a.values["recall"] == pytest.approx(16 / 17)
    assert a.values["roc_auc"] is None and "positives only" in a.na["roc_auc"]
    for key in ("llm_only", "static_llm", "static_llm_rag"):
        assert by[key].status == "not_run" and by[key].how_to_run
        assert f"--configuration {key}" in by[key].how_to_run  # type: ignore[operator]
    md = table_md(table)
    assert "| LLM Only | ✗ | ✓ | ✗ | N/A |" in md and "To run:" in md


def test_planted_precision_is_na_without_defect_findings(tmp_path: Path) -> None:
    save(tmp_path, "20260101T000000Z_planted_llm_only", {"detection": detection(0, 0, 0)},
         meta={"llm_provider": "groq"}, config=llm_cfg("B"))  # fmt: skip
    row = next(r for r in planted_table(load_runs(tmp_path)).rows if r.status == "ok")
    assert row.values["precision"] is None and row.values["f1"] is None
    assert row.values["recall"] == 0.0


def test_repeated_runs_report_mean_and_sd(tmp_path: Path) -> None:
    for i, matched in enumerate((16, 15)):
        exp = {"configuration": {"key": "static_only"}, "group_id": "g1", "repeat": i + 1}
        save(tmp_path, f"2026010{i + 1}T000000Z_planted_static_only",
             {"detection": detection(13, 0, matched)}, meta={"experiment": exp},
             config=CFG["A"])  # fmt: skip
    row = next(r for r in planted_table(load_runs(tmp_path)).rows if r.status == "ok")
    assert row.n_runs == 2
    assert row.values["recall"] == pytest.approx(15.5 / 17)
    assert row.sd["recall"] == pytest.approx(statistics.stdev([16 / 17, 15 / 17]))
    assert "±" in table_md(planted_table(load_runs(tmp_path)))


def test_mock_and_incomplete_runs_never_become_results(tmp_path: Path) -> None:
    save(tmp_path, "20260101T000000Z_planted_static_llm", {"detection": detection(13, 0, 17)},
         meta={"llm_provider": "mock"}, config={**llm_cfg("C"), "llm": {"provider": "mock"}})  # fmt: skip
    save(tmp_path, "20260102T000000Z_planted_static_llm_rag",
         {"detection": detection(13, 0, 17), "complete": False},
         meta={"llm_provider": "groq"}, config=llm_cfg("D"))  # fmt: skip
    by = {r.configuration.key: r for r in planted_table(load_runs(tmp_path)).rows}  # type: ignore[union-attr]
    assert by["static_llm"].status == "not_run"  # mock: a pipeline test, not a result
    assert by["static_llm_rag"].status == "incomplete" and by["static_llm_rag"].values == {}


# ---- CodeReviewer pairing ----------------------------------------------------------------------------


def cls_pred(sid: str, label: int, findings: list[dict[str, Any]]) -> dict[str, Any]:
    return {"sample_id": sid, "label": label, "findings": findings}


def test_codereviewer_rows_are_paired_on_common_samples(tmp_path: Path) -> None:
    hi = [{"severity": "high", "confidence": 0.8, "rule": None}]
    lo = [{"severity": "low", "confidence": 0.9, "rule": "F401"}]
    save(tmp_path, "20260101T000000Z_codereviewer_cls_test_static_only_n4",
         {"task": "cls", "n_evaluated": 4, "n_failed": 0},
         meta={"sample_ids": ["s1", "s2", "s3", "s4"], "split": "test"}, config=CFG["A"],
         predictions=[cls_pred("s1", 1, []), cls_pred("s2", 0, lo), cls_pred("s3", 1, hi),
                      cls_pred("s4", 0, [])])  # fmt: skip
    # The LLM run requested s1-s3 and failed on s3 (D22): s3 must leave every row.
    save(tmp_path, "20260102T000000Z_codereviewer_cls_test_static_llm_rag_n3",
         {"task": "cls", "n_evaluated": 2, "n_failed": 1},
         meta={"sample_ids": ["s1", "s2", "s3"], "split": "test", "llm_provider": "groq",
               "llm_model": "m"}, config=llm_cfg("D"),
         predictions=[cls_pred("s1", 1, hi), cls_pred("s2", 0, [])])  # fmt: skip
    table = codereviewer_tables(load_runs(tmp_path), "cls")[0]
    by = {r.configuration.key: r for r in table.rows if r.configuration}
    a, d = by["static_only"], by["static_llm_rag"]
    assert a.n == d.n == 2 and d.n_failed == 1 and a.n_failed == 0
    # A on {s1, s2}: s1 missed (FN), s2 flagged by F401 (FP)
    assert (a.values["precision"], a.values["recall"]) == (0.0, 0.0)
    assert a.values["adj_precision"] is None  # F401 removed: nothing flagged
    # D on {s1, s2}: s1 flagged (TP), s2 clean (TN)
    assert (d.values["precision"], d.values["recall"]) == (1.0, 1.0)
    assert d.values["roc_auc"] is None and "too few" in d.na["roc_auc"]  # n = 2: not reported
    assert any("restricted to the 3 reference samples" in n for n in a.notes)
    assert table.fairness[0].ok is False  # B and C have no results, so this is not "every"
    assert "2 of 3 requested samples" in table.fairness[0].detail
    assert "LLM Only, Static + LLM" in table.fairness[0].detail
    assert by["llm_only"].status == "not_run" and "--configuration llm_only" in (
        by["llm_only"].how_to_run or ""
    )
    full = codereviewer_tables(load_runs(tmp_path), "cls")[1]
    assert full.id == "codereviewer_cls_full" and full.rows[0].n == 4


# ---- efficiency ------------------------------------------------------------------------------------


def test_active_time_needs_one_llm_worker() -> None:
    timing = {"total_sec": 100.0, "llm_rate_limit_wait_sec": 80.0}
    assert _active({"timing": {**timing, "concurrency": 1}}) == 20.0
    assert _active({"timing": {**timing, "concurrency": 2}}) is None  # waits summed over workers


def test_planted_rag_overhead_only_for_runs_made_together(tmp_path: Path) -> None:
    t = {"total_sec": 30.0, "static_analysis_sec": 5.0, "rag_index_sec": 0.2,
         "rag_retrieval_sec": 0.1, "llm_inference_sec": 20.0, "validation_sec": 0.01,
         "other_sec": 4.69, "llm_rate_limit_wait_sec": 10.0, "concurrency": 1}  # fmt: skip
    for i, (letter, key, total) in enumerate(
        (("C", "static_llm", 30.0), ("D", "static_llm_rag", 32.0))
    ):
        exp = {"configuration": {"key": key}, "group_id": "g", "llm": GROQ}
        save(tmp_path, f"2026010{i + 1}T000000Z_planted_{key}",
             {"detection": detection(13, 0, 16), "timing": {**t, "total_sec": total}},
             meta={"experiment": exp}, config=llm_cfg(letter))  # fmt: skip
    table = planted_timing_table(load_runs(tmp_path))
    # active: 20 s without RAG, 22 s with RAG -> +10.0%
    assert any("RAG overhead +10.0%" in o for o in table.observations)


def test_planted_rag_overhead_na_for_separate_runs(tmp_path: Path) -> None:
    t = {"total_sec": 30.0, "concurrency": 1, "llm_rate_limit_wait_sec": 0.0}
    for i, (letter, key) in enumerate((("C", "static_llm"), ("D", "static_llm_rag"))):
        save(tmp_path, f"2026010{i + 1}T000000Z_planted_{key}",
             {"detection": detection(13, 0, 16), "timing": t},
             meta={"llm_provider": "groq"}, config=llm_cfg(letter))  # fmt: skip
    table = planted_timing_table(load_runs(tmp_path))
    assert not table.observations and any("RAG overhead: N/A" in n for n in table.notes)


# ---- compatibility with runs saved before the ablation framework --------------------------------


def test_old_runs_are_classified_from_config_yaml(tmp_path: Path) -> None:
    # Old static-only runs stored rag.enabled: true; effective RAG is off.
    save(tmp_path, "20260101T000000Z_planted_static_only", {"detection": detection(13, 0, 16)},
         meta={"llm_provider": "mock", "llm_model": None}, config=CFG["A"])  # fmt: skip
    save(tmp_path, "20260102T000000Z_planted_full", {"detection": detection(13, 0, 17)},
         meta={"llm_provider": "groq", "llm_model": "m"}, config=llm_cfg("D"))  # fmt: skip
    save(
        tmp_path,
        "20260103T000000Z_planted_full_norag",
        {"detection": detection(12, 1, 16)},
        meta={"llm_provider": "groq", "llm_model": "m"},
    )  # no config.yaml: tag says no RAG
    save(tmp_path, "20260104T000000Z_planted_full", {"detection": detection(1, 0, 1)})  # unknown
    runs = {r.name: r for r in load_runs(tmp_path)}
    assert runs["20260101T000000Z_planted_static_only"].configuration.key == "static_only"  # type: ignore[union-attr]
    assert runs["20260102T000000Z_planted_full"].configuration.key == "static_llm_rag"  # type: ignore[union-attr]
    assert runs["20260103T000000Z_planted_full_norag"].configuration.key == "static_llm"  # type: ignore[union-attr]
    assert runs["20260104T000000Z_planted_full"].configuration is None  # RAG state not recorded
    by = {r.configuration.key: r for r in planted_table(list(runs.values())).rows}  # type: ignore[union-attr]
    assert by["static_llm_rag"].run_ids == ["20260102T000000Z_planted_full"]
    assert by["static_llm"].values["fp"] == 1


def test_summary_from_an_empty_results_dir_is_all_na(tmp_path: Path) -> None:
    s = build_summary(tmp_path / "nothing")
    assert s.master is not None and all(r.status == "not_run" for r in s.master.rows)
    md = summary_md(s)
    assert "N/A" in md and "Metric definitions" in md and "not system-level" in md


def test_summary_from_saved_runs(tmp_path: Path) -> None:
    save(tmp_path, "20260101T000000Z_planted_static_only", {"detection": detection(13, 0, 16)},
         config=CFG["A"])  # fmt: skip
    save(tmp_path, "20260102T000000Z_retrieval_src", {
        "repo": "src", "n_queries": 10, "n_chunks": 50, "experiment": {"x": 1},
        "random_baseline": {"recall@10": 0.02, "mrr": 0.03},
        "hashing": {"recall@10": 0.4, "mrr": 0.3}})  # fmt: skip
    save(tmp_path, "20260103T000000Z_hunkrisk_cls_test_n10", {
        "n_evaluated": 10, "base_rate": 0.5, "random_baseline": {"precision_at_top": 0.5, "auc": 0.5},
        "auc": {"hunk_risk": {"auc": 0.64}, "size_baseline": {"auc": 0.65}},
        "precision_at_top": {"hunk_risk": {"10%": 0.73}, "size_baseline": {"10%": 0.79}}})  # fmt: skip
    s = build_summary(tmp_path)
    tables = {t.id: t for t in s.tables}
    rag = {r.label: r.values for r in tables["retrieval"].rows}
    assert rag["Random baseline"]["recall_at_10"] == 0.02  # metadata block is not a method
    assert rag["RAG (hashing embedder)"]["mrr"] == 0.3 and len(rag) == 2
    risk = tables["risk"]
    # the baseline wins on this run and the summary says so
    assert "Size only has a higher ROC-AUC than Risk model v2 (0.650 vs 0.640)." in (
        risk.observations
    )
    assert s.master.rows[0].values["planted_recall"] == pytest.approx(16 / 17)  # type: ignore[union-attr]


def test_a_run_where_every_sample_failed_is_shown_as_incomplete(tmp_path: Path) -> None:
    save(tmp_path, "20260101T000000Z_codereviewer_cls_test_static_only_n2",
         {"task": "cls", "n_evaluated": 2, "n_failed": 0},
         meta={"sample_ids": ["s1", "s2"], "split": "test"}, config=CFG["A"],
         predictions=[cls_pred("s1", 1, []), cls_pred("s2", 0, [])])  # fmt: skip
    save(tmp_path, "20260102T000000Z_codereviewer_cls_test_static_llm_rag_n2",
         {"task": "cls", "n_evaluated": 0, "n_failed": 2, "failure_reasons": {"llm": 2}},
         meta={"sample_ids": ["s1", "s2"], "split": "test", "llm_provider": "groq"},
         config=llm_cfg("D"), predictions=[])  # fmt: skip
    rows = {r.configuration.key: r for r in codereviewer_tables(load_runs(tmp_path), "cls")[0].rows}  # type: ignore[union-attr]
    d = rows["static_llm_rag"]
    assert d.status == "incomplete" and d.n == 0 and d.n_failed == 2
    assert "every sample failed" in d.na["*"] and "llm: 2" in d.na["*"]
    assert rows["static_only"].status == "ok" and rows["static_only"].n == 2


def test_master_table_withholds_tiny_paired_samples(tmp_path: Path) -> None:
    save(tmp_path, "20260101T000000Z_codereviewer_cls_test_static_only_n2",
         {"task": "cls", "n_evaluated": 2}, meta={"sample_ids": ["s1", "s2"], "split": "test"},
         config=CFG["A"], predictions=[cls_pred("s1", 1, []), cls_pred("s2", 0, [])])  # fmt: skip
    master = build_summary(tmp_path).master
    assert master is not None
    a = next(r for r in master.rows if r.configuration and r.configuration.key == "static_only")
    assert a.values["cls_f1"] is None and "too small for a headline (n = 2 < 30)" in a.na["cls_f1"]


def test_group_runs_are_preferred_over_newer_runs_outside_the_group(tmp_path: Path) -> None:
    preds = [cls_pred("s1", 1, []), cls_pred("s2", 0, [])]
    exp = {"group_id": "g", "configuration": {"key": "static_only"}}
    save(tmp_path, "20260101T000000Z_codereviewer_cls_test_static_only_n2",
         {"task": "cls", "n_evaluated": 2}, meta={"sample_ids": ["s1", "s2"], "split": "test",
                                                  "experiment": exp},
         config=CFG["A"], predictions=preds)  # fmt: skip
    save(tmp_path, "20260102T000000Z_codereviewer_cls_test_static_llm_n2",
         {"task": "cls", "n_evaluated": 2},
         meta={"sample_ids": ["s1", "s2"], "split": "test", "llm_provider": "groq",
               "experiment": {**exp, "configuration": {"key": "static_llm"}, "llm": GROQ}},
         config=llm_cfg("C"), predictions=preds)  # fmt: skip
    save(tmp_path, "20260103T000000Z_codereviewer_cls_test_static_only_n3",  # newer, wider
         {"task": "cls", "n_evaluated": 3}, meta={"sample_ids": ["s1", "s2", "s3"], "split": "test"},
         config=CFG["A"], predictions=[*preds, cls_pred("s3", 1, [])])  # fmt: skip
    table = codereviewer_tables(load_runs(tmp_path), "cls")[0]
    a = next(r for r in table.rows if r.configuration and r.configuration.key == "static_only")
    assert a.run_ids == ["20260101T000000Z_codereviewer_cls_test_static_only_n2"]
    assert next(f for f in table.fairness if f.name.startswith("Run together")).ok is True


# ---- one ablation group per table; local models apart -------------------------------------------


def _planted_group(root: Path, stamp_day: int, group: str, provider: str, model: str) -> None:
    llm = {"provider": provider, "model": model, "temperature": 0.0}
    for i, (key, letter) in enumerate((("static_only", "A"), ("llm_only", "B"),
                                       ("static_llm", "C"), ("static_llm_rag", "D"))):  # fmt: skip
        is_llm = key != "static_only"
        exp = {"configuration": {"key": key, "llm": is_llm}, "group_id": group,
               **({"llm": llm} if is_llm else {})}  # fmt: skip
        meta = {
            "experiment": exp,
            **({"llm_provider": provider, "llm_model": model} if is_llm else {}),
        }
        save(root, f"202601{stamp_day:02d}T00000{i}Z_planted_{key}",
             {"detection": detection(13, 0, 16 if is_llm else 15)}, meta=meta,
             config={**CFG[letter], **({"llm": llm} if is_llm else {})})  # fmt: skip


def test_a_local_model_ablation_never_replaces_the_gemini_rows(tmp_path: Path) -> None:
    _planted_group(tmp_path, 1, "abl-gemini", "gemini", "gemini-3.6-flash")
    _planted_group(tmp_path, 2, "abl-ollama", "ollama", "qwen2.5-coder:7b")  # newer
    summary = build_summary(tmp_path)
    official = next(t for t in summary.tables if t.id == "planted")
    assert all(r.run_ids and r.run_ids[0].startswith("20260101") for r in official.rows)
    assert "Gemini: gemini-3.6-flash" in official.badges
    assert not any(f.ok is False for f in official.fairness)  # None = not recorded in the fixture
    local = next(t for t in summary.tables if t.id == "planted_local")
    assert all(r.run_ids and r.run_ids[0].startswith("20260102") for r in local.rows)
    assert "Local: Ollama (qwen2.5-coder:7b)" in local.badges
    assert "not comparable" in (local.warning or "")
    assert any("local-model run(s)" in n for n in summary.master.notes)


def test_a_later_stand_alone_static_run_does_not_split_the_group(tmp_path: Path) -> None:
    _planted_group(tmp_path, 1, "abl-gemini", "gemini", "gemini-3.6-flash")
    save(tmp_path, "20260105T000000Z_planted_static_only", {"detection": detection(13, 0, 15)},
         meta={"experiment": {"configuration": {"key": "static_only"}}}, config=CFG["A"])  # fmt: skip
    table = planted_table(load_runs(tmp_path))
    static = next(r for r in table.rows if r.configuration and r.configuration.key == "static_only")
    assert static.run_ids == ["20260101T000000Z_planted_static_only"]
    assert next(f for f in table.fairness if f.name.startswith("Run together")).ok is True
