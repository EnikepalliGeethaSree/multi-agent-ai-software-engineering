"""The whole Bug Detection evaluation, offline: a fake repository cache and the mock LLM."""

import json
import shutil
from pathlib import Path

import pytest

from marl_agents.config import Settings
from marl_agents.core.schemas import AgentRequest, SuspectFunction
from marl_agents.evaluation.datasets.bugsinpy import BugsInPySample
from marl_agents.evaluation.datasets.bugsinpy_repo import BugRepoCache, resolve_bug
from marl_agents.evaluation.runners import bug_detection as runner
from marl_agents.llm.base import GenerationConfig, LLMResponse, Message, QuotaExhaustedError
from marl_agents.llm.mock import MockLLMProvider

BUGGY = "def half(x):\n    return x // 2\n\n\ndef other(d):\n    return d\n"
FIXED = "def half(x):\n    return x / 2\n\n\ndef other(d):\n    return d\n"
TEST = "from pkg.core import half\n\n\ndef test_half():\n    assert half(1) == 0.5\n"
PATCH = (
    "diff --git a/pkg/core.py b/pkg/core.py\n--- a/pkg/core.py\n+++ b/pkg/core.py\n"
    "@@ -1,2 +1,2 @@\n def half(x):\n-    return x // 2\n+    return x / 2\n"
)


class FakeCache(BugRepoCache):
    """Serves one small project for every bug, so no test touches the network."""

    def ensure_commits(self, sample: BugsInPySample) -> tuple[str, str]:
        return sample.buggy_commit, sample.fixed_commit

    def show(self, project: str, sha: str, path: str) -> str | None:
        if path == "tests/test_core.py":
            return TEST
        return (FIXED if sha.startswith("b") else BUGGY) if path == "pkg/core.py" else None

    def snapshot(self, project, sha, dest: Path, settings=None) -> int:
        (dest / "pkg").mkdir()
        (dest / "pkg" / "core.py").write_text(BUGGY, encoding="utf-8", newline="\n")
        return 1


def sample(n: int) -> BugsInPySample:
    return BugsInPySample(
        sample_id=f"demo-{n}", project="demo", bug_id=n,
        github_url="https://github.com/acme/demo", buggy_commit="a" * 40, fixed_commit="b" * 40,
        test_files=["tests/test_core.py"], test_names=["test_half"], patch=PATCH,
        source_files=["pkg/core.py"], changed_lines=2,
    )  # fmt: skip


