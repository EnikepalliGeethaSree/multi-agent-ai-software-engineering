"""Ruff, Radon, custom AST checks, secret scanning and test gaps -> core.schemas.Finding."""

from marl_agents.static_analysis.ast_checks import (
    AstChecksAnalyzer,
    SecretsAnalyzer,
    TestGapAnalyzer,
)
from marl_agents.static_analysis.base import AnalyzerOutput, Scope, StaticAnalyzer, overlaps_scope
from marl_agents.static_analysis.design_checks import DesignChecksAnalyzer
from marl_agents.static_analysis.flow_checks import FlowAnalyzer
from marl_agents.static_analysis.loop_checks import LoopAnalyzer
from marl_agents.static_analysis.radon_analyzer import RadonAnalyzer
from marl_agents.static_analysis.ruff_analyzer import RuffAnalyzer


def default_analyzers() -> list[StaticAnalyzer]:
    return [
        RuffAnalyzer(),
        RadonAnalyzer(),
        AstChecksAnalyzer(),
        DesignChecksAnalyzer(),
        SecretsAnalyzer(),
        TestGapAnalyzer(),
    ]


def bug_analyzers() -> list[StaticAnalyzer]:
    """Analyzers that can see defects. Radon, secrets and test gaps report other things."""
    return [RuffAnalyzer(), AstChecksAnalyzer(), FlowAnalyzer(), LoopAnalyzer()]


__all__ = [
    "AnalyzerOutput",
    "AstChecksAnalyzer",
    "DesignChecksAnalyzer",
    "FlowAnalyzer",
    "LoopAnalyzer",
    "RadonAnalyzer",
    "RuffAnalyzer",
    "Scope",
    "SecretsAnalyzer",
    "StaticAnalyzer",
    "TestGapAnalyzer",
    "bug_analyzers",
    "default_analyzers",
    "overlaps_scope",
]
