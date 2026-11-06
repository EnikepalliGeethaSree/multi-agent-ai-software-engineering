"""File-size benchmark, classifier metrics and the before/after table."""

from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest

from marl_agents.config import Settings
from marl_agents.evaluation.benchmark_runtime import (
    CSV_FIELDS,
    BenchmarkInput,
    aggregate,
    categorize,
    evenly_spaced,
    load_previous,
    metrics,
    review_file,
    run_benchmark,
    run_settings,
    select_inputs,
    summary_md,
    write_outputs,
)
from marl_agents.evaluation.comparison.before_after import before_after, before_after_md
from marl_agents.evaluation.recorder import RunRecorder
from marl_agents.evaluation.runners.classifier_eval import (
    latest_static_run,
    majority_report,
    score_report,
    static_report,
)
from marl_agents.llm import MockLLMProvider
from marl_agents.llm.base import (
    GenerationConfig,
    LLMError,
    LLMResponse,
    Message,
    QuotaExhaustedError,
)


def write_lines(path: Path, n: int) -> None:
    body = "\n".join(f"x{i} = {i}" for i in range(n)) + "\n"
    path.write_text(body, encoding="utf-8")


@pytest.mark.parametrize(
    ("lines", "category"),
    [
        (1, "small"),
        (100, "small"),
        (101, "medium"),
        (1000, "medium"),
        (1001, "large"),
        (5000, "large"),
        (5001, None),
        (0, None),
    ],
)
def test_size_categories_have_the_requested_boundaries(lines: int, category: str | None) -> None:
    assert categorize(lines) == category


def test_evenly_spaced_is_a_fixed_rule() -> None:
    assert evenly_spaced(list(range(10)), 3) == [0, 4, 9]
    assert evenly_spaced([1, 2], 3) == [1, 2]
    assert evenly_spaced(list(range(5)), 1) == [2]


def test_inputs_are_bucketed_and_identified(tmp_path: Path) -> None:
    write_lines(tmp_path / "a.py", 50)
    write_lines(tmp_path / "b.py", 500)
    write_lines(tmp_path / "c.py", 2000)
    write_lines(tmp_path / "too_big.py", 6000)
    chosen = select_inputs(tmp_path, per_category=1)
    assert [(i.category, i.name) for i in chosen] == [
        ("small", "a.py"),
        ("medium", "b.py"),
        ("large", "c.py"),
    ]
    assert all(len(i.sha256) == 64 for i in chosen)


def row(status: str, total: float | None, category: str = "small", run_type: str = "cold"):  # type: ignore[no-untyped-def]
    return {
        "file_name": "a.py",
        "category": category,
        "run_type": run_type,
        "status": status,
        "total_sec": total,
        "input_tokens": None,
        "skipped_units": 1 if status == "partial" else 0,
    }


def test_statistics_use_complete_runs_only() -> None:
    rows = [row("complete", t) for t in (1.0, 2.0, 3.0, 4.0, 5.0)]
    rows += [row("failed", 99.0), row("skipped", None), row("partial", 50.0)]
    r = aggregate(rows, "cold", "small")
    assert (r["runs"], r["complete"], r["failed"], r["skipped"], r["partial"]) == (8, 5, 1, 1, 1)
    assert r["success_rate"] == pytest.approx(5 / 8)
    assert (r["mean_sec"], r["median_sec"], r["min_sec"], r["max_sec"]) == (3.0, 3.0, 1.0, 5.0)
    assert r["p95_sec"] == pytest.approx(4.8)
    assert r["mean_input_tokens"] is None  # unavailable, not zero
    assert r["skipped_chunks"] == 1


def test_a_category_with_no_complete_run_has_no_times() -> None:
    r = aggregate([row("failed", 3.0)], "cold", "small")
    assert r["mean_sec"] is None and r["success_rate"] == 0.0


def test_cold_and_warm_are_reported_separately() -> None:
    rows = [row("complete", 10.0, run_type="cold"), row("complete", 1.0, run_type="warm")]
    assert aggregate(rows, "cold", "small")["mean_sec"] == 10.0
    assert aggregate(rows, "warm", "small")["mean_sec"] == 1.0


def _inputs(tmp_path: Path) -> list[BenchmarkInput]:
    write_lines(tmp_path / "a.py", 30)
    write_lines(tmp_path / "b.py", 150)
    return select_inputs(tmp_path, per_category=1)


