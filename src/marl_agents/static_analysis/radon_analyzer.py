"""Radon complexity and maintainability metrics (in-process; radon only parses, never runs)."""

from __future__ import annotations

import logging
from collections.abc import Iterator
from typing import Any

from marl_agents.core.schemas import Category, FindingSource, Severity
from marl_agents.ingestion.models import FileKind, Repository
from marl_agents.parsing.repo_index import RepoIndex
from marl_agents.static_analysis.base import (
    AnalyzerOutput,
    Scope,
    StaticAnalyzer,
    make_finding,
    overlaps_scope,
)

logger = logging.getLogger(__name__)


def complexity_severity(cc: int) -> Severity | None:
    """Cyclomatic complexity thresholds (McCabe; radon ranks C=11-20, D=21-30, E/F>30)."""
    if cc <= 10:
        return None
    if cc <= 15:
        return Severity.LOW
    return Severity.MEDIUM


class RadonAnalyzer(StaticAnalyzer):
    name = "radon"

    def __init__(self, cc_threshold: int = 10, mi_threshold: float = 10.0) -> None:
        self.cc_threshold = cc_threshold
        self.mi_threshold = mi_threshold

    def analyze(
        self, repo: Repository, index: RepoIndex, files: list[str], scope: Scope | None = None
    ) -> AnalyzerOutput:
        out = AnalyzerOutput()
        try:
            from radon.complexity import cc_visit
            from radon.metrics import mi_visit
        except ImportError:
            out.skipped = True
            out.errors.append("radon is not installed; skipping complexity analysis")
            return out

        for rel in files:
            if not repo.has(rel) or repo.by_path[rel].kind is not FileKind.CODE:
                continue
            if repo.by_path[rel].language != "python":
                continue
            module = index.modules.get(rel)
            if module is None or module.syntax_error:
                continue
            source = repo.read_text(rel)
            try:
                blocks = cc_visit(source)
                # MI is a whole-module metric reported at line 1: skip it for diffs elsewhere.
                mi = (
                    float(mi_visit(source, multi=True))
                    if overlaps_scope(scope, rel, 1, 1)
                    else float("inf")
                )
            except (SyntaxError, ValueError, RecursionError) as exc:
                out.errors.append(f"radon failed on {rel}: {exc}")
                continue

            for block in _flatten(blocks):
                cc = int(block.complexity)
                severity = complexity_severity(cc) if cc > self.cc_threshold else None
                if severity is None:
                    continue
                name = (
                    f"{block.classname}.{block.name}"
                    if getattr(block, "classname", None)
                    else block.name
                )
                def_line = int(block.lineno)
                out.findings.append(
                    make_finding(
                        source=FindingSource.RADON,
                        file=rel,
                        start_line=def_line,
                        end_line=def_line,
                        category=Category.MAINTAINABILITY,
                        severity=severity,
                        title=f"High cyclomatic complexity in {name} ({cc})",
                        description=(
                            f"`{name}` has cyclomatic complexity {cc} (threshold "
                            f"{self.cc_threshold}), spanning lines {block.lineno}-{block.endline}. "
                            "Complex functions are harder to test and more defect-prone."
                        ),
                        confidence=0.9,
                        evidence=[f"cyclomatic complexity = {cc}"],
                        recommendation=(
                            "Split the function into smaller helpers, replace nested conditionals "
                            "with early returns or lookup tables."
                        ),
                        test_recommendation=(
                            f"Cover each of the {cc} independent paths; at minimum one test per "
                            "branch of the top-level conditionals."
                        ),
                        rule_id="RADON-CC",
                        symbol=name,
                    )
                )

            if mi < self.mi_threshold and module.line_count >= 50:
                out.findings.append(
                    make_finding(
                        source=FindingSource.RADON,
                        file=rel,
                        start_line=1,
                        end_line=1,
                        category=Category.MAINTAINABILITY,
                        severity=Severity.MEDIUM,
                        title=f"Low maintainability index ({mi:.1f})",
                        description=(
                            f"The module's maintainability index is {mi:.1f} (radon rank C, < "
                            f"{self.mi_threshold}); it combines size, complexity and "
                            "Halstead volume."
                        ),
                        confidence=0.7,
                        evidence=[f"maintainability index = {mi:.1f}"],
                        recommendation="Split the module by responsibility and reduce complexity.",
                        rule_id="RADON-MI",
                    )
                )
        return out


def _flatten(blocks: list[Any]) -> Iterator[Any]:
    """Radon returns classes with nested methods; yield functions/methods only."""
    for block in blocks:
        methods = getattr(block, "methods", None)
        if methods is not None:
            yield from methods
        else:
            yield block
