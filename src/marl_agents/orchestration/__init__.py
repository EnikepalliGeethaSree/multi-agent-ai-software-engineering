"""LangGraph orchestration of the standalone agents (Part 5): two agents in parallel + aggregator.

Agents never import this package; it wraps them. LangGraph is imported only inside `build_graph`.
"""

from marl_agents.orchestration.aggregator import AggregatedFinding, Aggregation, aggregate

__all__ = ["AggregatedFinding", "Aggregation", "aggregate"]
