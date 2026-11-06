"""Contract every specialized agent implements. Agents never import LangGraph."""

from __future__ import annotations

from abc import ABC, abstractmethod

from marl_agents.core.schemas import AgentRequest, AgentResult
from marl_agents.llm.base import LLMProvider


class BaseAgent(ABC):
    """A standalone, dependency-injected agent: `agent.run(request) -> AgentResult`."""

    name: str = "base"

    def __init__(self, llm: LLMProvider) -> None:
        self.llm = llm

    @abstractmethod
    def run(self, request: AgentRequest) -> AgentResult:
        """Analyze the request and return structured, validated results."""
