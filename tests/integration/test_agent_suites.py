"""Behaviour suites for both agents, on small synthetic files.

Each case checks what was found and how it is described: category, location, severity, confidence,
evidence and a suggested fix. Static cases run the real analyzers; LLM cases use the mock provider
or a fake Ollama server, so nothing calls a paid or rate-limited API.

These fixtures show the agents behave as designed on controlled input. They do not show how well
the agents generalise to real projects; the benchmarks in docs/results.md measure that.
"""

from __future__ import annotations

import json
import urllib.error
from typing import Any

import pytest

from marl_agents.agents.bug_detection import BugDetectionAgent
from marl_agents.agents.code_review.agent import CodeReviewAgent
from marl_agents.config import Settings
from marl_agents.core.schemas import (
    AgentRequest,
    Category,
    EvidenceBasis,
    Finding,
    FindingSource,
    ReviewResult,
    Severity,
)
from marl_agents.llm import Message, MockLLMProvider
from marl_agents.llm.base import GenerationConfig, LLMError, LLMResponse
from marl_agents.llm.ollama import OllamaProvider
from marl_agents.static_analysis.base import AnalyzerOutput, StaticAnalyzer
from tests.conftest import llm_json

# ---- helpers ------------------------------------------------------------------------------------


def run(agent_cls: type, settings: Settings, code: str, llm: Any = None, **kw: Any) -> ReviewResult:
    agent = agent_cls(llm, settings=settings, **kw)
    return agent.run(AgentRequest(snippet=code, snippet_filename="sample.py"))


def static(settings: Settings, agent_cls: type, code: str) -> ReviewResult:
    settings.review.mode = "static_only"
    return run(agent_cls, settings, code)


def by_rule(result: ReviewResult, rule: str) -> list[Finding]:
    return [f for f in result.findings if f.rule_id == rule or f"rule:{rule}" in f.notes]


def line_of(code: str, text: str) -> int:
    return next(i for i, ln in enumerate(code.splitlines(), start=1) if text in ln)


def well_formed(f: Finding, code: str) -> None:
    """Every finding: real location, evidence from those lines, a fix, a valid confidence."""
    lines = code.splitlines()
    assert 1 <= f.start_line <= f.end_line <= len(lines)
    assert f.evidence, f.title
    assert f.recommendation, f.title
    assert 0.0 <= f.confidence <= 1.0
    assert f.snippet and f.snippet.splitlines()[0] == lines[f.start_line - 1]
    assert f.evidence_basis is not None


def expect(
    result: ReviewResult, rule: str, code: str, text: str, category: Category,
    min_severity: Severity = Severity.LOW,
) -> Finding:  # fmt: skip
    hits = by_rule(result, rule)
    assert hits, f"{rule} not reported; got {[f.rule_id for f in result.findings]}"
    f = hits[0]
    assert f.start_line <= line_of(code, text) <= f.end_line, (rule, f.start_line)
    assert f.category is category, (rule, f.category)
    assert f.severity.rank >= min_severity.rank, (rule, f.severity)
    well_formed(f, code)
    return f


def llm_finding(code: str, text: str, **over: Any) -> dict[str, Any]:
    line = line_of(code, text)
    base = {
        "file": "sample.py", "start_line": line, "end_line": line, "category": "bug",
        "severity": "high", "title": "Problem",
        "description": "This line fails for some inputs the caller can pass in.",
        "evidence": [text], "recommendation": "Guard the failing case before this line runs.",
        "confidence": 0.8,
    }  # fmt: skip
    return {**base, **over}


class Raising(MockLLMProvider):
    def __init__(self, error: Exception, name: str = "mock") -> None:
        super().__init__()
        self.error = error
        self.name = name

    def generate(
        self, messages: list[Message], config: GenerationConfig | None = None
    ) -> LLMResponse:
        raise self.error


class BrokenAnalyzer(StaticAnalyzer):
    name = "broken"

    def analyze(self, repo, index, files, scope=None) -> AnalyzerOutput:  # type: ignore[no-untyped-def]
        raise RuntimeError("tool crashed")


