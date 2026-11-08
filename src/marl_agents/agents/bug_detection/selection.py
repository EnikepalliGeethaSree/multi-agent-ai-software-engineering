"""Choose which review units get an LLM call when a scan cannot afford all of them.

The score only orders work. A unit that is not chosen still has its static findings, and the report
says how much code the LLM did not read.
"""

from __future__ import annotations

import re

from pydantic import BaseModel

from marl_agents.agents.code_review.units import ReviewUnit
from marl_agents.core.schemas import Finding
from marl_agents.ingestion.models import Repository

_BRANCH = re.compile(r"^\s*(if|elif|for|while|try|except|with)\b")
SIGNAL_WEIGHT = 3.0
CHANGED_WEIGHT = 5.0
BRANCH_WEIGHT = 0.1
MAX_BRANCH_POINTS = 3.0


class ScanCoverage(BaseModel):
    units_total: int
    units_selected: int
    lines_total: int
    lines_selected: int
    budget: int

    @property
    def complete(self) -> bool:
        return self.units_selected >= self.units_total


def unit_risk(unit: ReviewUnit, repo: Repository, static: list[Finding]) -> float:
    lines = repo.lines(unit.file)[unit.start_line - 1 : unit.end_line]
    signals = [
        f
        for f in static
        if f.file == unit.file and unit.start_line <= f.start_line <= unit.end_line
    ]
    score = sum(SIGNAL_WEIGHT * f.confidence for f in signals)
    score += min(sum(1 for ln in lines if _BRANCH.match(ln)) * BRANCH_WEIGHT, MAX_BRANCH_POINTS)
    if unit.changed:
        score += CHANGED_WEIGHT
    return score


def select_units(
    units: list[ReviewUnit], repo: Repository, static: list[Finding], budget: int
) -> tuple[list[ReviewUnit], ScanCoverage]:
    ranked = sorted(units, key=lambda u: (-unit_risk(u, repo, static), u.file, u.start_line))
    chosen = ranked[: max(budget, 0)]
    keep = {id(u) for u in chosen}
    selected = [u for u in units if id(u) in keep]  # original order: reports stay predictable
    coverage = ScanCoverage(
        units_total=len(units),
        units_selected=len(selected),
        lines_total=sum(u.end_line - u.start_line + 1 for u in units),
        lines_selected=sum(u.end_line - u.start_line + 1 for u in selected),
        budget=budget,
    )
    return selected, coverage
