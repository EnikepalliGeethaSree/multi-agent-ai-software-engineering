import json

import pytest

from marl_agents.agents import AGENT_REGISTRY, get_agent_class
from marl_agents.agents.bug_detection import (
    BugDetectionAgent,
    FailingTestError,
    make_bug_detection_node,
)
from marl_agents.agents.bug_detection import localize as loc
from marl_agents.agents.bug_detection.agent import resolve_test
from marl_agents.agents.bug_detection.checks import (
    NO_TRIGGER,
    UNKNOWN_NAME,
    claim_problem,
    static_detail,
)
from marl_agents.agents.bug_detection.llm_schema import (
    LLMBugFinding,
    LLMLocalization,
    parse_bug_type,
)
from marl_agents.agents.bug_detection.prompts import load_prompt, prompt_versions
from marl_agents.agents.bug_detection.selection import select_units
from marl_agents.agents.code_review.agent import CodeReviewAgent
from marl_agents.agents.code_review.units import ReviewUnit
from marl_agents.config import Settings
from marl_agents.core.schemas import (
    AgentRequest,
    BugDetail,
    BugType,
    Category,
    Finding,
    FindingSource,
    Severity,
)
from marl_agents.findings.dedup import deduplicate
from marl_agents.llm.base import LLMError, QuotaExhaustedError
from marl_agents.llm.mock import MockLLMProvider
from marl_agents.reports import to_markdown

CODE = """def mean(values):
    total = 0
    for v in values:
        total += v
    return total / len(values)
"""


def bug_json(**overrides) -> str:
    finding = {
        "start_line": 5,
        "end_line": 5,
        "category": "edge_case",
        "bug_type": "boundary",
        "severity": "high",
        "title": "Empty input crashes",
        "root_cause": "Nothing handles an empty list before dividing.",
        "trigger": "values is an empty list",
        "expected": "a clear result or error",
        "actual": "ZeroDivisionError",
        "involved_names": ["values", "total"],
        "evidence": ["return total / len(values)"],
        "repro_steps": ["Call mean([])"],
        "recommendation": "Return 0 for an empty list.",
        "test_recommendation": "Assert mean([]) == 0.",
        "confidence": 0.9,
    }
    finding.update(overrides)
    return json.dumps({"findings": [finding], "static_assessments": []})


def make_agent(settings: Settings, responses: list[str] | None = None, mode: str = "llm_only"):
    settings.review.mode = mode  # type: ignore[assignment]
    settings.rag.enabled = False
    llm = MockLLMProvider(responses=responses) if mode != "static_only" else None
    return BugDetectionAgent(llm, settings=settings), llm


def snippet(code: str = CODE, **options) -> AgentRequest:
    return AgentRequest(snippet=code, snippet_filename="stats.py", options=options)


# ---- contract ------------------------------------------------------------------------------------


def test_registered_and_standalone() -> None:
    assert "bug_detection" in AGENT_REGISTRY
    assert get_agent_class("bug_detection") is BugDetectionAgent


def test_happy_path_keeps_the_bug_detail(settings: Settings) -> None:
    agent, _llm = make_agent(settings, [bug_json()])
    result = agent.run(snippet())
    assert result.agent == "bug_detection"
    finding = result.findings[0]
    assert finding.id == "BD-001" and finding.category is Category.EDGE_CASE
    assert finding.bug is not None
    assert finding.bug.bug_type is BugType.BOUNDARY
    assert finding.bug.trigger == "values is an empty list"
    assert finding.bug.repro_steps == ["Call mean([])"]
    assert finding.description == "Nothing handles an empty list before dividing."
    assert result.metadata.prompt_versions == prompt_versions()


def test_malformed_reply_is_a_failed_unit_not_a_crash(settings: Settings) -> None:
    agent, _llm = make_agent(settings, ["not json", "still not json"])
    result = agent.run(snippet())
    assert result.findings == [] and result.stats["units_failed"] == 1


