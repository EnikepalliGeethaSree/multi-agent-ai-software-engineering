"""Experiment configurations A-D: each genuinely switches its components on/off (mock LLM)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from marl_agents.config import Settings
from marl_agents.core.schemas import Category
from marl_agents.evaluation.configurations import (
    CONFIGURATIONS,
    LLM_RAG,
    apply_configuration,
    classify,
    classify_config_dict,
    sample_fingerprint,
)
from marl_agents.evaluation.recorder import RunRecorder
from marl_agents.evaluation.runners import timing as tm
from marl_agents.evaluation.runners.ablation import planted_once, run_ablation
from marl_agents.llm import MockLLMProvider
from tests.conftest import PLANTED, PLANTED_EXPECTED, llm_json


def recording_llm() -> MockLLMProvider:
    return MockLLMProvider(default=llm_json())


def prompts(llm: MockLLMProvider) -> list[str]:
    """Every prompt the mock provider was sent (it records its calls)."""
    return ["\n".join(m.content for m in call) for call in llm.calls]


def _saved(folder: Path) -> tuple[dict, dict]:  # type: ignore[type-arg]
    meta = json.loads((folder / "meta.json").read_text(encoding="utf-8"))
    metrics = json.loads((folder / "metrics.json").read_text(encoding="utf-8"))
    return meta, metrics


def _run(settings: Settings, key: str, tmp_path: Path, llm: MockLLMProvider | None = None):  # type: ignore[no-untyped-def]
    s = apply_configuration(settings, key)
    folder = planted_once(
        s, llm, results_dir=tmp_path / "results", repo=PLANTED, expected=PLANTED_EXPECTED
    )
    return _saved(folder)


def test_static_only_runs_no_llm_and_no_rag(settings: Settings, tmp_path: Path) -> None:
    llm = recording_llm()
    meta, metrics = _run(settings, "static_only", tmp_path, llm)
    p, t = metrics["pipeline"], metrics["timing"]
    assert (p["static_enabled"], p["llm_enabled"], p["rag_enabled"]) == (True, False, False)
    assert t["llm_calls"] == 0 and t["rag_queries"] == 0 and t["static_analysis_sec"] > 0
    assert prompts(llm) == []  # the provider is never called
    exp = meta["experiment"]
    assert exp["configuration"]["key"] == "static_only" and exp["llm"] is None
    assert exp["rag"] is None and meta["llm_model"] is None


def test_llm_only_runs_no_static_analysis_and_no_rag(settings: Settings, tmp_path: Path) -> None:
    llm = recording_llm()
    meta, metrics = _run(settings, "llm_only", tmp_path, llm)
    p, t = metrics["pipeline"], metrics["timing"]
    assert (p["static_enabled"], p["llm_enabled"], p["rag_enabled"]) == (False, True, False)
    assert t["static_analysis_sec"] == 0 and t["static_tools_sec"] == {}
    assert t["llm_calls"] > 0 and t["rag_queries"] == 0 and "rag_index" not in p
    assert all("## Static analysis findings" not in x for x in prompts(llm))
    assert all("[similar]" not in x and "[guideline]" not in x for x in prompts(llm))
    assert meta["experiment"]["static_analyzers"] == []


def test_static_llm_runs_without_rag(settings: Settings, tmp_path: Path) -> None:
    llm = recording_llm()
    meta, metrics = _run(settings, "static_llm", tmp_path, llm)
    p, t = metrics["pipeline"], metrics["timing"]
    assert (p["static_enabled"], p["llm_enabled"], p["rag_enabled"]) == (True, True, False)
    assert t["static_analysis_sec"] > 0 and t["llm_calls"] > 0 and t["rag_queries"] == 0
    assert any("## Static analysis findings" in x for x in prompts(llm))  # LLM triages static
    assert all("[similar]" not in x and "[guideline]" not in x for x in prompts(llm))
    assert meta["experiment"]["rag"] is None


def test_static_llm_rag_genuinely_retrieves(settings: Settings, tmp_path: Path) -> None:
    llm = recording_llm()
    meta, metrics = _run(settings, "static_llm_rag", tmp_path, llm)
    p, t = metrics["pipeline"], metrics["timing"]
    assert (p["static_enabled"], p["llm_enabled"], p["rag_enabled"]) == (True, True, True)
    assert t["rag_queries"] > 0 and p["rag_index"]["chunks"] > 0
    assert any("[similar]" in x or "[guideline]" in x for x in prompts(llm))
    assert meta["experiment"]["rag"]["top_k"] == settings.rag.top_k


def test_metadata_and_timing_are_persisted(settings: Settings, tmp_path: Path) -> None:
    meta, metrics = _run(settings, "static_llm_rag", tmp_path, MockLLMProvider(default=llm_json()))
    exp = meta["experiment"]
    assert metrics["experiment"] == exp  # stored alongside the metrics too
    for key in ("benchmark", "sample_count", "sample_fingerprint", "n_failed",
                "confidence_threshold", "evaluation_rules", "prompt_versions", "timestamp"):  # fmt: skip
        assert key in exp, key
    assert exp["llm"] == {
        "provider": "mock", "model": settings.llm.model, "temperature": 0.0,
        "seed": settings.llm.seed, "max_tokens": settings.llm.max_tokens,
    }  # fmt: skip
    assert exp["sample_count"] == 17 and exp["evaluation_rules"]["line_tolerance"] == 2
    assert meta["git_commit"] and metrics["complete"] is True
    for key in ("total_sec", "static_analysis_sec", "llm_inference_sec", "validation_sec"):
        assert metrics["timing"][key] >= 0  # the breakdown is saved with the run


def test_failed_llm_units_mark_planted_run_incomplete(settings: Settings, tmp_path: Path) -> None:
    broken = MockLLMProvider(default="not json")
    meta, metrics = _run(settings, "static_llm", tmp_path, broken)
    assert metrics["complete"] is False and metrics["llm_units_failed"] > 0
    assert meta["errors"] > 0 and meta["experiment"]["n_failed"] > 0


def test_classification_and_apply() -> None:
    assert classify("static_only", True).key == "static_only"  # static-only never retrieves
    assert classify("llm_only", False).key == "llm_only"
    assert classify("llm_only", True) == LLM_RAG  # not silently relabelled as B
    assert classify("full", False).key == "static_llm"
    assert classify("full", True).key == "static_llm_rag"
    assert (
        classify_config_dict({"review": {"mode": "full"}, "rag": {"enabled": False}})
        == (CONFIGURATIONS["static_llm"])
    )
    assert classify_config_dict({}) is None


def test_apply_configuration_changes_only_the_variables_under_test(settings: Settings) -> None:
    for key, c in CONFIGURATIONS.items():
        s = apply_configuration(settings, key)
        assert (s.review.mode, s.rag.enabled) == (c.mode, c.rag)
        assert s.llm == settings.llm and s.review.min_confidence == settings.review.min_confidence
        assert s.rag.top_k == settings.rag.top_k
    assert settings.review.mode == "full"  # the base settings are not mutated
    with pytest.raises(ValueError, match="unknown configuration"):
        apply_configuration(settings, "everything")


def test_sample_fingerprint_is_order_independent() -> None:
    assert sample_fingerprint(["b", "a"]) == sample_fingerprint(["a", "b", "a"])
    assert sample_fingerprint(["a"]) != sample_fingerprint(["a", "c"])


def test_recorder_never_overwrites_a_run(settings: Settings, tmp_path: Path) -> None:
    a = RunRecorder("same", settings, base_dir=tmp_path)
    b = RunRecorder("same", settings, base_dir=tmp_path)
    assert a.dir != b.dir and a.dir.exists() and b.dir.exists()


def test_ablation_runs_every_configuration_on_one_input(settings: Settings, tmp_path: Path) -> None:
    folder, m = run_ablation(
        "planted", settings, MockLLMProvider(default=llm_json()),
        ["static_only", "llm_only", "static_llm", "static_llm_rag"], repeats=2,
        results_dir=tmp_path,
    )  # fmt: skip
    assert {k: len(v) for k, v in m["runs"].items()} == dict.fromkeys(CONFIGURATIONS, 2)
    groups = set()
    for names in m["runs"].values():
        for name in names:
            meta, _ = _saved(tmp_path / name)
            groups.add(meta["experiment"]["group_id"])
            assert meta["experiment"]["repeats"] == 2
            assert (tmp_path / name / "config.yaml").is_file()
    assert groups == {m["group_id"]}
    assert (folder / "summary.md").is_file() and m["tables"]


def test_timing_benchmark_includes_llm_only(
    settings: Settings, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(tm, "_vector_store", lambda: "memory")
    repo = tmp_path / "tiny"
    repo.mkdir()
    (repo / "app.py").write_text("def f(xs):\n    return sum(xs) / len(xs)\n", encoding="utf-8")
    rec = RunRecorder("timing_b", settings, base_dir=tmp_path / "runs")
    m = tm.run_timing(
        settings, MockLLMProvider(default=llm_json()), rec, [tm.TimingInput("tiny", repo)],
        ["static_only", "llm_only"], repeats=1,
    )  # fmt: skip
    b = m["results"]["tiny"]["configs"]["llm_only"]
    assert b["configuration"]["key"] == "llm_only"
    assert b["static_analysis_sec"]["median"] == 0 and b["rag_sec"]["median"] == 0
    assert b["llm_inference_sec"]["n"] == 1 and b["conditions"]["llm_calls"] >= 1


def test_category_enum_unchanged() -> None:
    """The planted answer key's categories still parse (labels are not modified)."""
    spec = json.loads(PLANTED_EXPECTED.read_text(encoding="utf-8"))
    assert len(spec["issues"]) == 17
    assert all(Category(i["category"]) for i in spec["issues"])
    assert sum(1 for i in spec["issues"] if i["detectable_by"] == "llm") == 1


