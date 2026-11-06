"""Ruff, Radon, custom AST checks, secret scanning and test gaps -> core.schemas.Finding."""

from marl_agents.static_analysis.ast_checks import (
    AstChecksAnalyzer,
    SecretsAnalyzer,
    TestGapAnalyzer,
)
from marl_agents.static_analysis.base import AnalyzerOutput, Scope, StaticAnalyzer, overlaps_scope
from marl_agents.static_analysis.radon_analyzer import RadonAnalyzer
from marl_agents.static_analysis.ruff_analyzer import RuffAnalyzer


def default_analyzers() -> list[StaticAnalyzer]:
    return [
        RuffAnalyzer(),
        RadonAnalyzer(),
        AstChecksAnalyzer(),
        SecretsAnalyzer(),
        TestGapAnalyzer(),
    ]


__all__ = [
    "AnalyzerOutput",
    "AstChecksAnalyzer",
    "RadonAnalyzer",
    "RuffAnalyzer",
    "Scope",
    "SecretsAnalyzer",
    "StaticAnalyzer",
    "TestGapAnalyzer",
    "default_analyzers",
    "overlaps_scope",
]