def test_finding_with_invented_evidence_is_rejected(settings: Settings) -> None:
    agent, _llm = make_agent(settings, [bug_json(evidence=["this is not in the file"])])
    result = agent.run(snippet())
    assert result.findings == [] and result.rejected_findings == 1


def test_finding_without_a_trigger_is_rejected_and_counted(settings: Settings) -> None:
    agent, _llm = make_agent(settings, [bug_json(trigger="")])
    result = agent.run(snippet())
    assert result.findings == []
    assert result.stats["llm_rejected_by_reason"] == {NO_TRIGGER: 1}
    assert result.rejected_findings == 1


def test_finding_about_a_name_not_in_the_code_is_rejected(settings: Settings) -> None:
    agent, _llm = make_agent(settings, [bug_json(involved_names=["config_cache"])])
    result = agent.run(snippet())
    assert result.findings == []
    assert result.stats["llm_rejected_by_reason"] == {UNKNOWN_NAME: 1}


def test_runs_with_rag_disabled_and_sends_no_context(settings: Settings) -> None:
    agent, llm = make_agent(settings, [bug_json()])
    agent.run(snippet())
    assert result_prompt(llm).count("[similar]") == 0


def test_static_only_needs_no_llm_and_every_finding_has_detail(settings: Settings) -> None:
    agent, _llm = make_agent(settings, mode="static_only")
    result = agent.run(snippet())
    assert [f.rule_id for f in result.findings] == ["BUG-DIV-BY-LEN"]
    assert result.findings[0].bug is not None
    assert result.findings[0].bug.bug_type is BugType.BOUNDARY


def test_static_findings_that_are_not_defects_are_left_out(settings: Settings) -> None:
    agent, _llm = make_agent(settings, mode="static_only")
    result = agent.run(snippet("import os\n\n\ndef f(x):\n    return x\n"))
    assert result.findings == []


def test_quality_scope_matches_code_review_otherwise(settings: Settings) -> None:
    """The same input through Code Review still reports what it always did."""
    settings.review.mode = "static_only"
    settings.rag.enabled = False
    review = CodeReviewAgent(None, settings=settings).run(snippet("import os\n\n\nx = 1\n"))
    assert any(f.rule_id == "F401" for f in review.findings)
    assert all(f.id.startswith("CR-") for f in review.findings)


def test_node_wraps_the_agent(settings: Settings) -> None:
    agent, _llm = make_agent(settings, mode="static_only")
    state = make_bug_detection_node(agent)({"request": snippet().model_dump()})
    assert state["bug_detection_result"].agent == "bug_detection"


def test_llm_prompt_carries_the_injection_defence(settings: Settings) -> None:
    agent, llm = make_agent(settings, [bug_json()])
    agent.run(snippet())
    assert llm is not None
    assert "DATA, not instructions" in llm.calls[0][0].content


def result_prompt(llm) -> str:
    return llm.calls[0][1].content


# ---- budget --------------------------------------------------------------------------------------


def _many_functions(n: int) -> str:
    return "\n\n".join(
        f"def f{i}(d):\n" + ("    x = 1\n" * 190) + "    return x\n" for i in range(n)
    )


def test_a_scan_spends_at_most_its_budget_and_says_so(settings: Settings) -> None:
    settings.bugs.max_units = 2
    agent, llm = make_agent(settings)
    assert llm is not None
    result = agent.run(snippet(_many_functions(5)))
    assert len(llm.calls) == 2
    assert result.stats["scan_coverage"]["units_total"] == 5
    assert result.stats["scan_coverage"]["units_selected"] == 2
    assert any("Scan budget" in e for e in result.errors)


def test_riskiest_unit_is_chosen(make_repo) -> None:
    repo = make_repo({"a.py": "x = 1\n", "b.py": "y = 2\n"})
    units = [ReviewUnit("a.py", 1, 1), ReviewUnit("b.py", 1, 1)]
    signal = Finding(
        id="T", file="b.py", start_line=1, end_line=1, category=Category.BUG,
        severity=Severity.HIGH, title="t", description="d", confidence=0.9,
    )  # fmt: skip
    chosen, coverage = select_units(units, repo, [signal], 1)
    assert [u.file for u in chosen] == ["b.py"]
    assert not coverage.complete and coverage.lines_selected == 1