@pytest.mark.parametrize(
    ("porcelain", "changed"),
    [
        ("", []),
        ("?? experiments/results/20261108T055008Z_planted_static_only/\n", []),
        (" M experiments/evaluation_summary/summary.md\n", []),
        (" M src/marl_agents/cli.py\n", ["src/marl_agents/cli.py"]),
        ("?? experiments/results/run/\n M docs/results.md\n", ["docs/results.md"]),
        ("R  old.py -> new.py\n", ["new.py"]),
        ('?? "docs/a b.md"\n', ["docs/a b.md"]),
    ],
)
def test_a_runs_own_output_does_not_count_as_uncommitted_code(
    porcelain: str, changed: list[str]
) -> None:
    from marl_agents.evaluation.recorder import source_changes

    assert source_changes(porcelain) == changed


def test_cache_reuse_is_off_unless_asked_and_recorded_when_on(settings: Settings) -> None:
    from marl_agents.cli import apply_cache_choice
    from marl_agents.evaluation.configurations import experiment_metadata

    settings.review.mode = "full"
    settings.review.unit_cache = False
    apply_cache_choice(settings, False)
    assert settings.review.unit_cache is False
    exp = experiment_metadata(settings, benchmark="planted", llm_used=True)
    assert exp["llm_cache_reused"] is False
    apply_cache_choice(settings, True)
    assert settings.review.unit_cache is True
    assert settings.review.cache_ttl_hours >= 720  # outlasts a multi-day free-tier run
    exp = experiment_metadata(settings, benchmark="planted", llm_used=True)
    assert exp["llm_cache_reused"] is True