def run(
    settings: Settings, tmp_path: Path, llm: MockLLMProvider | None, mode: str, **kwargs
) -> tuple[list[dict], RunRecorder]:  # type: ignore[type-arg]
    settings.rag.embedding_model = "hashing"
    recorder = RunRecorder("runtime_test", settings, base_dir=tmp_path / "results")
    inputs = _inputs(tmp_path)
    rows = run_benchmark(
        settings, llm, inputs, mode=mode, rag=False, repeats=2, recorder=recorder,
        progress=lambda _m: None, **kwargs,
    )  # fmt: skip
    return rows, recorder


def test_benchmark_writes_csv_and_json(settings: Settings, tmp_path: Path) -> None:
    rows, recorder = run(settings, tmp_path, None, "static_only")
    assert len(rows) == 2 * 2 * 2  # files x rounds x (cold, warm)
    assert {r["status"] for r in rows} == {"complete"}
    m = metrics(rows, _inputs(tmp_path), mode="static_only", rag=False, repeats=2, llm=None,
                settings=settings)  # fmt: skip
    out = recorder.finish(m, summary_md(m))
    write_outputs(out, rows, m)
    with (out / "results.csv").open(encoding="utf-8") as fh:
        table = list(csv.DictReader(fh))
    assert len(table) == 8 and float(table[0]["total_sec"]) > 0
    assert table[0]["llm_inference_sec"] == ""  # not measured, so blank rather than 0
    saved = json.loads((out / "results.json").read_text(encoding="utf-8"))
    assert saved["metrics"]["benchmark"] == "runtime" and len(saved["runs"]) == 8
    assert "exclude LLM inference" in (out / "summary.md").read_text(encoding="utf-8")
    assert (out / "summary.csv").is_file()


def test_warm_run_reuses_the_llm_work_of_the_cold_run(settings: Settings, tmp_path: Path) -> None:
    llm = MockLLMProvider()
    rows, _ = run(settings, tmp_path, llm, "full")
    warm = [r for r in rows if r["run_type"] == "warm"]
    cold = [r for r in rows if r["run_type"] == "cold"]
    assert sum(r["llm_calls"] or 0 for r in warm) == 0
    assert sum(r["units_from_cache"] or 0 for r in warm) == sum(r["review_units"] for r in cold)


class Spent(MockLLMProvider):
    def generate(
        self, messages: list[Message], config: GenerationConfig | None = None
    ) -> LLMResponse:
        raise QuotaExhaustedError("quota reached")


def test_quota_stop_marks_later_runs_skipped_not_fast(settings: Settings, tmp_path: Path) -> None:
    rows, _ = run(settings, tmp_path, Spent(), "full")
    assert rows[0]["status"] == "partial"
    assert all(r["status"] == "skipped" for r in rows[1:])
    assert all(r.get("total_sec") is None for r in rows[1:])


def test_call_budget_stops_llm_runs(settings: Settings, tmp_path: Path) -> None:
    llm = MockLLMProvider()
    rows, _ = run(settings, tmp_path, llm, "full", max_llm_calls=1)
    assert {r["status"] for r in rows} == {"complete", "skipped"}
    assert len(llm.calls) == 1


def test_mock_runs_are_flagged_as_pipeline_checks(settings: Settings, tmp_path: Path) -> None:
    rows, _ = run(settings, tmp_path, MockLLMProvider(), "full")
    m = metrics(rows, _inputs(tmp_path), mode="full", rag=False, repeats=2, llm=MockLLMProvider(),
                settings=settings)  # fmt: skip
    assert m["pipeline_check_only"] is True and "Do not report" in summary_md(m)


def test_resume_keeps_only_measured_runs(tmp_path: Path) -> None:
    runs = [
        {
            "file_name": "a.py",
            "repeat": 1,
            "run_type": "cold",
            "status": "complete",
            "failed_units": 0,
        },
        {"file_name": "a.py", "repeat": 1, "run_type": "warm", "status": "skipped"},
        {
            "file_name": "b.py",
            "repeat": 1,
            "run_type": "cold",
            "status": "partial",
            "failed_units": 2,
        },
    ]
    (tmp_path / "results.json").write_text(json.dumps({"runs": runs}), encoding="utf-8")
    assert list(load_previous(tmp_path)) == [("a.py", 1, "cold")]


# ---- classifier metrics (values worked out by hand) --------------------------------------------


