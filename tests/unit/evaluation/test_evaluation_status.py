"""Audit rules of the Evaluation dashboard: honest labels, status from raw rows, runs left untouched."""

from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

from marl_agents.api.app import _headline
from marl_agents.evaluation.comparison import build_summary, summary_md
from marl_agents.evaluation.comparison.baselines import (
    retrieval_table,
    risk_table,
    runtime_counts,
    runtime_tables,
    usefulness_table,
)
from marl_agents.evaluation.comparison.common import provider_badge
from marl_agents.evaluation.comparison.detection import (
    answer_key_counts,
    codereviewer_tables,
    planted_table,
)
from marl_agents.evaluation.comparison.status import unfinished_runs
from marl_agents.evaluation.runs import load_runs
from tests.unit.evaluation.test_comparison import CFG, GROQ, cls_pred, detection, llm_cfg, save

GEMINI_CFG = {**CFG["D"], "llm": {**GROQ, "provider": "gemini", "model": "gemini-3.6-flash"}}
CSV_HEAD = (
    "category", "file_name", "repeat", "run_type", "status", "total_sec", "static_analysis_sec",
    "rag_retrieval_sec", "llm_inference_sec", "llm_quota_wait_sec", "input_tokens",
    "output_tokens", "thinking_tokens", "cache_hit_rate",
)  # fmt: skip


def runtime_run(
    root: Path, name: str, rows: list[dict[str, Any]], *, mode: str = "full", files: int = 1
) -> Path:
    inputs = [{"name": f"f{i}.py"} for i in range(files)]
    # The summary fields claim success, so a test can prove they are not what is believed.
    groups = [{"complete": 2, "partial": 0, "failed": 0, "skipped": 0, "runs": 2}]
    d = save(
        root, name,
        {"benchmark": "runtime", "mode": mode, "repeats": 2, "inputs": inputs, "results": groups},
        meta={"llm_provider": "gemini", "llm_model": "gemini-3.6-flash"} if mode == "full" else {},
        config=GEMINI_CFG,
    )  # fmt: skip
    with (d / "results.csv").open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, CSV_HEAD, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    return d


def row(status: str, repeat: int, run_type: str, category: str = "small", **kw: Any) -> Any:
    base = {"category": category, "file_name": "f0.py", "repeat": repeat, "run_type": run_type}
    return {**base, "status": status, **kw}


# ---- planted ------------------------------------------------------------------------------------


def test_correct_findings_and_issues_found_are_separate_columns(tmp_path: Path) -> None:
    save(tmp_path, "20260101T000000Z_planted_static_llm_rag", {"detection": detection(14, 0, 17)},
         meta={"llm_provider": "groq", "llm_model": "m"}, config=llm_cfg("D"))  # fmt: skip
    table = planted_table(load_runs(tmp_path))
    d = next(r for r in table.rows if r.status == "ok")
    assert (d.values["tp"], d.values["issues_found"], d.values["fn"]) == (14, 17, 0)
    assert d.values["recall"] == 1.0
    labels = {c.key: c.label for c in table.columns}
    assert labels["tp"] == "Correct" and labels["issues_found"] == "Found"
    assert labels["f1"] == "F1 (mixed basis)"
    assert "TP" not in labels.values()
    assert any("Why 14 correct findings" in n for n in table.notes)


def test_answer_key_explains_the_gap_between_14_and_17() -> None:
    assert answer_key_counts() == {
        "total": 17,
        "defect": 14,
        "other": 3,
        "static": 16,
        "semantic": 1,
    }


def test_planted_table_warns_that_a_perfect_score_is_not_real_world_accuracy(
    tmp_path: Path,
) -> None:
    table = planted_table(load_runs(tmp_path))
    assert "17 issues" in (table.warning or "") and "not evidence of 100%" in (table.warning or "")
    assert "Small benchmark (n = 17)" in table.badges


def test_a_recall_that_varies_between_complete_runs_is_reported(tmp_path: Path) -> None:
    for name, matched in (("20260101T000000Z", 17), ("20260102T000000Z", 16),
                          ("20260103T000000Z", 17)):  # fmt: skip
        save(tmp_path, f"{name}_planted_static_llm_rag", {"detection": detection(14, 0, matched)},
             meta={"llm_provider": "groq", "llm_model": "m"}, config=llm_cfg("D"))  # fmt: skip
    obs = planted_table(load_runs(tmp_path)).observations
    assert any("varies between complete runs" in o and "16/17" in o for o in obs)


# ---- CodeReviewer -------------------------------------------------------------------------------