def test_function_scope_shows_exact_lines_and_marks_nothing(settings: Settings) -> None:
    code = "def a():\n    return 1\n\n\ndef b(x):\n    return x / len(x)\n"
    agent, llm = make_agent(settings, ['{"findings": []}'])
    agent.run(snippet(code, function_scope={"stats.py": [(5, 6)]}))
    prompt = result_prompt(llm)
    assert "lines 5-6 of 6" in prompt
    assert "def a" not in prompt
    # A mark on the changed lines would hand the benchmark's answer to the model.
    assert "marked with" not in prompt and "\n>" not in prompt


# ---- claim checks and parsing --------------------------------------------------------------------


def _finding(bug: BugDetail | None) -> Finding:
    return Finding(
        id="T", file="a.py", start_line=1, end_line=1, category=Category.BUG,
        severity=Severity.HIGH, title="t", description="d", confidence=0.5, bug=bug,
    )  # fmt: skip


def test_claim_checks() -> None:
    code = "self.items[0].name = other"
    assert claim_problem(_finding(None), code) == NO_TRIGGER
    assert claim_problem(_finding(None), code, require_trigger=False) is None
    ok = BugDetail(trigger="t", involved_names=["self.items[0]", "None", "other"])
    assert claim_problem(_finding(ok), code) is None
    bad = BugDetail(trigger="t", involved_names=["missing_name"])
    assert claim_problem(_finding(bad), code) == UNKNOWN_NAME


def test_bug_type_is_lenient_and_never_rejects_a_finding() -> None:
    assert parse_bug_type("Off-by-one") is BugType.BOUNDARY
    assert parse_bug_type("race condition") is BugType.CONCURRENCY
    assert parse_bug_type("Null/Exception") is BugType.NULL_EXCEPTION
    assert parse_bug_type("something else") is BugType.OTHER


def test_llm_bug_finding_accepts_common_variations() -> None:
    item = LLMBugFinding.model_validate(
        {
            "start_line": 1,
            "category": "logic",
            "severity": "major",
            "title": "t",
            "bug_type": "NULL",
            "trigger": None,
            "involved_names": "x",
            "repro_steps": None,
        }
    )
    assert item.bug_type is BugType.NULL_EXCEPTION and item.trigger == ""
    assert item.involved_names == ["x"] and item.repro_steps == []


def test_static_detail_uses_the_rule_and_category() -> None:
    flagged = _finding(None).model_copy(update={"rule_id": "BUG-OFF-BY-ONE"})
    assert static_detail(flagged).bug_type is BugType.BOUNDARY
    secure = _finding(None).model_copy(update={"rule_id": "S608", "category": Category.SECURITY})
    assert static_detail(secure).bug_type is BugType.SECURITY


def test_merging_with_a_static_finding_keeps_the_llm_detail() -> None:
    detail = BugDetail(bug_type=BugType.LOGIC, trigger="t", root_cause="why")
    llm = _finding(detail).model_copy(
        update={"sources": [FindingSource.LLM], "title": "wrong total here", "evidence": ["x"]}
    )
    tool = _finding(None).model_copy(
        update={"sources": [FindingSource.AST], "title": "wrong total here", "evidence": ["x"],
                "description": "a much longer description than the other finding has"}
    )  # fmt: skip
    merged = deduplicate([tool, llm]).findings
    assert len(merged) == 1 and merged[0].bug == detail


def test_report_shows_what_makes_a_bug_finding_useful(settings: Settings) -> None:
    agent, _llm = make_agent(settings, [bug_json()])
    text = to_markdown(agent.run(snippet()))
    assert text.startswith("# Bug Detection Report")
    assert "**Trigger:** values is an empty list" in text
    assert "**Reproduce:**" in text and "Call mean([])" in text


def test_prompts_are_versioned_and_render() -> None:
    assert set(prompt_versions()) == {"bug_system", "bug_review", "bug_localize"}
    text = load_prompt("localize").render(
        failing_test="t", error_section="", hints_note="", candidates="c"
    )
    assert '"ranking"' in text