def degraded_gracefully(result: ReviewResult, code: str, rule: str) -> None:
    """A failed LLM call leaves a partial review that still reports the static findings."""
    assert result.stats["units_failed"] >= 1
    assert result.stats.get("review_status") == "partial"
    assert by_rule(result, rule), "static findings must survive an LLM failure"
    assert any("LLM review failed" in e for e in result.errors)


CLEAN = '''"""Order totals."""


def order_total(prices: list[float], discount: float = 0.0) -> float:
    """Sum of prices after a discount between 0 and 1."""
    if not prices:
        return 0.0
    return sum(prices) * (1.0 - discount)
'''

COMPLEX = (
    "def route(a, b, c, d):\n"
    + "".join(f"    if a == {i}:\n        return {i}\n" for i in range(14))
    + "    return -1\n"
)

DUPLICATE = """def sum_over(items, limit):
    total = 0
    for item in items:
        if item > limit:
            total += item
    count = len(items) or 1
    return total / count


def add_above(values, threshold):
    acc = 0
    for value in values:
        if value > threshold:
            acc += value
    count = len(values) or 1
    return acc / count
"""

NAMING = (
    "class order_service:\n    def computeTotal(self, itemList):\n        return sum(itemList)\n"
)
LONG = (
    "def long_function(x):\n"
    + "".join(f"    y{i} = x + {i}\n" for i in range(85))
    + "    return y0\n"
)
NESTED = """def nested(xs):
    for a in xs:
        if a:
            for b in a:
                if b:
                    while b:
                        b -= 1
    return xs
"""
SWALLOW = """def load(path):
    try:
        return open(path).read()
    except Exception:
        pass
"""


# ---- Code Review Agent --------------------------------------------------------------------------