def _paired(root: Path, task: str = "cls") -> None:
    hi = [{"severity": "high", "confidence": 0.9, "rule": "R", "lines": [1, 1]}]
    ids = ["s1", "s2", "s3", "s4"]
    tag = f"{task}_test"
    save(root, f"20260101T000000Z_codereviewer_{tag}_static_only_n4",
         {"task": task, "n_evaluated": 4, "n_failed": 0},
         meta={"sample_ids": ids, "split": "test"}, config=CFG["A"],
         predictions=[cls_pred(i, 1, hi) for i in ids])  # fmt: skip
    save(root, f"20260102T000000Z_codereviewer_{tag}_static_llm_n4",
         {"task": task, "n_evaluated": 2, "n_failed": 2, "failure_reasons": {"llm": 2}},
         meta={"sample_ids": ids, "split": "test", "llm_provider": "groq", "llm_model": "m"},
         config=llm_cfg("C"),
         predictions=[cls_pred("s1", 1, hi), cls_pred("s2", 0, [])])  # fmt: skip
    save(root, f"20260103T000000Z_codereviewer_{tag}_static_llm_rag_n4",
         {"task": task, "n_evaluated": 0, "n_failed": 4, "failure_reasons": {"llm": 4}},
         meta={"sample_ids": ids, "split": "test", "llm_provider": "groq", "llm_model": "m"},
         config=llm_cfg("D"), predictions=[])  # fmt: skip


def test_a_tiny_paired_set_is_preliminary_and_reports_no_roc_auc(tmp_path: Path) -> None:
    _paired(tmp_path)
    table = codereviewer_tables(load_runs(tmp_path), "cls")[0]
    assert "Preliminary" in table.badges
    assert "only 2 of 4 requested samples" in (table.warning or "")
    assert table.conditions["paired samples"] == "2 of 4 requested"
    for r in table.rows:
        if r.status == "ok":
            assert r.values["roc_auc"] is None and "too few" in r.na["roc_auc"]
            assert r.values["adj_roc_auc"] is None


def test_same_samples_is_not_claimed_when_a_configuration_has_none(tmp_path: Path) -> None:
    _paired(tmp_path)
    check = codereviewer_tables(load_runs(tmp_path), "cls")[0].fairness[0]
    assert check.ok is False
    assert "every configuration" not in check.detail
    assert "no scored samples for" in check.detail and "Static + LLM + RAG" in check.detail


def test_failed_runs_stay_visible(tmp_path: Path) -> None:
    _paired(tmp_path)
    table = codereviewer_tables(load_runs(tmp_path), "cls")[0]
    assert "C 2/4" in table.conditions["evaluated per configuration"]
    assert "D 0" in table.conditions["evaluated per configuration"]
    assert any("2 of 4 samples failed (llm: 2)" in n for n in table.notes)
    d = next(r for r in table.rows if r.label == "Static + LLM + RAG")
    assert d.status == "incomplete" and d.n_failed == 4


def test_the_full_split_is_never_presented_as_paired(tmp_path: Path) -> None:
    _paired(tmp_path)
    ids = [f"s{i}" for i in range(1, 7)]
    save(tmp_path, "20251231T000000Z_codereviewer_cls_test_static_only_n6",
         {"task": "cls", "n_evaluated": 6, "n_failed": 0},
         meta={"sample_ids": ids, "split": "test"}, config=CFG["A"],
         predictions=[cls_pred(i, 1, []) for i in ids])  # fmt: skip
    full = codereviewer_tables(load_runs(tmp_path), "cls")[1]
    assert "Not paired" in full.badges
    assert "do not compare" in full.about


def test_cls_commands_warn_about_the_classifier_test_set(tmp_path: Path) -> None:
    _paired(tmp_path)
    notes = codereviewer_tables(load_runs(tmp_path), "cls")[0].notes
    assert any("--split valid" in n and "held-out" in n for n in notes)


def _msg(root: Path) -> None:
    ids = [f"s{i}" for i in range(40)]
    pred = {"reference": "fix", "comment": "fix it", "label": 1}
    save(root, "20260101T000000Z_codereviewer_msg_test_static_only_n40",
         {"task": "msg", "n_evaluated": 40, "n_failed": 0},
         meta={"sample_ids": ids, "split": "test"}, config=CFG["A"],
         predictions=[{"sample_id": i, **pred} for i in ids])  # fmt: skip
    save(root, "20260102T000000Z_codereviewer_msg_test_full_n40",
         {"task": "msg", "n_evaluated": 36, "n_failed": 4, "failure_reasons": {"llm": 4}},
         meta={"sample_ids": ids, "split": "test", "llm_provider": "groq", "llm_model": "qwen"},
         config=llm_cfg("D"),
         predictions=[{"sample_id": i, **pred} for i in ids[:36]])  # fmt: skip


