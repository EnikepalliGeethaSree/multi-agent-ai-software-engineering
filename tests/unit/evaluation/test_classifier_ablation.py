"""The three-mode classifier comparison, on tiny samples with the mock LLM."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from marl_agents.agents.code_review import CodeReviewAgent
from marl_agents.config import Settings
from marl_agents.evaluation.benchmark_runtime import cache_hit_rate
from marl_agents.evaluation.comparison.before_after import before_after
from marl_agents.evaluation.datasets.codereviewer import CodeReviewerSample
from marl_agents.evaluation.recorder import RunRecorder
from marl_agents.evaluation.runners import classifier_ablation as ca
from marl_agents.llm import MockLLMProvider
from marl_agents.llm.classifier import FixedScoreClassifier

OLD = "def f(a):\n    return a\n"


def patch(line: str) -> str:
    return f"@@ -1,2 +1,2 @@\n def f(a):\n-    return a\n+    {line}\n"


def sample(i: int, line: str, label: int = 1, proj: str = "dev-project") -> CodeReviewerSample:
    return CodeReviewerSample(
        sample_id=f"s{i}",
        task="cls",
        split="valid",
        proj=proj,
        patch=patch(line),
        oldf=OLD,
        label=label,
    )


def agents(settings: Settings, llm: MockLLMProvider) -> dict[str, CodeReviewAgent]:
    scorer = FixedScoreClassifier(lambda text: 0.9 if "risky" in text else 0.1)
    built = {}
    for mode in ca.MODES:
        s = ca.mode_settings(settings, mode, Path("unused"))
        built[mode] = CodeReviewAgent(
            llm,
            settings=s,
            progress=lambda _m: None,
            classifier=None if mode == "disabled" else scorer,
        )
    return built


def run(settings: Settings, tmp_path: Path, samples: list[Any], **kw: Any) -> list[dict[str, Any]]:
    recorder = RunRecorder("t", settings, base_dir=tmp_path)
    rows = ca.run_ablation(
        agents(settings, MockLLMProvider()), samples, recorder, progress=lambda _m: None, **kw
    )
    recorder.finish({}, "")
    return rows


def finding(rule: str | None, severity: str, line: int, sources: list[str]) -> dict[str, Any]:
    return {
        "rule": rule,
        "severity": severity,
        "category": "bug",
        "lines": [line, line],
        "sources": sources,
        "title": "t",
    }


def row(sample_id: str, mode: str, findings: list[Any], label: int = 1, skipped: int = 0) -> Any:
    return {
        "sample_id": sample_id,
        "mode": mode,
        "label": label,
        "status": "complete",
        "units_skipped": skipped,
        "llm_calls": 1,
        "findings_count": len(findings),
        "findings": findings,
    }


def test_every_mode_reviews_the_same_samples_and_only_gate_skips(
    settings: Settings, tmp_path: Path
) -> None:
    rows = run(settings, tmp_path, [sample(1, "return a + 1  # risky"), sample(2, "return a + 2")])
    assert sorted((r["sample_id"], r["mode"]) for r in rows) == sorted(
        (s, m) for s in ("s1", "s2") for m in ca.MODES
    )
    skipped = {(r["sample_id"], r["mode"]): r["units_skipped"] for r in rows}
    assert skipped[("s2", "gate")] == 1
    assert skipped[("s1", "gate")] == 0
    assert skipped[("s2", "prioritize")] == 0
    assert skipped[("s2", "disabled")] == 0
    calls = {(r["sample_id"], r["mode"]): r["llm_calls"] for r in rows}
    assert calls[("s2", "gate")] < calls[("s2", "disabled")]


def test_mode_order_rotates_so_no_mode_always_goes_first(
    settings: Settings, tmp_path: Path
) -> None:
    samples = [sample(i, f"return a + {i}") for i in range(3)]
    rows = run(settings, tmp_path, samples)
    assert [rows[i]["mode"] for i in (0, 3, 6)] == list(ca.MODES)


def test_the_budget_stops_between_samples_so_each_one_is_paired(
    settings: Settings, tmp_path: Path
) -> None:
    rows = run(
        settings,
        tmp_path,
        [sample(1, "return a + 1  # risky"), sample(2, "return a + 2 # risky")],
        max_llm_calls=1,
    )
    assert all(r["status"] == "complete" for r in rows if r["sample_id"] == "s1")
    assert all(r["status"] == "skipped" for r in rows if r["sample_id"] == "s2")
    assert ca.compare(rows)["paired_samples"] == 1


def test_resume_reuses_measured_rows_and_retries_the_rest(
    settings: Settings, tmp_path: Path
) -> None:
    first = run(
        settings,
        tmp_path,
        [sample(1, "return a + 1 # risky"), sample(2, "return a + 2 # risky")],
        max_llm_calls=1,
    )
    run_dir = next(tmp_path.glob("*_t"))
    done = ca.load_previous(run_dir)
    assert len(done) == 3 and len(first) == 6
    rows = run(
        settings,
        tmp_path,
        [sample(1, "return a + 1 # risky"), sample(2, "return a + 2 # risky")],
        done=done,
    )
    assert all(r["status"] == "complete" for r in rows)
    assert ca.compare(rows)["paired_samples"] == 2


def test_comparison_matches_hand_computed_values() -> None:
    static_high = finding("S1", "high", 5, ["ast"])
    llm_high = finding(None, "high", 20, ["llm"])
    llm_medium = finding(None, "medium", 30, ["llm"])
    llm_low = finding(None, "low", 40, ["llm"])
    base = [static_high, llm_high, llm_medium, llm_low]
    rows = [
        row("a", "disabled", base),
        row("a", "prioritize", base),
        row("a", "gate", [static_high, llm_low], skipped=1),
        row("b", "disabled", [llm_medium], label=0),
        row("b", "prioritize", [llm_medium], label=0),
        row("b", "gate", [llm_medium], label=0),
    ]
    gate = ca.compare(rows)["modes"]["gate"]
    assert gate["baseline_findings"] == 5
    assert gate["findings_retained"] == 3  # lost: llm_high and llm_medium in sample a
    assert gate["useful_baseline"] == 3  # static_high, llm_high, llm_medium; b has no comment
    assert gate["useful_retained"] == 1
    assert gate["important_baseline"] == 2
    assert gate["important_missed"] == 1
    assert gate["important_missed_detail"][0]["sample_id"] == "a"
    assert gate["static_high_lost_in_skipped_units"] == 0
    assert ca.compare(rows)["modes"]["prioritize"]["findings_retained"] == 5


def test_a_static_high_finding_lost_in_a_skipped_unit_is_counted() -> None:
    static_high = finding("S1", "critical", 5, ["ast"])
    rows = [
        row("a", "disabled", [static_high]),
        row("a", "prioritize", [static_high]),
        row("a", "gate", [], skipped=1),
    ]
    assert ca.compare(rows)["modes"]["gate"]["static_high_lost_in_skipped_units"] == 1


def test_a_sample_incomplete_in_any_mode_is_not_compared() -> None:
    rows = [
        row("a", "disabled", []),
        row("a", "prioritize", []),
        {**row("a", "gate", []), "status": "failed"},
    ]
    result = ca.compare(rows)
    assert result["paired_samples"] == 0
    assert result["status_counts"]["gate"] == {"failed": 1}


def test_a_match_needs_the_same_rule_or_a_nearby_line() -> None:
    a = finding(None, "high", 10, ["llm"])
    assert ca.missing_from([a], [finding(None, "low", 12, ["llm"])]) == []
    assert ca.missing_from([a], [finding(None, "high", 20, ["llm"])]) == [a]
    ruled = finding("R1", "high", 10, ["ast"])
    assert ca.missing_from([ruled], [finding("R2", "high", 10, ["ast"])]) == [ruled]


def test_one_finding_cannot_match_two_baseline_findings() -> None:
    a = finding(None, "high", 10, ["llm"])
    assert len(ca.missing_from([a, dict(a)], [a])) == 1


def test_modes_differ_only_in_the_classifier(settings: Settings) -> None:
    built = {m: ca.mode_settings(settings, m, Path("model")) for m in ca.MODES}
    dumps = [s.model_dump(exclude={"classifier": {"enabled", "mode"}}) for s in built.values()]
    assert dumps[0] == dumps[1] == dumps[2]
    assert built["disabled"].classifier.enabled is False
    assert built["prioritize"].classifier.mode == "prioritize"
    assert built["gate"].classifier.mode == "gate"
    assert built["gate"].review.unit_cache is False  # calls and time must be real


def test_samples_come_from_dev_only_and_the_test_split_is_never_loaded(
    settings: Settings, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    keep = sample(1, "return a + 1")
    copy = sample(2, "return a + 1")
    other_project = sample(3, "return a + 3", proj="test-project")
    not_in_dev = sample(4, "return a + 4")
    loaded: list[tuple[Any, ...]] = []

    def load(task: str, split: str, **_kw: Any) -> list[CodeReviewerSample]:
        loaded.append((task, split))
        return [keep, copy, other_project, not_in_dev]

    monkeypatch.setattr(ca, "load_codereviewer", load)
    (tmp_path / "manifest.json").write_text(
        json.dumps({"dev_projects": ["dev-project"]}), encoding="utf-8"
    )
    with (tmp_path / "dev.jsonl").open("w", encoding="utf-8") as fh:
        for s in (keep, other_project):
            fh.write(json.dumps({"text": s.patch.strip(), "label": 1}) + "\n")
    chosen = ca.dev_samples(settings, tmp_path, 10)
    assert [s.sample_id for s in chosen] == ["s1"]
    assert loaded == [("cls", "valid")]


def test_the_comparison_table_never_points_at_the_test_split(tmp_path: Path) -> None:
    rows = before_after(tmp_path).rows
    hints = [r.note for r in rows if "LLM work per sample" in r.benchmark]
    assert hints
    assert all("classifier-ablation" in h and "--task msg" not in h for h in hints)


def test_summary_marks_missing_values_and_states_the_limits() -> None:
    rows = [row("a", m, []) for m in ca.MODES]
    metrics = {"provider": "mock", "model": "m", "seed": 42, **ca.compare(rows)}
    md = ca.summary_md(metrics)
    assert "not an independent test" in md
    assert "| Input tokens | - | - | - |" in md


def test_outputs_are_written_as_csv_and_json(tmp_path: Path) -> None:
    rows = [row("a", "gate", [finding(None, "high", 1, ["llm"])])]
    ca.write_outputs(tmp_path, rows)
    assert "units_skipped" in (tmp_path / "results.csv").read_text(encoding="utf-8")
    saved = json.loads((tmp_path / "results.json").read_text(encoding="utf-8"))
    assert saved[0]["findings"][0]["severity"] == "high"


@pytest.mark.parametrize(
    ("units", "cached", "rate"),
    [(4, 1, 0.25), (4, 4, 1.0), (4, 0, 0.0), (0, 0, None), (None, None, None), (4, None, None)],
)
def test_cache_hit_rate(units: int | None, cached: int | None, rate: float | None) -> None:
    assert cache_hit_rate({"review_units": units, "units_from_cache": cached}) == rate