def test_static_only_runs_record_no_cache_choice(settings: Settings) -> None:
    from marl_agents.evaluation.configurations import experiment_metadata

    settings.review.mode = "static_only"
    assert (
        experiment_metadata(settings, benchmark="planted", llm_used=False)["llm_cache_reused"]
        is None
    )


def test_the_cli_flag_reaches_the_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    from marl_agents import cli

    seen: dict[str, bool] = {}

    def fake(args, s):  # type: ignore[no-untyped-def]
        seen["unit_cache"] = s.review.unit_cache
        return 0

    monkeypatch.setattr(cli, "_eval_ablation", fake)
    assert cli.main(["eval", "ablation", "--reuse-llm-cache"]) == 0
    assert seen["unit_cache"] is True
    assert cli.main(["eval", "ablation"]) == 0
    assert seen["unit_cache"] is False


def _cr_samples(n: int):  # type: ignore[no-untyped-def]
    from marl_agents.evaluation.datasets.codereviewer import CodeReviewerSample

    old = "def f(a):\n    return a\n"
    return [
        CodeReviewerSample(
            sample_id=f"s{i}", task="cls", split="test", label=i % 2, oldf=old,
            patch=f"@@ -1,2 +1,2 @@\n def f(a):\n-    return a\n+    return a + {i}\n",
        )
        for i in range(n)
    ]  # fmt: skip


