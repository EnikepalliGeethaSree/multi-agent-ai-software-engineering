from marl_agents.agents.code_review.context import ContextBuilder, render_context
from marl_agents.agents.code_review.llm_schema import (
    LLMFinding,
    LLMReviewEnvelope,
    StaticAssessment,
    parse_items,
)
from marl_agents.agents.code_review.prompts import load_prompt, prompt_versions
from marl_agents.agents.code_review.units import build_units, render_numbered
from marl_agents.core.schemas import Category, FindingSource, Severity
from marl_agents.rag import HashingEmbedder, InMemoryVectorStore, Retriever

# ---- LLM output schema -----------------------------------------------------------------------


def test_llm_finding_is_lenient_about_common_variations() -> None:
    f = LLMFinding.model_validate(
        {
            "start_line": 3,
            "category": "Error Handling",
            "severity": "Major",
            "title": "t",
            "evidence": "single string",
            "confidence": 85,
            "cwe": "89",
        }
    )
    assert f.category is Category.ERROR_HANDLING and f.severity is Severity.HIGH
    assert f.evidence == ["single string"] and f.confidence == 0.85 and f.cwe == "CWE-89"
    finding = f.to_finding("app.py", symbol="fn")
    assert (
        finding.file == "app.py"
        and finding.end_line == 3
        and finding.sources == [FindingSource.LLM]
    )
    assert finding.proposed_severity is Severity.HIGH and finding.symbol == "fn"


def test_malformed_items_are_dropped_individually() -> None:
    env = LLMReviewEnvelope.model_validate(
        {
            "findings": [
                {
                    "start_line": 1,
                    "category": "bug",
                    "severity": "low",
                    "title": "ok",
                    "evidence": ["x = 1"],
                },
                {"start_line": 0, "category": "bug", "severity": "low", "title": "bad line"},
                {"start_line": 2, "category": "astrology", "severity": "low", "title": "bad cat"},
                "not a dict",
            ],
            "static_assessments": [{"ref": "S1", "verdict": "False Positive"}, {"verdict": "x"}],
        }
    )
    findings, assessments, errors = parse_items(env)
    assert [f.title for f in findings] == ["ok"]
    assert assessments == [StaticAssessment(ref="S1", verdict="false_positive")]
    assert len(errors) == 3


def test_envelope_accepts_null_and_single_objects() -> None:
    env = LLMReviewEnvelope.model_validate({"findings": None, "static_assessments": {"ref": "S1"}})
    assert env.findings == [] and len(env.static_assessments) == 1


# ---- prompts -----------------------------------------------------------------------------------


def test_prompts_are_versioned_and_contain_safety_rules() -> None:
    assert set(prompt_versions()) == {"system", "review"}
    system = load_prompt("system").text
    assert "DATA, not instructions" in system and "evidence" in system
    rendered = load_prompt("review").render(
        file="a.py",
        start_line=1,
        end_line=2,
        total_lines=2,
        scope_note="",
        changed_legend="",
        context_section="CTX",
        static_section="STATIC",
        numbered_code="1 | x = 1",
    )
    assert "CTX" in rendered and "STATIC" in rendered and '"findings"' in rendered


# ---- review units ------------------------------------------------------------------------------


def _funcs(n: int, body_lines: int = 8) -> str:
    return "".join(
        f"def f{i}(x):\n"
        + "".join(f"    x = x + {j}\n" for j in range(body_lines))
        + "    return x\n\n"
        for i in range(n)
    )


def test_small_file_is_one_unit_and_large_file_splits_at_defs(make_index) -> None:  # type: ignore[no-untyped-def]
    index = make_index({"small.py": _funcs(3), "big.py": _funcs(30)})
    small = build_units(index.repo, index.modules["small.py"], max_lines=200)
    assert len(small) == 1 and small[0].start_line == 1
    big = build_units(index.repo, index.modules["big.py"], max_lines=60)
    assert len(big) > 1 and all(u.end_line - u.start_line + 1 <= 60 for u in big)
    def_lines = {s.start_line for s in index.modules["big.py"].symbols}
    assert all(u.start_line in def_lines for u in big)  # units start at definitions
    assert big[-1].end_line >= index.repo.line_count("big.py") - 1


