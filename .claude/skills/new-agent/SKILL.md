---
name: new-agent
description: Scaffold a new specialized agent (Bug Detection, Security, Test Generation, Documentation, or another) following the same modular contract as the Code Review Agent. Use when the user asks to start, create, or add an agent.
---

# Scaffold a new agent

Agents are plain Python classes implementing `marl_agents.agents.base.BaseAgent`. LangGraph wraps them later;
they must never import LangGraph themselves.

## Steps

1. **Confirm scope.** Which agent, which input types (snippet / repo / diff), which finding categories,
   which eval dataset and metrics (see the table in CLAUDE.md). Ask if anything is ambiguous.
2. **Read the reference implementation first**: `src/marl_agents/agents/base.py`, `src/marl_agents/core/schemas.py`,
   and `src/marl_agents/agents/code_review/` (the most complete agent). Reuse its pipeline pieces
   (ingestion, parsing, rag, static_analysis, findings) — do not copy-paste them into the new agent.
3. **Create the package** `src/marl_agents/agents/<agent_name>/`:
   ```
   __init__.py        exports the agent class
   agent.py           class <Name>Agent(BaseAgent): name = "<agent_name>"; run(request) -> AgentResult
   prompts/           versioned prompt files (system.md, analyze.md) with a `version:` header
   config.py          agent-specific settings model (optional)
   ```
4. **Output contract.** Emit `core.schemas.Finding` objects (add a new `Category` value only if truly needed,
   and update `docs/severity-rubric.md`). Artifacts that are not findings (generated tests, docstrings) go in
   `AgentResult.artifacts` with a typed model added to `core/schemas.py`.
5. **Dependencies by injection**: constructor takes `llm: LLMProvider`, `retriever: Retriever | None`
   (None = RAG disabled, needed for experiment config B), and any static analyzers.
6. **Register** the agent in `src/marl_agents/agents/__init__.py` (`AGENT_REGISTRY`).
7. **Tests** in `tests/unit/agents/test_<agent_name>.py` using `MockLLMProvider` with canned JSON responses:
   happy path, malformed LLM output, finding rejected by validation, RAG disabled.
8. **Evaluation hook**: add a stub runner in `src/marl_agents/evaluation/runners/<agent_name>.py` and
   point to `/add-dataset-loader` if the dataset loader doesn't exist yet.
9. Log the decision in `docs/decisions.md` if the agent introduced a new pattern.
10. Run `ruff check . --fix && ruff format . && pytest tests/unit -q` and report results.