class TestCodeReview:
    def test_clean_code_has_no_real_problems(self, settings: Settings) -> None:
        result = static(settings, CodeReviewAgent, CLEAN)
        serious = [f for f in result.findings if f.severity.rank >= Severity.MEDIUM.rank]
        assert serious == [], [f.title for f in serious]
        assert not [f for f in result.findings if f.category in (Category.BUG, Category.SECURITY)]

    def test_high_cyclomatic_complexity(self, settings: Settings) -> None:
        expect(static(settings, CodeReviewAgent, COMPLEX), "RADON-CC", COMPLEX, "def route",
               Category.MAINTAINABILITY)  # fmt: skip

    def test_duplicated_functions(self, settings: Settings) -> None:
        f = expect(static(settings, CodeReviewAgent, DUPLICATE), "AST-DUPLICATE-FUNCTION",
                   DUPLICATE, "def add_above", Category.MAINTAINABILITY)  # fmt: skip
        assert "sum_over" in f.title and f.evidence_basis is EvidenceBasis.STATIC_CONFIRMED

    def test_poor_naming(self, settings: Settings) -> None:
        result = static(settings, CodeReviewAgent, NAMING)
        titles = {f.title for f in by_rule(result, "AST-NAMING")}
        assert titles == {
            "Naming: class `order_service`",
            "Naming: function `computeTotal`, argument `itemList`",
        }
        expect(result, "AST-NAMING", NAMING, "class order_service", Category.STANDARDS)

    def test_long_function(self, settings: Settings) -> None:
        expect(static(settings, CodeReviewAgent, LONG), "AST-LONG-FUNCTION", LONG,
               "def long_function", Category.MAINTAINABILITY)  # fmt: skip

    def test_code_smell_deep_nesting(self, settings: Settings) -> None:
        expect(static(settings, CodeReviewAgent, NESTED), "AST-DEEP-NESTING", NESTED, "def nested",
               Category.MAINTAINABILITY)  # fmt: skip

    def test_missing_error_handling(self, settings: Settings) -> None:
        expect(static(settings, CodeReviewAgent, SWALLOW), "AST-SWALLOWED-EXCEPTION", SWALLOW,
               "except Exception", Category.ERROR_HANDLING, Severity.MEDIUM)  # fmt: skip

    def test_a_failing_static_tool_does_not_stop_the_review(self, settings: Settings) -> None:
        settings.review.mode = "static_only"
        from marl_agents.static_analysis import default_analyzers

        result = run(CodeReviewAgent, settings, SWALLOW,
                     analyzers=[BrokenAnalyzer(), *default_analyzers()])  # fmt: skip
        assert by_rule(result, "AST-SWALLOWED-EXCEPTION")
        assert any("broken" in e for e in result.errors)
        assert result.stats["review_status"] == "partial"
        assert result.stats["analyzers_failed"] == ["broken"]

    def test_rag_context_cited_by_the_llm_is_verified(self, settings: Settings) -> None:
        settings.review.suggest_fixes = False
        code = DUPLICATE
        reply = llm_json([llm_finding(code, "return acc / count", category="maintainability",
                                      severity="low", context_refs=["C1", "C99"])])  # fmt: skip
        llm = MockLLMProvider(default=reply)
        result = run(CodeReviewAgent, settings, code, llm, analyzers=[])
        prompt = llm.calls[0][-1].content
        assert "### C1 [" in prompt and "context_refs" in prompt
        f = next(f for f in result.findings if FindingSource.LLM in f.sources)
        assert len(f.context_refs) == 1 and f.evidence_basis is EvidenceBasis.LLM_WITH_CONTEXT
        assert result.stats["context_refs_cited"] == 1
        assert result.stats["context_refs_invalid"] == 1  # C99 was never shown

    def test_invalid_llm_output_is_rejected_not_reported(self, settings: Settings) -> None:
        settings.review.suggest_fixes = False
        llm = MockLLMProvider(default="this is not json")
        degraded_gracefully(run(CodeReviewAgent, settings, SWALLOW, llm), SWALLOW,
                            "AST-SWALLOWED-EXCEPTION")  # fmt: skip

    def test_duplicate_findings_are_merged(self, settings: Settings) -> None:
        settings.review.suggest_fixes = False
        reply = llm_json([llm_finding(SWALLOW, "except Exception:", category="error_handling",
                                      severity="medium", title="Exception swallowed")])  # fmt: skip
        result = run(CodeReviewAgent, settings, SWALLOW, MockLLMProvider(default=reply))
        at_line = [f for f in result.findings if f.start_line == line_of(SWALLOW, "except")]
        assert len(at_line) == 1
        # Ruff (BLE001) and the AST check both flag the line; the LLM finding merges into them.
        assert FindingSource.LLM in at_line[0].sources
        assert set(at_line[0].sources) & {FindingSource.AST, FindingSource.RUFF}
        assert at_line[0].evidence_basis is EvidenceBasis.STATIC_CONFIRMED

    def test_wrong_line_numbers_are_repaired_or_rejected(self, settings: Settings) -> None:
        settings.review.suggest_fixes = False
        code = CLEAN
        moved = llm_finding(code, "return sum(prices) * (1.0 - discount)", start_line=1,
                            end_line=1, title="Moved")  # fmt: skip
        invented = llm_finding(code, "return sum(prices)", evidence=["os.system(cmd)"],
                               title="Invented")  # fmt: skip
        result = run(CodeReviewAgent, settings, code,
                     MockLLMProvider(default=llm_json([moved, invented])), analyzers=[])  # fmt: skip
        titles = {f.title: f for f in result.findings}
        assert "Invented" not in titles
        assert titles["Moved"].start_line == line_of(code, "return sum(prices)")
        assert result.stats["llm_rejected_by_reason"].get("evidence_not_found") == 1

    def test_provider_timeout(self, settings: Settings) -> None:
        settings.review.suggest_fixes = False
        llm = Raising(LLMError("request timed out after 120s"))
        degraded_gracefully(run(CodeReviewAgent, settings, SWALLOW, llm), SWALLOW,
                            "AST-SWALLOWED-EXCEPTION")  # fmt: skip

    def test_ollama_unavailable(self, settings: Settings) -> None:
        settings.review.suggest_fixes = False

        def refused(*_a: Any, **_k: Any) -> Any:
            raise urllib.error.URLError(ConnectionRefusedError(10061, "refused"))

        llm = OllamaProvider(opener=refused)
        result = run(CodeReviewAgent, settings, SWALLOW, llm)
        degraded_gracefully(result, SWALLOW, "AST-SWALLOWED-EXCEPTION")
        assert any("Cannot reach Ollama" in e for e in result.errors)

    def test_gemini_unavailable(self, settings: Settings) -> None:
        settings.review.suggest_fixes = False
        llm = Raising(LLMError("gemini request rejected (503): overloaded"), name="gemini")
        degraded_gracefully(run(CodeReviewAgent, settings, SWALLOW, llm), SWALLOW,
                            "AST-SWALLOWED-EXCEPTION")  # fmt: skip