def test_comment_comparison_is_incomplete_and_makes_no_rag_claim(tmp_path: Path) -> None:
    _msg(tmp_path)
    table = codereviewer_tables(load_runs(tmp_path), "msg")[0]
    assert "Incomplete" in table.badges
    assert "Historical: Groq (qwen)" in table.badges
    warning = table.warning or ""
    assert "LLM Only, Static + LLM have no results" in warning
    assert "run separately" in warning
    assert "does not show that RAG improves" in warning
    assert table.conditions["paired samples"] == "36 of 40 requested"
    assert "B not run" in table.conditions["evaluated per configuration"]
    assert any("--configurations" in n and "--limit 40" in n for n in table.notes)
    assert any("cannot be judged here" in n for n in table.notes)
    assert not table.observations


# ---- retrieval, risk, usefulness ----------------------------------------------------------------


def test_retrieval_keeps_every_metric_and_states_what_it_measures(tmp_path: Path) -> None:
    metrics = {"recall@1": 0.1, "recall@5": 0.2, "recall@10": 0.3, "hit@10": 0.4, "mrr": 0.5,
               "ndcg@10": 0.6}  # fmt: skip
    save(tmp_path, "20260102T000000Z_retrieval_src", {
        "n_queries": 10, "n_chunks": 50, "random_baseline": metrics, "hashing": metrics})  # fmt: skip
    table = retrieval_table(load_runs(tmp_path))
    assert table.rows[0].label == "Random baseline"
    assert table.rows[1].values["ndcg_at_10"] == 0.6 and table.rows[1].values["hit_at_10"] == 0.4
    assert any("does not measure final review accuracy" in n for n in table.notes)


def _risk(root: Path, size_auc: float, model_auc: float) -> None:
    top = {"5%": 0.5, "10%": 0.5, "25%": 0.5}
    save(root, "20260102T000000Z_hunkrisk_cls_test_n10", {
        "n_evaluated": 10, "n_failed": 0, "base_rate": 0.5,
        "auc": {"size_baseline": {"auc": size_auc}, "hunk_risk": {"auc": model_auc}},
        "precision_at_top": {"size_baseline": top, "hunk_risk": top}})  # fmt: skip


def test_risk_table_says_plainly_when_size_wins(tmp_path: Path) -> None:
    _risk(tmp_path, 0.651, 0.644)
    table = risk_table(load_runs(tmp_path))
    assert "Baseline not beaten" in table.badges
    assert "Size-only ranking outperforms Risk model v2" in (table.warning or "")
    assert all("used once" not in n for n in table.notes)
    assert any("not changed after seeing test results" in n for n in table.notes)


def test_risk_table_gives_no_warning_when_size_does_not_win(tmp_path: Path) -> None:
    _risk(tmp_path, 0.60, 0.70)
    table = risk_table(load_runs(tmp_path))
    assert table.warning is None and "Baseline not beaten" not in table.badges


def test_usefulness_rows_show_their_own_counts(tmp_path: Path) -> None:
    part = lambda n: {"relevance": {"n": n, "mean": 4.0}, "informativeness": {"n": n, "mean": 4.0}}  # noqa: E731
    save(tmp_path, "20260102T000000Z_usefulness_x",
         {"agent": part(28), "human": part(36), "n_judged": 64})  # fmt: skip
    table = usefulness_table(load_runs(tmp_path))
    assert table is not None
    assert [r.n for r in table.rows] == [28, 36]


# ---- efficiency ---------------------------------------------------------------------------------


def test_completion_comes_from_raw_rows_not_the_summary(tmp_path: Path) -> None:
    rows = [row("complete", 1, "cold", total_sec=20.0), row("complete", 1, "warm", total_sec=0.1),
            row("partial", 2, "cold"), row("skipped", 2, "warm")]  # fmt: skip
    runtime_run(tmp_path, "20260102T000000Z_runtime_full_r2", rows)
    run = load_runs(tmp_path)[0]
    assert all(g["complete"] == 2 for g in run.metrics["results"])  # the summary looks fine
    c = runtime_counts(run)
    assert c is not None and not c["is_complete"]
    assert (c["complete"], c["partial"], c["skipped"], c["planned"]) == (2, 1, 1, 4)
    assert (c["rounds_reached"], c["rounds_complete"]) == (2, 1)
    table = runtime_tables([run])[0]
    assert "Incomplete" in table.badges
    assert "2 of 4 planned runs" in (table.warning or "")