@pytest.fixture
def env(settings: Settings, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    cache = FakeCache(tmp_path / "cache")
    bugs = [resolve_bug(sample(n), cache) for n in (1, 2)]
    audit = {
        "split": "dev",
        "pool": 2,
        "checked": 2,
        "usable": 2,
        "ineligible": {"change_outside_a_function": 1},
        "sample_ids": [b.sample_id for b in bugs],
    }
    monkeypatch.setattr(
        runner, "select_bugs", lambda _s, _c, _sp, limit, _seed, _p: (bugs[:limit], audit)
    )
    monkeypatch.setattr(runner, "_cache_root", lambda _s: tmp_path / "data")
    return settings, cache, tmp_path / "runs"


def options(task: str, *configs: str, **extra) -> runner.BugEvalOptions:
    return runner.BugEvalOptions(
        task=task, limit=2, configurations=list(configs or ["static_only"]), **extra
    )


def metrics(path: Path) -> dict:
    return json.loads((path / "metrics.json").read_text(encoding="utf-8"))


def rows(path: Path) -> list[dict]:
    return [
        json.loads(line)
        for line in (path / "predictions.jsonl").read_text(encoding="utf-8").splitlines()
    ]


def rank_half(messages: list[Message]) -> str:
    prompt = messages[1].content
    line = next(ln for ln in prompt.splitlines() if "::half " in ln)
    return json.dumps({"hypothesis": "h", "ranking": [{"ref": line.split()[1], "reason": "r"}]})


def test_naming_the_function_around_a_nested_bug_counts(env) -> None:
    _settings, cache, _out = env
    bug = resolve_bug(sample(1), cache)
    bug.gold[0].changed_lines = [3]
    bug.gold[0].qualname = "outer.inner"

    def suspect(symbol: str, start: int, end: int, file: str = "pkg/core.py") -> SuspectFunction:
        return SuspectFunction(
            rank=1, file=file, symbol=symbol, start_line=start, end_line=end, score=0.0
        )

    suspects = [
        suspect("outer", 1, 5),
        suspect("outer.inner", 2, 4),
        suspect("unrelated", 7, 9),
        suspect("same_lines_other_file", 1, 5, "pkg/other.py"),
    ]
    assert runner.gold_names(bug, suspects) == {"pkg/core.py::outer", "pkg/core.py::outer.inner"}


def test_audit_says_why_bugs_are_unusable_and_is_recorded_as_no_llm(env) -> None:
    settings, cache, out = env
    path = runner.run_audit(settings, "dev", 42, None, cache, recorder_dir=out)
    assert "change_outside_a_function" in (path / "summary.md").read_text(encoding="utf-8")
    assert "mode: static_only" in (path / "config.yaml").read_text(encoding="utf-8")


def test_static_localization_run(env) -> None:
    settings, cache, out = env
    paths = runner.run_bug_evaluation(
        options("localization"), settings, None, cache, recorder_dir=out
    )
    assert len(paths) == 1
    m = metrics(paths[0])
    assert m["n"] == 2 and m["top_function"]["top_1"] == 1.0 and m["complete"] is True
    meta = json.loads((paths[0] / "meta.json").read_text(encoding="utf-8"))
    assert meta["sample_ids"] == ["demo-1", "demo-2"]
    assert meta["experiment"]["configuration"]["key"] == "static_only"
    assert meta["experiment"]["prompt_versions"] == {}
    assert meta["experiment"]["sample_fingerprint"]
    assert meta["git_commit"]


def test_llm_localization_records_its_prompts_and_never_sees_the_fix(env) -> None:
    settings, cache, out = env
    llm = MockLLMProvider(responder=rank_half)
    paths = runner.run_bug_evaluation(
        options("localization", "llm_only"), settings, llm, cache, recorder_dir=out
    )
    assert len(llm.calls) == 2
    meta = json.loads((paths[0] / "meta.json").read_text(encoding="utf-8"))
    assert meta["experiment"]["prompt_versions"]["bug_localize"]
    for call in llm.calls:
        text = call[1].content
        assert "x // 2" in text  # the buggy code
        assert "x / 2\n" not in text  # never the fix


def test_detection_shows_each_version_once_and_only_marks_nothing(env) -> None:
    settings, cache, out = env

    def flag_buggy(messages: list[Message]) -> str:
        prompt = messages[1].content
        if "x // 2" not in prompt:
            return '{"findings": []}'
        return json.dumps(
            {
                "findings": [
                    {
                        "start_line": 2,
                        "end_line": 2,
                        "category": "bug",
                        "bug_type": "logic",
                        "severity": "high",
                        "title": "Floor division loses the fraction",
                        "root_cause": "// truncates",
                        "trigger": "x is odd",
                        "involved_names": ["x"],
                        "evidence": ["return x // 2"],
                        "confidence": 0.9,
                        "recommendation": "Use / instead of // in half.",
                    }
                ]
            }
        )

    llm = MockLLMProvider(responder=flag_buggy)
    paths = runner.run_bug_evaluation(
        options("detection", "llm_only"), settings, llm, cache, recorder_dir=out
    )
    assert len(llm.calls) == 4
    assert sum("x // 2" in c[1].content for c in llm.calls) == 2
    assert sum("x / 2\n" in c[1].content for c in llm.calls) == 2
    assert all("def other" not in c[1].content for c in llm.calls)
    assert all("\n>" not in c[1].content for c in llm.calls)
    m = metrics(paths[0])
    assert m["function_level"]["precision"] == 1.0 and m["function_level"]["recall"] == 1.0
    assert m["at_gold_lines"]["recall"] == 1.0 and m["pairs"]["discrimination"] == 1.0
    assert (paths[0] / "summary.md").read_text(encoding="utf-8").count("Mock LLM") == 1


def test_comparison_is_written_for_several_configurations(env) -> None:
    settings, cache, out = env
    llm = MockLLMProvider(responder=rank_half)
    paths = runner.run_bug_evaluation(
        options("localization", "static_only", "llm_only"), settings, llm, cache, recorder_dir=out
    )
    assert len(paths) == 3 and "comparison" in paths[-1].name
    table = metrics(paths[-1])["comparison"]["top_1"][0]
    assert table["n"] == 2 and table["p_value"] == 1.0


def test_rag_configuration_runs_with_the_memory_store(env) -> None:
    settings, cache, out = env
    llm = MockLLMProvider(responder=rank_half)
    paths = runner.run_bug_evaluation(
        options("localization", "static_llm_rag"), settings, llm, cache, recorder_dir=out
    )
    assert metrics(paths[0])["n"] == 2
    assert metrics(paths[0])["experiment"]["configuration"]["letter"] == "D"


class OneCallThenQuota(MockLLMProvider):
    def __init__(self, allowed: int) -> None:
        super().__init__(responder=self.reply)
        self.allowed = allowed

    @staticmethod
    def reply(messages: list[Message]) -> str:
        is_ranking = "Candidate functions" in messages[1].content
        return rank_half(messages) if is_ranking else '{"findings": []}'

    def generate(
        self, messages: list[Message], config: GenerationConfig | None = None
    ) -> LLMResponse:
        if self.allowed <= 0:
            raise QuotaExhaustedError("daily quota reached")
        self.allowed -= 1
        return super().generate(messages, config)


def test_quota_stop_keeps_work_and_the_same_command_continues(env) -> None:
    settings, cache, out = env
    first = runner.run_bug_evaluation(
        options("localization", "llm_only"), settings, OneCallThenQuota(1), cache, recorder_dir=out
    )
    m = metrics(first[0])
    assert m["n"] == 1 and m["complete"] is False
    summary = (first[0] / "summary.md").read_text(encoding="utf-8")
    assert "**Incomplete:** 1 sample(s)" in summary
    meta = json.loads((first[0] / "meta.json").read_text(encoding="utf-8"))
    assert "quota" in meta["stopped"].lower() and meta["pending"] == 1

    llm = OneCallThenQuota(5)
    second = runner.run_bug_evaluation(
        options("localization", "llm_only"), settings, llm, cache, recorder_dir=out
    )
    assert len(llm.calls) == 1  # only the bug that was left
    assert metrics(second[0])["n"] == 2 and metrics(second[0])["complete"] is True


def test_quota_stop_during_detection_also_resumes(env) -> None:
    settings, cache, out = env
    first = runner.run_bug_evaluation(
        options("detection", "llm_only"), settings, OneCallThenQuota(1), cache, recorder_dir=out
    )
    assert metrics(first[0])["n_functions"] == 1
    llm = OneCallThenQuota(10)
    second = runner.run_bug_evaluation(
        options("detection", "llm_only"), settings, llm, cache, recorder_dir=out
    )
    assert len(llm.calls) == 3 and metrics(second[0])["n_functions"] == 4


def test_call_budget_stops_between_bugs(env) -> None:
    settings, cache, out = env
    llm = MockLLMProvider(responder=rank_half)
    paths = runner.run_bug_evaluation(
        options("localization", "llm_only", max_llm_calls=1), settings, llm, cache, recorder_dir=out
    )
    assert len(llm.calls) == 1 and metrics(paths[0])["n"] == 1


def test_changing_a_prompt_or_model_does_not_reuse_saved_rows(env, monkeypatch) -> None:
    settings, _cache, _out = env
    before = runner.ledger_for(settings, options("localization")).path
    monkeypatch.setattr(runner, "prompt_versions", lambda: {"bug_system": "9.9"})
    assert runner.ledger_for(settings, options("localization")).path != before
    monkeypatch.undo()


def test_failed_llm_reply_is_counted_as_a_miss(env, monkeypatch) -> None:
    settings, cache, out = env
    monkeypatch.setattr(runner, "_cache_root", lambda _s: out.parent / "data2")
    llm = MockLLMProvider(default="not json")
    paths = runner.run_bug_evaluation(
        options("localization", "llm_only"), settings, llm, cache, recorder_dir=out
    )
    m = metrics(paths[0])
    assert m["n"] == 2 and m["n_failed"] == 2 and m["top_function"]["top_1"] == 0.0
    assert (paths[0] / "errors.jsonl").read_text(encoding="utf-8").count("sample_id") == 2


def test_snapshots_are_removed_after_each_bug(env, tmp_path: Path) -> None:
    settings, cache, out = env
    runner.run_bug_evaluation(options("detection"), settings, None, cache, recorder_dir=out)
    snapshots = tmp_path / "data" / "bugsinpy" / "snapshots"
    assert not snapshots.exists() or not any(snapshots.iterdir())


def test_fixed_version_differs_only_in_the_patched_file(env) -> None:
    settings, cache, _out = env
    bug = resolve_bug(sample(1), cache)
    snapshot = runner._Snapshot(cache, bug, settings)
    try:
        buggy_repo, _ = snapshot.load("buggy")
        assert "x // 2" in buggy_repo.read_text("pkg/core.py")
        fixed_repo, _ = snapshot.load("fixed")
        assert "x / 2" in fixed_repo.read_text("pkg/core.py")
    finally:
        snapshot.close()
    assert not snapshot.dir.exists()


def test_the_agent_never_runs_analyzed_code(settings: Settings, tmp_path: Path) -> None:
    """A repository whose import would leave a mark. Analysis must leave none."""
    from marl_agents.agents.bug_detection import BugDetectionAgent

    marker = tmp_path / "executed"
    code = f"from pathlib import Path\nPath({str(marker)!r}).write_text('x')\n"
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "boom.py").write_text(code, encoding="utf-8")
    (repo / "test_boom.py").write_text("import boom\n\n\ndef test_a():\n    assert 0\n")
    settings.review.mode = "static_only"
    agent = BugDetectionAgent(None, settings=settings)
    agent.run(AgentRequest(repo_path=str(repo), options={"failing_test": "test_boom.py::test_a"}))
    assert not marker.exists()
    shutil.rmtree(repo)
