"""Baseline comparison of the Code Review Agent's configurations, built from saved runs only.

from marl_agents.evaluation.comparison import build_summary, summary_md
md = summary_md(build_summary(PROJECT_ROOT / "experiments" / "results"))
"""

from marl_agents.evaluation.comparison.models import (
    DEFINITIONS,
    Column,
    ComparisonTable,
    EvaluationSummary,
    FairnessCheck,
    MetricDefinition,
    Row,
)
from marl_agents.evaluation.comparison.render import summary_md, table_md, tables_md
from marl_agents.evaluation.comparison.summary import build_group_tables, build_summary

__all__ = [
    "DEFINITIONS",
    "Column",
    "ComparisonTable",
    "EvaluationSummary",
    "FairnessCheck",
    "MetricDefinition",
    "Row",
    "build_group_tables",
    "build_summary",
    "summary_md",
    "table_md",
    "tables_md",
]