# ---- Bug Detection Agent ------------------------------------------------------------------------

DIV = "def mean(values):\n    total = sum(values)\n    return total / len(values)\n"
UNDEFINED = "def area(r):\n    return PI * r * r\n"
OFF_BY_ONE = "def last_items(xs):\n    out = []\n    for i in range(len(xs) + 1):\n        out.append(xs[i])\n    return out\n"
CONDITION = "def is_one(x):\n    if x is 1:\n        return True\n    return False\n"
MISSING_RETURN = (
    "def sign(x):\n    if x > 0:\n        return 1\n    elif x < 0:\n        return -1\n"
)
NONE_DEREF = (
    "import re\n\n\ndef year(text):\n    m = re.match(r'(\\d+)', text)\n    return m.group(1)\n"
)
LOOP = "def wait(done):\n    while not done:\n        print('waiting')\n"
SYNTAX = "def broken(:\n    return 1\n"
WRONG_CALL = "def area(w, h):\n    return w * h\n\n\ndef total():\n    return area(3)\n"


class TestBugDetection:
    def test_clean_code_has_no_bugs(self, settings: Settings) -> None:
        assert static(settings, BugDetectionAgent, CLEAN).findings == []

    @pytest.mark.parametrize(
        ("code", "rule", "text", "category"),
        [
            (DIV, "BUG-DIV-BY-LEN", "total / len(values)", Category.EDGE_CASE),
            (UNDEFINED, "F821", "PI * r", Category.BUG),
            (OFF_BY_ONE, "BUG-OFF-BY-ONE", "out.append(xs[i])", Category.BUG),
            (CONDITION, "F632", "x is 1", Category.BUG),
            (MISSING_RETURN, "BUG-MISSING-RETURN", "def sign", Category.BUG),
            (NONE_DEREF, "BUG-NONE-DEREF", "m.group(1)", Category.BUG),
            (SWALLOW, "AST-SWALLOWED-EXCEPTION", "except Exception", Category.ERROR_HANDLING),
            (LOOP, "BUG-INFINITE-LOOP", "while not done", Category.BUG),
        ],
        ids=["division_by_zero", "undefined_variable", "index_out_of_range",
             "incorrect_condition", "missing_return", "none_dereference",
             "incorrect_exception_handling", "infinite_loop"],
    )  # fmt: skip
    def test_static_defects(
        self, settings: Settings, code: str, rule: str, text: str, category: Category
    ) -> None:
        f = expect(static(settings, BugDetectionAgent, code), rule, code, text, category)
        assert f.bug is not None and f.bug.root_cause
        assert f.evidence_basis is EvidenceBasis.STATIC_CONFIRMED
        assert f.id.startswith("BD-")

    def test_syntax_error(self, settings: Settings) -> None:
        result = static(settings, BugDetectionAgent, SYNTAX)
        f = next(
            f
            for f in result.findings
            if f.rule_id and f.rule_id.startswith(("E9", "SyntaxError", "invalid"))
        )
        assert f.start_line == 1 and f.severity.rank >= Severity.HIGH.rank

    def test_incorrect_function_arguments_inferred_by_the_llm(self, settings: Settings) -> None:
        settings.review.suggest_fixes = False
        bug = llm_finding(WRONG_CALL, "return area(3)", title="area() called with one argument",
                          bug_type="logic", root_cause="area needs w and h", trigger="calling total()",
                          expected="a number", actual="TypeError",
                          fix_explanation="passing both sides gives area its second argument",
                          involved_names=["area"])  # fmt: skip
        result = run(
            BugDetectionAgent, settings, WRONG_CALL, MockLLMProvider(default=llm_json([bug]))
        )
        f = next(f for f in result.findings if FindingSource.LLM in f.sources)
        assert f.start_line == line_of(WRONG_CALL, "return area(3)")
        assert f.bug is not None and f.bug.trigger and f.bug.fix_explanation
        assert f.evidence_basis is EvidenceBasis.LLM_INFERRED
        well_formed(f, WRONG_CALL)

    def test_duplicate_findings_are_merged(self, settings: Settings) -> None:
        settings.review.suggest_fixes = False
        bug = llm_finding(DIV, "return total / len(values)", title="Divides by zero for []",
                          root_cause="empty list", trigger="mean([])",
                          involved_names=["values"])  # fmt: skip
        result = run(BugDetectionAgent, settings, DIV, MockLLMProvider(default=llm_json([bug])))
        at = [f for f in result.findings if f.start_line == 3]
        assert len(at) == 1 and FindingSource.LLM in at[0].sources

    def test_invalid_line_numbers(self, settings: Settings) -> None:
        settings.review.suggest_fixes = False
        bad = llm_finding(DIV, "return total / len(values)", start_line=99, end_line=99,
                          evidence=["return values[0]"], title="Invented",
                          involved_names=["values"])  # fmt: skip
        result = run(BugDetectionAgent, settings, DIV, MockLLMProvider(default=llm_json([bad])))
        assert all(f.title != "Invented" for f in result.findings)

    def test_llm_timeout(self, settings: Settings) -> None:
        settings.review.suggest_fixes = False
        result = run(BugDetectionAgent, settings, DIV, Raising(LLMError("timed out")))
        degraded_gracefully(result, DIV, "BUG-DIV-BY-LEN")

    def test_rag_retrieval_failure(
        self, settings: Settings, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        settings.review.suggest_fixes = False
        from marl_agents.rag.retriever import Retriever

        def boom(*_a: Any, **_k: Any) -> Any:
            raise RuntimeError("vector store unavailable")

        monkeypatch.setattr(Retriever, "retrieve", boom)
        monkeypatch.setattr(Retriever, "retrieve_guidelines", boom)
        result = run(BugDetectionAgent, settings, DIV, MockLLMProvider(default=llm_json()))
        assert result.stats["rag_errors"] >= 1
        assert any("retrieval of" in e for e in result.errors)
        assert by_rule(result, "BUG-DIV-BY-LEN")
        assert result.stats["units_failed"] == 0


def test_the_two_agents_keep_their_findings_apart(settings: Settings) -> None:
    review = static(settings, CodeReviewAgent, NAMING + "\n\n" + DIV)
    bugs = static(settings, BugDetectionAgent, NAMING + "\n\n" + DIV)
    assert all(f.id.startswith("CR-") for f in review.findings)
    assert all(f.id.startswith("BD-") for f in bugs.findings)
    assert not by_rule(bugs, "AST-NAMING")  # style is not a bug
    assert all(f.category in (Category.BUG, Category.ERROR_HANDLING, Category.EDGE_CASE,
                              Category.SECURITY) for f in bugs.findings)  # fmt: skip


def test_each_agent_retrieves_its_own_guidance(make_index: Any) -> None:
    from marl_agents.agents.code_review.agent import CodeReviewAgent as CR
    from marl_agents.rag import create_embedder
    from marl_agents.rag.retriever import Retriever
    from marl_agents.rag.store import InMemoryVectorStore

    retriever = Retriever(create_embedder("hashing"), InMemoryVectorStore())
    retriever.index_repository(make_index({"a.py": DIV}))
    query = "division by zero when the list is empty; naming and duplicated code"
    bug_files = {h.chunk.file.rsplit("/", 1)[-1]
                 for h in retriever.retrieve_guidelines(query, k=5, files=BugDetectionAgent.GUIDELINE_FILES)}  # fmt: skip
    review_files = {h.chunk.file.rsplit("/", 1)[-1]
                    for h in retriever.retrieve_guidelines(query, k=5, files=CR.GUIDELINE_FILES)}  # fmt: skip
    assert bug_files and bug_files <= BugDetectionAgent.GUIDELINE_FILES
    assert review_files and review_files <= CR.GUIDELINE_FILES
    assert "bug_patterns.md" not in review_files and "review_examples.md" not in bug_files


def test_prompt_versions_are_recorded(settings: Settings) -> None:
    from marl_agents.agents.bug_detection.prompts import prompt_versions as bug_versions
    from marl_agents.agents.code_review.prompts import prompt_versions

    assert prompt_versions()["review"] == "1.1" and bug_versions()["bug_review"] == "1.1"
    assert json.dumps(prompt_versions())
