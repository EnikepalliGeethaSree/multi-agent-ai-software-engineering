"""Quota-aware review: nothing twice, resume after a stop, and the classifier's safety rule."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from marl_agents.agents.code_review import CodeReviewAgent
from marl_agents.agents.code_review.scheduling import (
    UnitCache,
    is_protected,
    plan_units,
    unit_fingerprint,
)
from marl_agents.agents.code_review.units import ReviewUnit, build_units
from marl_agents.config import ClassifierSettings, Settings
from marl_agents.core.schemas import AgentRequest, Category, FindingSource, Severity
from marl_agents.ingestion import load_files
from marl_agents.llm import LLMResponse, Message, MockLLMProvider
from marl_agents.llm.base import GenerationConfig, LLMError, QuotaExhaustedError
from marl_agents.llm.classifier import FixedScoreClassifier, change_text
from marl_agents.parsing import RepoIndex
from marl_agents.static_analysis.base import make_finding
from tests.conftest import llm_json

FUNC = "def f(values):\n    total = sum(values)\n    return total / len(values)\n"


def big_file(functions: int, body_lines: int = 40) -> str:
    out = []
    for i in range(functions):
        out.append(f"def function_{i}(x):")
        out += [f"    y{n} = x + {n + i}" for n in range(body_lines)]
        out.append(f"    return y0 + {i}\n")
    return "\n".join(out)


class QuotaAfter(MockLLMProvider):
    """Answers `allowed` calls, then behaves like a spent daily quota."""

    def __init__(self, allowed: int) -> None:
        super().__init__()
        self.allowed = allowed

    def generate(
        self, messages: list[Message], config: GenerationConfig | None = None
    ) -> LLMResponse:
        if len(self.calls) >= self.allowed:
            self.calls.append(list(messages))
            raise QuotaExhaustedError("quota reached", resets_at="2026-11-07T08:00:00+00:00")
        return super().generate(messages, config)


def agent_for(settings: Settings, llm: MockLLMProvider, **kwargs) -> CodeReviewAgent:  # type: ignore[no-untyped-def]
    return CodeReviewAgent(llm, settings=settings, analyzers=[], **kwargs)


def cached_settings(settings: Settings, tmp_path: Path) -> Settings:
    settings.review.unit_cache = True
    settings.review.cache_dir = str(tmp_path / "cache")
    return settings


def finding(line: int, severity: Severity, confidence: float = 0.5, file: str = "a.py"):  # type: ignore[no-untyped-def]
    return make_finding(
        source=FindingSource.RUFF,
        file=file,
        start_line=line,
        end_line=line,
        category=Category.QUALITY,
        severity=severity,
        title="t",
        description="d",
        confidence=confidence,
    )


# ---- duplicates -------------------------------------------------------------------------------


def test_identical_code_is_reviewed_once_and_reported_for_both_files(settings: Settings) -> None:
    llm = MockLLMProvider(
        responder=lambda _m: llm_json(
            [
                {
                    "start_line": 3,
                    "end_line": 3,
                    "category": "bug",
                    "severity": "high",
                    "title": "Division by zero on an empty list",
                    "description": "len(values) can be 0, which raises ZeroDivisionError.",
                    "evidence": "return total / len(values)",
                    "recommendation": "Return 0 when the list is empty.",
                    "confidence": 0.9,
                }
            ]
        )
    )
    settings.rag.enabled = False
    agent = agent_for(settings, llm)
    result = agent.run(
        AgentRequest(snippet="x = 1\n", options={"files": {"a.py": FUNC, "b.py": FUNC}})
    )
    assert len(llm.calls) == 1
    assert result.stats["units_deduplicated"] == 1
    assert {f.file for f in result.findings} == {"a.py", "b.py"}


def test_fingerprint_ignores_position_but_not_content(settings: Settings) -> None:
    repo = load_files(
        {"a.py": FUNC, "b.py": "\n\n" + FUNC, "c.py": FUNC + "# x\n"}, settings.ingestion
    )
    a = ReviewUnit("a.py", 1, 3)
    b = ReviewUnit("b.py", 3, 5)
    c = ReviewUnit("c.py", 1, 4)
    assert unit_fingerprint(repo, a, []) == unit_fingerprint(repo, b, [])
    assert unit_fingerprint(repo, a, []) != unit_fingerprint(repo, c, [])


def test_copies_with_different_static_findings_are_both_reviewed(settings: Settings) -> None:
    repo = load_files({"a.py": FUNC, "b.py": FUNC}, settings.ingestion)
    units = [ReviewUnit("a.py", 1, 3), ReviewUnit("b.py", 1, 3)]
    plan = plan_units(repo, units, [finding(2, Severity.LOW, file="a.py")])
    assert plan.order == [0, 1] and plan.duplicates == {}


# ---- unit cache and resume --------------------------------------------------------------------


def test_cache_key_depends_on_prompt_and_model() -> None:
    a, b = MockLLMProvider(), MockLLMProvider()
    b.model = "other"
    msgs = [Message(role="user", content="x")]
    assert UnitCache.key(msgs, a) != UnitCache.key(msgs, b)
    assert UnitCache.key(msgs, a) != UnitCache.key([Message(role="user", content="y")], a)


def test_cache_entries_expire(tmp_path: Path) -> None:
    cache = UnitCache(tmp_path, ttl_hours=0)
    cache.put("k", "{}")
    assert UnitCache(tmp_path, ttl_hours=0).get("k") is None


def test_second_run_reuses_finished_units_without_llm_calls(
    settings: Settings, tmp_path: Path
) -> None:
    s = cached_settings(settings, tmp_path)
    s.rag.enabled = False
    code = big_file(4, 60)
    llm = MockLLMProvider()
    first = agent_for(s, llm).run(AgentRequest(snippet=code))
    calls = len(llm.calls)
    assert calls == first.stats["units_total"] > 1
    second = agent_for(s, llm).run(AgentRequest(snippet=code))
    assert len(llm.calls) == calls
    assert second.stats["units_from_cache"] == calls and second.stats["run_type"] == "warm"


def test_quota_stop_makes_no_further_calls_and_reports_partial(
    settings: Settings, tmp_path: Path
) -> None:
    s = cached_settings(settings, tmp_path)
    s.rag.enabled = False
    llm = QuotaAfter(allowed=2)
    result = agent_for(s, llm).run(AgentRequest(snippet=big_file(12, 60)))
    total = result.stats["units_total"]
    assert len(llm.calls) == 3  # 2 answered + the one that hit the quota
    assert result.stats["review_status"] == "partial"
    assert result.stats["units_failed"] == total - 2
    assert result.stats["units_not_attempted"] == total - 3
    assert result.stats["quota"]["resets_at"]
    assert len(result.stats["units_failed_list"]) == total - 2


def test_resume_repeats_only_the_units_that_failed(settings: Settings, tmp_path: Path) -> None:
    s = cached_settings(settings, tmp_path)
    s.rag.enabled = False
    code = big_file(12, 60)
    agent_for(s, QuotaAfter(allowed=2)).run(AgentRequest(snippet=code))
    later = MockLLMProvider()
    result = agent_for(s, later).run(AgentRequest(snippet=code))
    assert result.stats["units_from_cache"] == 2
    assert len(later.calls) == result.stats["units_total"] - 2
    assert result.stats["review_status"] == "complete"


def test_no_fix_calls_after_the_quota_ran_out(settings: Settings) -> None:
    settings.rag.enabled = False
    settings.review.suggest_fixes = True
    llm = QuotaAfter(allowed=0)
    result = agent_for(settings, llm).run(AgentRequest(snippet=big_file(2, 60)))
    assert "fixes" not in result.stats and len(llm.calls) == 1


def test_ordinary_failures_do_not_stop_the_other_units(settings: Settings) -> None:
    settings.rag.enabled = False

    class FailsOnce(MockLLMProvider):
        def generate(self, messages, config=None):  # type: ignore[no-untyped-def]
            if not self.calls:
                self.calls.append(list(messages))
                raise LLMError("server error")
            return super().generate(messages, config)

    llm = FailsOnce()
    result = agent_for(settings, llm).run(AgentRequest(snippet=big_file(12, 60)))
    assert len(llm.calls) == result.stats["units_total"] > 1
    assert result.stats["units_failed"] == 1 and "quota" not in result.stats


def test_unit_with_a_secret_finding_is_never_written_to_the_cache(
    settings: Settings, tmp_path: Path
) -> None:
    s = cached_settings(settings, tmp_path)
    s.rag.enabled = False
    code = 'api_key = "sk-abcdefghijklmnopqrstuvwxyz123456"\n' + FUNC
    from marl_agents.static_analysis import SecretsAnalyzer

    agent = CodeReviewAgent(MockLLMProvider(), settings=s, analyzers=[SecretsAnalyzer()])
    result = agent.run(AgentRequest(snippet=code))
    assert result.stats["static_findings_raw"]["secrets"] >= 1
    assert list((tmp_path / "cache" / "llm_units").glob("*.json")) == []


def test_large_file_has_no_silently_skipped_chunks(settings: Settings) -> None:
    settings.rag.enabled = False
    llm = MockLLMProvider()
    code = big_file(40, 60)
    assert code.count("\n") > 2000
    result = agent_for(settings, llm).run(AgentRequest(snippet=code))
    repo = load_files({"snippet.py": code}, settings.ingestion)
    index = RepoIndex.build(repo)
    units = build_units(repo, index.modules["snippet.py"], settings.review.max_unit_lines)
    covered = sum(u.end_line - u.start_line + 1 for u in units)
    assert covered == repo.line_count("snippet.py")
    assert result.stats["units_total"] == len(units) == len(llm.calls)
    assert result.stats["units_failed"] == 0


def test_too_many_units_are_reported(settings: Settings) -> None:
    settings.rag.enabled = False
    settings.review.max_units = 2
    result = agent_for(settings, MockLLMProvider()).run(AgentRequest(snippet=big_file(10, 60)))
    assert any("exceed max_units" in e for e in result.errors)


# ---- classifier -------------------------------------------------------------------------------


GATE = ClassifierSettings(enabled=True, model_dir="x", mode="gate", threshold=0.5)
ORDER = ClassifierSettings(enabled=True, model_dir="x", mode="prioritize")


def changed_units(settings: Settings) -> tuple[object, list[ReviewUnit]]:
    code = "\n".join(f"x{i} = {i}" for i in range(30)) + "\n"
    repo = load_files({"a.py": code, "b.py": code + "y = 2\n"}, settings.ingestion)
    return repo, [
        ReviewUnit("a.py", 1, 10, changed=[(2, 3)]),
        ReviewUnit("b.py", 1, 31, changed=[(31, 31)]),
    ]


def test_classifier_orders_units_riskiest_first(settings: Settings) -> None:
    repo, units = changed_units(settings)
    clf = FixedScoreClassifier(lambda t: 0.9 if "y = 2" in t else 0.1)
    plan = plan_units(repo, units, [], clf, ORDER)
    assert plan.order == [1, 0] and plan.skipped == {}


def test_gate_skips_low_scores_and_reports_them(settings: Settings) -> None:
    repo, units = changed_units(settings)
    clf = FixedScoreClassifier(lambda t: 0.9 if "y = 2" in t else 0.1)
    plan = plan_units(repo, units, [], clf, GATE)
    assert plan.order == [1] and list(plan.skipped) == [0]
    assert plan.classifier["skipped"] == 1


@pytest.mark.parametrize(
    ("severity", "confidence"),
    [(Severity.CRITICAL, 0.5), (Severity.HIGH, 0.5), (Severity.LOW, 0.95)],
)
def test_gate_never_skips_a_unit_with_a_serious_static_finding(
    settings: Settings, severity: Severity, confidence: float
) -> None:
    repo, units = changed_units(settings)
    serious = finding(3, severity, confidence)
    assert is_protected(units[0], [serious])
    plan = plan_units(repo, units, [serious], FixedScoreClassifier(lambda _t: 0.0), GATE)
    assert 0 in plan.order and plan.classifier["protected"] == 1


def test_low_risk_score_never_removes_a_static_finding(settings: Settings) -> None:
    from marl_agents.static_analysis.base import AnalyzerOutput, StaticAnalyzer

    class Critical(StaticAnalyzer):
        name = "fake"

        def analyze(self, repo, index, files, scope=None):  # type: ignore[no-untyped-def]
            return AnalyzerOutput([finding(1, Severity.CRITICAL, 0.99, "snippet.py")])

    settings.rag.enabled = False
    settings.classifier = GATE
    llm = MockLLMProvider()
    agent = CodeReviewAgent(
        llm,
        settings=settings,
        analyzers=[Critical()],
        classifier=FixedScoreClassifier(lambda _t: 0.0),
    )
    result = agent.run(
        AgentRequest(snippet=FUNC, options={"changed_lines": {"snippet.py": [[1, 3]]}})
    )
    assert len(result.findings) == 1  # kept, whatever the classifier scored
    assert len(llm.calls) == 1  # protected, so it still reached the LLM


def test_gated_units_are_counted_and_stated(settings: Settings) -> None:
    settings.rag.enabled = False
    settings.classifier = GATE
    llm = MockLLMProvider()
    agent = agent_for(settings, llm, classifier=FixedScoreClassifier(lambda _t: 0.0))
    result = agent.run(
        AgentRequest(snippet=FUNC, options={"changed_lines": {"snippet.py": [[1, 3]]}})
    )
    assert llm.calls == [] and result.stats["units_skipped"] == 1
    assert result.stats["classifier"]["skipped"] == 1
    assert any("not sent to the LLM" in e for e in result.errors)
    assert result.stats["review_status"] == "complete"


def test_classifier_is_not_applied_to_whole_file_reviews(settings: Settings) -> None:
    settings.rag.enabled = False
    settings.classifier = GATE
    llm = MockLLMProvider()
    agent = agent_for(settings, llm, classifier=FixedScoreClassifier(lambda _t: 0.0))
    result = agent.run(AgentRequest(snippet=FUNC))
    assert len(llm.calls) == 1 and result.stats["classifier"]["applied"] is False


def test_change_text_is_a_stable_format() -> None:
    assert change_text("@@ -1 +1 @@\r\n-a\r\n+b\r\n") == "@@ -1 +1 @@\n-a\n+b"
    assert len(change_text("x" * 9000)) == 4000


def test_call_log_names_the_review_unit(settings: Settings) -> None:
    settings.rag.enabled = False
    result = agent_for(settings, MockLLMProvider()).run(AgentRequest(snippet=FUNC))
    calls = result.stats["llm_calls"]
    assert len(calls) == 1 and calls[0]["label"].startswith("snippet.py:1-")
    assert json.dumps(calls)  # stored with the review


def test_gate_uses_the_models_own_threshold_unless_one_is_set(settings: Settings) -> None:
    repo, units = changed_units(settings)
    scorer = FixedScoreClassifier(lambda _text: 0.45)
    scorer.threshold = 0.44
    own = ClassifierSettings(enabled=True, model_dir="x", mode="gate")
    kept = plan_units(repo, units, [], scorer, own)
    assert (kept.classifier["threshold"], kept.classifier["skipped"]) == (0.44, 0)
    forced = ClassifierSettings(enabled=True, model_dir="x", mode="gate", threshold=0.5)
    dropped = plan_units(repo, units, [], scorer, forced)
    assert dropped.classifier["threshold"] == 0.5
    assert dropped.classifier["skipped"] == len(dropped.scores) > 0
