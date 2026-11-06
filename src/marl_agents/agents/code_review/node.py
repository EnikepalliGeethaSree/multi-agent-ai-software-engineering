"""LangGraph-ready adapter. Plain function over a dict state; no LangGraph import here.

Usage later: `graph.add_node("code_review", make_code_review_node(agent))`.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from marl_agents.agents.code_review.agent import CodeReviewAgent
from marl_agents.core.schemas import AgentRequest

State = dict[str, Any]


def make_code_review_node(agent: CodeReviewAgent) -> Callable[[State], State]:
    def node(state: State) -> State:
        request = state.get("request")
        if not isinstance(request, AgentRequest):
            request = AgentRequest.model_validate(request)
        result = agent.run(request)
        return {"code_review_result": result}

    return node