def test_missing_rows_cannot_look_complete(tmp_path: Path) -> None:
    rows = [row("complete", 1, "cold"), row("complete", 1, "warm")]
    runtime_run(tmp_path, "20260102T000000Z_runtime_full_r2", rows)
    c = runtime_counts(load_runs(tmp_path)[0])
    assert c is not None and not c["is_complete"] and c["planned"] == 4


def test_times_use_complete_runs_and_unmeasured_values_stay_empty(tmp_path: Path) -> None:
    rows = [
        row("complete", 1, "cold", total_sec=20.0, input_tokens=100),
        row("partial", 2, "cold", total_sec=999.0, input_tokens=999),
        row("complete", 1, "warm", total_sec=0.1, input_tokens=""),
    ]
    runtime_run(tmp_path, "20260102T000000Z_runtime_full_r2", rows)
    by = {r.label: r for r in runtime_tables(load_runs(tmp_path))[0].rows}
    assert by["Small, cold"].values["total_sec"] == 20.0
    assert by["Small, cold"].values["input_tokens"] == 100.0
    assert by["Small, warm"].values["input_tokens"] is None
    assert "cache" in by["Small, warm"].na["input_tokens"]
    assert by["Large, cold"].values["total_sec"] is None
    assert by["Large, cold"].na["total_sec"] == "no complete run"


def test_static_benchmark_is_never_labelled_with_an_llm(tmp_path: Path) -> None:
    rows = [row("complete", k, t) for k in (1, 2) for t in ("cold", "warm")]
    runtime_run(tmp_path, "20260102T000000Z_runtime_static_only_r2", rows, mode="static_only")
    table = runtime_tables(load_runs(tmp_path))[0]
    assert table.badges == ["Complete", "No LLM"]
    assert all(c.key != "input_tokens" for c in table.columns)
    assert table.section.startswith("6b.")


def test_gemini_comes_before_static_and_historical_is_separate(tmp_path: Path) -> None:
    rows = [row("complete", 1, "cold"), row("complete", 1, "warm")]
    runtime_run(tmp_path, "20260101T000000Z_runtime_static_only_r2", rows, mode="static_only")
    runtime_run(tmp_path, "20260102T000000Z_runtime_full_r2", rows)
    sections = [t.section for t in build_summary(tmp_path).tables]
    assert sections.index("6a. Efficiency: Gemini") < sections.index(
        "6b. Efficiency: static analysis only"
    )
    assert "6c. Efficiency: historical timing (not Gemini)" in sections


def test_a_run_of_mock_rows_is_not_a_benchmark(tmp_path: Path) -> None:
    d = runtime_run(tmp_path, "20260102T000000Z_runtime_full_r2", [row("complete", 1, "cold")])
    m = json.loads((d / "metrics.json").read_text(encoding="utf-8"))
    (d / "metrics.json").write_text(
        json.dumps({**m, "pipeline_check_only": True}), encoding="utf-8"
    )
    assert runtime_tables(load_runs(tmp_path)) == []


def test_runs_table_headline_counts_what_finished() -> None:
    metrics = {"mode": "full", "repeats": 5, "inputs": [{}] * 9,
               "results": [{"complete": 3, "partial": 1, "failed": 0, "skipped": 11},
                           {"complete": 5, "partial": 2, "failed": 0, "skipped": 68}]}  # fmt: skip
    h = _headline("20261106T162014Z_runtime_full_r5", metrics, {})
    assert (h["complete"], h["partial"], h["failed"], h["skipped"]) == (8, 3, 0, 79)


def test_provider_badge_separates_eras(tmp_path: Path) -> None:
    save(tmp_path, "20260101T000000Z_planted_static_llm_rag", {"detection": detection(14, 0, 17)},
         meta={"llm_provider": "groq", "llm_model": "m"}, config=llm_cfg("D"))  # fmt: skip
    assert provider_badge(load_runs(tmp_path)) == "Historical: Groq (m)"
    runtime_run(tmp_path, "20260102T000000Z_runtime_full_r2", [row("complete", 1, "cold")])
    gemini = [r for r in load_runs(tmp_path) if r.kind == "runtime"]
    assert provider_badge(gemini) == "Gemini: gemini-3.6-flash"


# ---- overall status -----------------------------------------------------------------------------


def status_of(root: Path, name: str) -> Any:
    status = build_summary(root).status
    assert status is not None
    return next(i for i in status.items if i.name.startswith(name))


