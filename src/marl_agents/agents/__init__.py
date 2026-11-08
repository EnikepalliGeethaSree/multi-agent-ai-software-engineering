"""Specialized agents. Each is standalone: `Agent(llm=...).run(AgentRequest) -> AgentResult`."""

from importlib import import_module

from marl_agents.agents.base import BaseAgent

# name -> "module:Class"; imported lazily so optional dependencies stay optional.
AGENT_REGISTRY: dict[str, str] = {
    "code_review": "marl_agents.agents.code_review.agent:CodeReviewAgent",
    "bug_detection": "marl_agents.agents.bug_detection.agent:BugDetectionAgent",
}


def get_agent_class(name: str) -> type[BaseAgent]:
    module_name, _, cls_name = AGENT_REGISTRY[name].partition(":")
    cls: type[BaseAgent] = getattr(import_module(module_name), cls_name)
    return cls


__all__ = ["AGENT_REGISTRY", "BaseAgent", "get_agent_class"]
