"""LangGraph-ready adapter. Plain function over a dict state; no LangGraph import here."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from marl_agents.agents.bug_detection.agent import BugDetectionAgent
from marl_agents.core.schemas import AgentRequest

State = dict[str, Any]


def make_bug_detection_node(agent: BugDetectionAgent) -> Callable[[State], State]:
    def node(state: State) -> State:
        request = state.get("request")
        if not isinstance(request, AgentRequest):
            request = AgentRequest.model_validate(request)
        return {"bug_detection_result": agent.run(request)}

    return node