def test_classifier_metrics_match_hand_computed_values() -> None:
    labels = [1, 1, 1, 0, 0, 0]
    scores = [0.9, 0.8, 0.2, 0.7, 0.3, 0.1]
    r = score_report(labels, scores, 0.5)  # predicted: 1 1 0 1 0 0
    assert r["confusion_matrix"] == {"tp": 2, "fp": 1, "tn": 2, "fn": 1}
    assert r["accuracy"] == pytest.approx(4 / 6, abs=1e-4)
    assert r["precision"] == pytest.approx(2 / 3, abs=1e-4)
    assert r["recall"] == pytest.approx(2 / 3, abs=1e-4)
    assert r["f1"] == pytest.approx(2 / 3, abs=1e-4)
    assert r["false_positive_rate"] == pytest.approx(1 / 3, abs=1e-4)
    assert r["roc_auc"] == pytest.approx(7 / 9, abs=1e-4)  # 7 of 9 pos/neg pairs ranked correctly
    assert r["class_wise"]["no_comment"] == {
        "precision": pytest.approx(2 / 3, abs=1e-4),
        "recall": pytest.approx(2 / 3, abs=1e-4),
        "support": 3,
    }


def test_majority_baseline() -> None:
    assert majority_report([1, 0, 0, 0]) == {"n": 4, "accuracy": 0.75, "predicts": "no_comment"}


# ---- before / after ---------------------------------------------------------------------------


def saved(root: Path, name: str, provider: str, recall: float, fingerprint: str = "abc") -> None:
    d = root / name
    d.mkdir(parents=True)
    experiment = {
        "configuration": {"key": "static_llm_rag", "letter": "D", "label": "x", "static": True,
                          "llm": True, "rag": True, "mode": "full"},
        "llm": {"provider": provider, "model": "m"},
        "sample_fingerprint": fingerprint,
    }  # fmt: skip
    (d / "metrics.json").write_text(
        json.dumps({"detection": {"recall": recall, "defect_precision": 1.0}}), encoding="utf-8"
    )
    (d / "meta.json").write_text(json.dumps({"experiment": experiment}), encoding="utf-8")


def test_missing_runs_are_na_with_a_command(tmp_path: Path) -> None:
    table = before_after(tmp_path)
    assert all(r.improved is None for r in table.rows)
    assert "configs/gemini.yaml" in (table.rows[0].note or "")
    assert "N/A" in before_after_md(table)


def test_comparison_uses_the_saved_values(tmp_path: Path) -> None:
    saved(tmp_path, "20261001T000000Z_planted_full", "groq", 0.9)
    saved(tmp_path, "20261101T000000Z_planted_full", "gemini", 1.0)
    recall = next(r for r in before_after(tmp_path).rows if r.metric == "Recall")
    assert (recall.original, recall.improved, recall.note) == (0.9, 1.0, None)


def test_different_samples_are_not_compared(tmp_path: Path) -> None:
    saved(tmp_path, "20261001T000000Z_planted_full", "groq", 0.9, "one")
    saved(tmp_path, "20261101T000000Z_planted_full", "gemini", 1.0, "two")
    recall = next(r for r in before_after(tmp_path).rows if r.metric == "Recall")
    assert recall.improved is None and "not comparable" in (recall.note or "")


def static_predictions(root: Path) -> Path:
    run = root / "20261012T000000Z_codereviewer_cls_test_static_only_n4196"
    run.mkdir(parents=True)
    high = {"severity": "high", "confidence": 0.5, "rule": "S608"}
    cross_hunk = {"severity": "high", "confidence": 0.9, "rule": "F821"}
    rows = [
        {"sample_id": "a", "label": 1, "findings": [high]},
        {"sample_id": "b", "label": 0, "findings": [cross_hunk]},  # ignored: needs other hunks
        {"sample_id": "c", "label": 0, "findings": []},
        {"sample_id": "other", "label": 1, "findings": [high]},  # not in the sample set
        {"sample_id": "failed", "error": "patch"},
    ]
    (run / "predictions.jsonl").write_text(
        "\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8"
    )
    return run


def test_original_system_is_scored_from_saved_predictions_on_the_same_samples(
    tmp_path: Path,
) -> None:
    run = static_predictions(tmp_path)
    assert latest_static_run(tmp_path) == run
    r = static_report(run, {"a", "b", "c", "failed"})
    assert r is not None and r["n"] == 3
    assert r["confusion_matrix"] == {"tp": 1, "fp": 0, "tn": 2, "fn": 0}
    assert r["roc_auc"] == 1.0 and r["source_run"] == run.name


def test_no_overlap_gives_no_baseline(tmp_path: Path) -> None:
    assert static_report(static_predictions(tmp_path), {"nothing"}) is None