def test_status_groups_follow_the_saved_runs(tmp_path: Path) -> None:
    _paired(tmp_path)
    _msg(tmp_path)
    rows = [row("complete", 1, "cold")]
    runtime_run(tmp_path, "20260102T000000Z_runtime_full_r2", rows)
    assert status_of(tmp_path, "CodeReviewer classification, paired").status == "preliminary"
    assert status_of(tmp_path, "Review comment generation").status == "incomplete"
    item = status_of(tmp_path, "File-size benchmark, gemini-3.6-flash")
    assert item.status == "incomplete" and "1 of 4 planned runs" in item.detail
    assert "--per-category 1" in (item.command or "")


def test_a_finished_benchmark_moves_to_complete_by_itself(tmp_path: Path) -> None:
    rows = [row("complete", k, t) for k in (1, 2) for t in ("cold", "warm")]
    runtime_run(tmp_path, "20260102T000000Z_runtime_full_r2", rows)
    item = status_of(tmp_path, "File-size benchmark, gemini-3.6-flash")
    assert item.status == "complete" and item.command is None


def test_pending_work_lists_commands_and_never_the_classifier_test_set(tmp_path: Path) -> None:
    status = build_summary(tmp_path).status
    assert status is not None
    pending = [i for i in status.items if i.status == "pending"]
    assert {i.name for i in pending} == {
        "Planted issues on Gemini",
        "Comment generation on Gemini",
        "Classifier off, prioritize and gate",
    }
    assert all(i.command for i in pending)
    ablation = next(i for i in pending if i.name.startswith("Classifier off"))
    assert "classifier-ablation" in (ablation.command or "")
    assert "eval classifier --model-dir" not in " ".join(i.command or "" for i in pending)


def test_findings_only_use_numbers_that_exist(tmp_path: Path) -> None:
    status = build_summary(tmp_path).status
    assert status is not None and status.findings == []
    _risk(tmp_path, 0.651, 0.644)
    status = build_summary(tmp_path).status
    assert status is not None
    assert any("does not beat the size baseline" in f for f in status.findings)


def test_stopped_runs_are_listed_though_the_tables_cannot_show_them(tmp_path: Path) -> None:
    (tmp_path / "20260101T000000Z_timing_r2").mkdir()
    aborted = save(tmp_path, "20260102T000000Z_codereviewer_msg_test_full_n40", {"task": "msg"})
    (aborted / "ABORTED.txt").write_text("quota", encoding="utf-8")
    lines = unfinished_runs(tmp_path)
    assert any("timing_r2: stopped before metrics" in x for x in lines)
    assert any("aborted" in x for x in lines)
    assert unfinished_runs(tmp_path / "missing") == []


@pytest.mark.parametrize("phrase", ["Evaluation status", "Status: "])
def test_markdown_carries_the_status(tmp_path: Path, phrase: str) -> None:
    assert phrase in summary_md(build_summary(tmp_path))


def test_building_the_dashboard_changes_no_saved_file(tmp_path: Path) -> None:
    _paired(tmp_path)
    _msg(tmp_path)
    runtime_run(tmp_path, "20260105T000000Z_runtime_full_r2", [row("complete", 1, "cold")])

    def digests() -> dict[str, str]:
        return {
            str(p): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in tmp_path.rglob("*")
            if p.is_file()
        }

    before = digests()
    summary_md(build_summary(tmp_path))
    assert digests() == before


def test_a_comparison_that_reused_cached_replies_says_so(tmp_path: Path) -> None:
    from marl_agents.evaluation.comparison.detection import planted_table

    for name, cfg, reused in (("static_llm", "C", False), ("static_llm_rag", "D", True)):
        save(tmp_path, f"20260101T00000{1 if cfg == 'D' else 0}Z_planted_{name}",
             {"detection": detection(14, 0, 17),
              "experiment": {"configuration": {"key": name}, "llm": {"provider": "gemini", "model": "m"},
                             "llm_cache_reused": reused}},
             meta={"llm_provider": "gemini", "llm_model": "m"}, config=llm_cfg(cfg))  # fmt: skip
    check = next(
        f for f in planted_table(load_runs(tmp_path)).fairness if f.name == "Fresh LLM calls"
    )
    assert (
        check.ok is False
        and "Static + LLM + RAG" in check.detail
        and "times do not" in check.detail
    )


def test_pending_comment_comparison_uses_the_cache_flag(tmp_path: Path) -> None:
    status = build_summary(tmp_path).status
    assert status is not None
    item = next(i for i in status.items if i.name == "Comment generation on Gemini")
    assert "--reuse-llm-cache" in (item.command or "")