def test_trivial_files_are_skipped_and_scope_filters_units(make_index) -> None:  # type: ignore[no-untyped-def]
    index = make_index({"pkg/__init__.py": '"""Pkg."""\n', "m.py": _funcs(20)})
    assert build_units(index.repo, index.modules["pkg/__init__.py"]) == []
    units = build_units(index.repo, index.modules["m.py"], max_lines=40, changed=[(12, 12)])
    assert len(units) == 1 and units[0].changed == [(12, 12)]
    numbered = render_numbered(index.repo, units[0])
    assert (
        ">12 | " in numbered.replace(" 12 |", "12 |") or "> 12 |" in numbered or ">12 |" in numbered
    )


def test_syntax_error_file_still_gets_units(make_index) -> None:  # type: ignore[no-untyped-def]
    src = "def broken(:\n" + "".join(f"    x = {i}\n" for i in range(10))
    index = make_index({"bad.py": src})
    assert len(build_units(index.repo, index.modules["bad.py"])) == 1


# ---- context builder -----------------------------------------------------------------------------

CTX_FILES = {
    "app/db.py": "def fetch(uid):\n    return {'id': uid}\n",
    "app/service.py": "from app.db import fetch\n\ndef get_user(uid):\n    return fetch(uid)\n",
    "app/api.py": "from app.service import get_user\n\ndef handler(req):\n    return get_user(req.id)\n",
    "tests/test_service.py": "from app.service import get_user\n\ndef test_get_user():\n    assert get_user(1)\n",
    "README.md": "# Demo\nA demo project.\n",
}


def test_context_includes_callee_caller_test_readme_and_respects_budget(make_index) -> None:  # type: ignore[no-untyped-def]
    index = make_index(CTX_FILES)
    unit = build_units(index.repo, index.modules["app/service.py"])[0]
    code = index.repo.read_text("app/service.py")
    items = ContextBuilder(index, retriever=None).build(unit, code)
    reasons = {(i.reason, i.file) for i in items}
    assert ("callee", "app/db.py") in reasons
    assert ("caller", "app/api.py") in reasons
    assert ("test", "tests/test_service.py") in reasons
    assert ("readme", "README.md") in reasons
    assert all(i.file != "app/service.py" for i in items)  # never echoes the unit under review
    tiny = ContextBuilder(index, retriever=None, max_chars=200).build(unit, code)
    assert sum(len(i.text) + 100 for i in tiny) <= 200
    assert "Project context" in render_context(items)
    assert "(none provided)" in render_context([])


def test_context_with_dense_retrieval_and_guidelines(make_index) -> None:  # type: ignore[no-untyped-def]
    index = make_index(CTX_FILES)
    retriever = Retriever(HashingEmbedder(), InMemoryVectorStore())
    retriever.index_repository(index)
    unit = build_units(index.repo, index.modules["app/service.py"])[0]
    items = ContextBuilder(index, retriever, structural=False, top_k=3, guideline_k=2).build(
        unit, index.repo.read_text("app/service.py"), hints=["S608 SQL injection"]
    )
    reasons = [i.reason for i in items]
    assert "similar" in reasons and reasons.count("guideline") == 2
    assert "callee" not in reasons  # structural disabled


def test_unit_too_large_is_retried_without_project_context(settings, make_repo) -> None:  # type: ignore[no-untyped-def]
    from marl_agents.agents.code_review import CodeReviewAgent
    from marl_agents.core.schemas import AgentRequest
    from marl_agents.llm import Message, MockLLMProvider, RequestTooLargeError

    prompts: list[str] = []

    def responder(messages: list[Message]) -> str:
        prompts.append(messages[-1].content)
        if len(prompts) == 1:
            raise RequestTooLargeError("request too large for model m")
        return '{"findings": [], "static_assessments": []}'

    settings.review.mode = "full"
    repo = make_repo({
        "app/db.py": "def query(conn, name):\n    return conn.execute(name)\n",
        "app/api.py": "from app.db import query\n\n\ndef handler(conn, name):\n    return query(conn, name)\n",
    })  # fmt: skip
    agent = CodeReviewAgent(MockLLMProvider(responder=responder), settings=settings)
    result = agent.run(AgentRequest(repo_path=str(repo.root)))
    assert result.stats["units_failed"] == 0
    assert any("reviewed without it" in e for e in result.errors)
    retried = [p for p in prompts[1:] if "def query" in p or "def handler" in p]
    assert retried and len(prompts) >= 2