def test_classification_rows_compare_static_with_the_classifier(tmp_path: Path) -> None:
    d = tmp_path / "20261106T000000Z_classifier_cls_test_n3"
    d.mkdir()
    primary = {
        "n": 3,
        "f1": 0.7,
        "baselines": {"static_analysis": {"f1": 0.3, "source_run": "run-a"}},
    }
    (d / "metrics.json").write_text(json.dumps({"repo_disjoint": primary}), encoding="utf-8")
    (d / "meta.json").write_text("{}", encoding="utf-8")
    row = next(r for r in before_after(tmp_path).rows if r.metric == "F1-score")
    assert (row.original, row.improved, row.original_run, row.n) == (0.3, 0.7, "run-a", 3)


def test_classifier_run_saves_every_score_and_scores_each_change_once(
    settings: Settings, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from marl_agents.evaluation.datasets.codereviewer import CodeReviewerSample
    from marl_agents.evaluation.runners import classifier_eval as ce

    def sample(i: int, label: int, patch: str) -> CodeReviewerSample:
        return CodeReviewerSample.model_construct(
            sample_id=f"s{i}", task="cls", split="test", patch=patch, label=label
        )

    samples = [
        sample(0, 1, "@@ -1 +1 @@\n+a = 1"),
        sample(1, 0, "@@ -1 +1 @@\n+b = 2"),
        sample(2, 1, "@@ -1 +1 @@\n+c = 3"),
        sample(3, 0, "@@ -1 +1 @@\n+d = 4"),
        sample(4, 1, "@@ -1 +1 @@\n+a = 1"),  # same patch as s0
    ]
    calls: list[list[str]] = []

    class Fake:
        model_id = "fake"
        metadata = type("M", (), {"threshold": 0.5})()

        def __init__(self, _dir: Path) -> None:
            pass

        def score(self, texts: list[str]) -> list[float]:
            calls.append(texts)
            return [0.9 if "a = 1" in t or "c = 3" in t else 0.1 for t in texts]

    monkeypatch.setattr(ce, "load_codereviewer", lambda *a, **k: samples)
    monkeypatch.setattr(ce, "TransformersChangeClassifier", Fake)
    data = tmp_path / "data"
    data.mkdir()
    (data / "test_sample_ids.json").write_text(json.dumps(["s0", "s1", "s2"]), encoding="utf-8")
    models = tmp_path / "models" / "m"
    models.mkdir(parents=True)
    results = tmp_path / "results"

    run = ce.run_classifier_evaluation(settings, models, data, results)

    assert run.parent == results  # never into the real results folder
    assert len(calls) == 1 and len(calls[0]) == 4  # four distinct changes, one pass
    rows = [
        json.loads(ln)
        for ln in (run / "predictions.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert {r["sample_id"] for r in rows} == {"s0", "s1", "s2", "s3"}
    assert all(r["score"] in {0.9, 0.1} for r in rows)
    assert sum(r["repo_disjoint"] for r in rows) == 3
    metrics = json.loads((run / "metrics.json").read_text(encoding="utf-8"))
    assert metrics["repo_disjoint"]["n"] == 3
    assert metrics["repo_disjoint"]["f1"] == 1.0
    assert metrics["official_test"]["n"] == 4
    assert metrics["weights_sha256"] is None  # no weights file here, so none is claimed


def test_a_partial_run_says_why(settings: Settings, tmp_path: Path) -> None:
    class CutOff(MockLLMProvider):
        def generate(
            self, messages: list[Message], config: GenerationConfig | None = None
        ) -> LLMResponse:
            raise LLMError("reply was cut off at the output token limit")

    conf = run_settings(settings, "full", False, tmp_path / "cache", None)
    record, quota = review_file(conf, CutOff(), _inputs(tmp_path)[0], tmp_path / "out")
    assert (record.status, quota) == ("partial", False)
    assert "cut off" in (record.message or "")


def test_thinking_tokens_reach_the_csv() -> None:
    assert "thinking_tokens" in CSV_FIELDS


@pytest.mark.parametrize("config", ["configs/default.yaml", "configs/gemini.yaml"])
def test_the_output_limit_leaves_room_for_reasoning(config: str) -> None:
    import yaml

    from marl_agents.config import PROJECT_ROOT

    data = yaml.safe_load((PROJECT_ROOT / config).read_text(encoding="utf-8"))
    assert data["llm"]["max_tokens"] >= 16384