# ---- localization --------------------------------------------------------------------------------

REPO = {
    "shop/cart.py": (
        "from shop.money import round_price\n\n\n"
        "def total(items):\n    return round_price(sum(items))\n\n\n"
        "def unrelated():\n    return 2\n"
    ),
    "shop/money.py": "def round_price(x):\n    return int(x)\n",
    "shop/other.py": "def far_away():\n    return 3\n",
    "tests/test_cart.py": "from shop.cart import total\n\n\ndef helper():\n    return 1\n",
}
TEST = "def test_total():\n    assert total([1.5]) == 1.5\n"


def test_candidates_follow_calls_and_leave_out_tests(make_index) -> None:
    pool = loc.structural_candidates(make_index(REPO), TEST, "tests/test_cart.py")
    names = {q for _f, q in pool}
    assert {"total", "round_price"} <= names
    assert "far_away" not in names and "helper" not in names


def test_called_function_ranks_above_what_it_calls(make_index) -> None:
    pool = loc.structural_candidates(make_index(REPO), TEST, "tests/test_cart.py")
    assert loc.ranked(pool)[0].symbol.name == "total"


def test_rest_of_a_reached_file_is_a_weak_candidate(make_index) -> None:
    pool = loc.structural_candidates(make_index(REPO), TEST)
    assert pool[("shop/cart.py", "unrelated")].score < pool[("shop/cart.py", "total")].score


def test_traceback_frame_outranks_names(make_index) -> None:
    error = 'File "shop/money.py", line 2, in round_price\n    return int(x)\n'
    pool = loc.structural_candidates(make_index(REPO), TEST, None, error)
    assert loc.ranked(pool)[0].symbol.name == "round_price"


def test_identifiers_in_test_handles_an_indented_method() -> None:
    called, _other = loc.identifiers_in_test("    def test_a(self):\n        self.go(x)\n")
    assert "go" in called


def test_static_localization_needs_no_llm(settings: Settings, make_repo) -> None:
    from marl_agents.parsing import RepoIndex

    agent, _llm = make_agent(settings, mode="static_only")
    repo = make_repo(REPO)
    found = agent.localize(repo, RepoIndex.build(repo), TEST, "tests/test_cart.py")
    assert found.ranked_by == "static" and found.suspects[0].symbol == "total"
    assert [s.rank for s in found.suspects] == list(range(1, len(found.suspects) + 1))


def localized(settings: Settings, make_repo, reply: str, mode: str = "llm_only"):
    from marl_agents.parsing import RepoIndex

    agent, llm = make_agent(settings, [reply], mode=mode)
    repo = make_repo(REPO)
    return agent.localize(repo, RepoIndex.build(repo), TEST, "tests/test_cart.py"), llm


def _ref_of(llm, name: str) -> str:
    prompt = llm.calls[0][1].content
    line = next(ln for ln in prompt.splitlines() if ln.startswith("### ") and f"::{name} " in ln)
    return line.split()[1]


def test_llm_reorders_the_candidates(settings: Settings, make_repo) -> None:
    from marl_agents.parsing import RepoIndex

    agent, llm = make_agent(settings, mode="llm_only")
    assert llm is not None

    def reply(messages):
        prompt = messages[1].content
        line = next(ln for ln in prompt.splitlines() if "::round_price " in ln)
        return json.dumps(
            {"hypothesis": "int() truncates", "ranking": [{"ref": line.split()[1], "reason": "r"}]}
        )

    llm._responder = reply
    repo = make_repo(REPO)
    found = agent.localize(repo, RepoIndex.build(repo), TEST, "tests/test_cart.py")
    assert found.ranked_by == "llm" and found.suspects[0].symbol == "round_price"
    assert found.hypothesis == "int() truncates"
    assert found.suspects[0].reasons[0] == "LLM: r"
    assert found.candidates_shown == found.candidates_considered