class _QuotaAfter(MockLLMProvider):
    """Answers `budget` requests, then behaves like a spent daily quota."""

    def __init__(self, budget: int) -> None:
        super().__init__(default=llm_json())
        self.budget = budget

    def generate(self, messages, config=None):  # type: ignore[no-untyped-def]
        from marl_agents.llm.base import QuotaExhaustedError

        if len(self.calls) >= self.budget:
            raise QuotaExhaustedError("daily quota")
        return super().generate(messages, config)


def test_a_quota_stopped_comparison_finishes_later_without_repeating_calls(
    settings: Settings, tmp_path: Path
) -> None:
    from marl_agents.cli import apply_cache_choice

    settings.review.cache_dir = str(tmp_path / "cache")
    apply_cache_choice(settings, True)
    samples = _cr_samples(4)
    configs = ["llm_only", "static_llm", "static_llm_rag"]

    def run(llm: MockLLMProvider) -> dict:  # type: ignore[type-arg]
        _folder, m = run_ablation(
            "codereviewer", settings, llm, configs, samples=samples, task="cls",
            split="test", seed=42, limit=4, workers=1, results_dir=tmp_path / "results",
        )  # fmt: skip
        out = {}
        for key, names in m["runs"].items():
            metrics = json.loads((tmp_path / "results" / names[0] / "metrics.json").read_text())
            out[key] = (metrics["n_evaluated"], metrics["n_failed"], metrics["experiment"])
        return out

    day1 = _QuotaAfter(budget=5)
    first = run(day1)
    assert sum(n_failed for _, n_failed, _ in first.values()) > 0  # the quota stopped it
    assert len(day1.calls) == 5

    day2 = _QuotaAfter(budget=100)
    second = run(day2)
    assert all(n_failed == 0 and n == 4 for n, n_failed, _ in second.values())  # complete
    assert len(day2.calls) == 12 - 5  # only the work that day one did not finish
    assert all(exp["llm_cache_reused"] is True for _, _, exp in second.values())

    day3 = _QuotaAfter(budget=0)
    assert all(n_failed == 0 for _, n_failed, _ in run(day3).values())  # all from the cache
    assert day3.calls == []


def test_without_the_flag_every_run_calls_the_model_again(
    settings: Settings, tmp_path: Path
) -> None:
    settings.review.cache_dir = str(tmp_path / "cache")
    settings.review.unit_cache = False
    llm = MockLLMProvider(default=llm_json())
    for _ in range(2):
        run_ablation(
            "codereviewer", settings, llm, ["llm_only"], samples=_cr_samples(2), task="cls",
            split="test", seed=42, limit=2, workers=1, results_dir=tmp_path / "results",
        )  # fmt: skip
    assert len(llm.calls) == 4