def test_reference_outside_the_list_is_dropped(settings: Settings, make_repo) -> None:
    reply = json.dumps({"hypothesis": "h", "ranking": [{"ref": "F99"}, "F1"]})
    found, _llm = localized(settings, make_repo, reply)
    assert found.suspects and all(s.file != "F99" for s in found.suspects)
    assert any("F99" in e for e in found.errors)


def test_failed_llm_falls_back_to_static_order_and_says_so(settings: Settings, make_repo) -> None:
    found, _llm = localized(settings, make_repo, "not json")
    assert found.llm_failed and found.ranked_by == "static" and found.suspects


class _NoQuota(MockLLMProvider):
    def generate(self, messages, config=None):
        raise QuotaExhaustedError("daily quota")


class _Broken(MockLLMProvider):
    def generate(self, messages, config=None):
        raise LLMError("server error")


def test_quota_stop_is_raised_so_a_run_can_resume(settings: Settings, make_repo) -> None:
    from marl_agents.parsing import RepoIndex

    settings.review.mode = "llm_only"
    settings.rag.enabled = False
    agent = BugDetectionAgent(_NoQuota(), settings=settings)
    repo = make_repo(REPO)
    with pytest.raises(QuotaExhaustedError):
        agent.localize(repo, RepoIndex.build(repo), TEST)


def test_provider_error_is_recorded(settings: Settings, make_repo) -> None:
    from marl_agents.parsing import RepoIndex

    settings.review.mode = "llm_only"
    settings.rag.enabled = False
    agent = BugDetectionAgent(_Broken(), settings=settings)
    repo = make_repo(REPO)
    found = agent.localize(repo, RepoIndex.build(repo), TEST)
    assert found.llm_failed and "server error" in found.errors[0]


def test_candidates_past_the_budget_are_not_shown(settings: Settings, make_repo) -> None:
    settings.bugs.max_prompt_chars = 120
    found, llm = localized(settings, make_repo, '{"ranking": []}')
    assert 0 < found.candidates_shown < found.candidates_considered
    assert "far_away" not in llm.calls[0][1].content


def test_retrieval_only_changes_configuration_d(settings: Settings, make_repo) -> None:
    from marl_agents.parsing import RepoIndex

    settings.review.mode = "full"
    settings.rag.enabled = True
    agent = BugDetectionAgent(MockLLMProvider(responses=['{"ranking": []}']), settings=settings)
    repo = make_repo(REPO)
    found = agent.localize(repo, RepoIndex.build(repo), "def test_far_away():\n    assert 1\n")
    assert "far_away" in {s.symbol for s in found.suspects}


def test_failing_test_option_localizes_then_reads_the_suspects(
    settings: Settings, make_repo
) -> None:
    agent, llm = make_agent(settings)
    assert llm is not None
    repo = make_repo({**REPO, "tests/test_cart.py": "from shop.cart import total\n\n\n" + TEST})
    request = AgentRequest(
        repo_path=str(repo.root), options={"failing_test": "tests/test_cart.py::test_total"}
    )
    result = agent.run(request)
    found = result.artifacts["localization"]
    assert found["suspects"][0]["symbol"] == "total"
    assert any("shop/cart.py" in call[1].content for call in llm.calls[1:])


def test_resolve_test(make_index) -> None:
    index = make_index({"tests/test_a.py": "class T:\n    def test_x(self):\n        pass\n"})
    source, path = resolve_test(index, "tests/test_a.py::T::test_x")
    assert path == "tests/test_a.py" and source.strip().startswith("def test_x")
    assert resolve_test(index, "assert f() == 1") == ("assert f() == 1", None)
    with pytest.raises(FailingTestError):
        resolve_test(index, "tests/missing.py::test_x")
    with pytest.raises(FailingTestError):
        resolve_test(index, "tests/test_a.py::test_missing")


def test_localization_reply_keeps_good_items() -> None:
    reply = LLMLocalization.model_validate({"ranking": ["F1", 7, {"ref": "[F2]", "reason": None}]})
    assert [r.ref for r in reply.ranking] == ["F1", "F2"] and reply.ranking[1].reason == ""
