"""Filter vague, non-actionable LLM findings (the #1 complaint about review bots in the literature:
"unsatisfactory recommendations" and information overload).

A finding is actionable when it names a concrete problem in concrete code and says what to change.
Rules apply to LLM-only findings; tool findings are concrete by construction.

- 2+ problems -> dropped (counted in stats as `filtered_vague`)
- 1 problem   -> kept, downgraded to `info`, reason recorded in `notes`
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from marl_agents.core.schemas import Finding, FindingSource, Severity

VAGUE = re.compile(
    r"\b(consider|might want|may want|could be improved|it would be (better|nice|good)|"
    r"ensure that|make sure|be careful|think about|you may|perhaps|possibly|review this|"
    r"double[- ]check|keep in mind|best practice)\b",
    re.IGNORECASE,
)
CONCRETE = re.compile(r"`[^`]+`|\b[a-z_][a-z0-9_]*\(|\b[A-Za-z_]+\.[A-Za-z_]+\b|\bline \d+")
MIN_FIX_WORDS = 4
MIN_DESCRIPTION_WORDS = 6


@dataclass
class Actionability:
    problems: list[str]

    @property
    def keep(self) -> bool:
        return len(self.problems) < 2


def assess(f: Finding) -> Actionability:
    if f.sources != [FindingSource.LLM]:
        return Actionability([])
    problems: list[str] = []
    text = f"{f.description} {f.recommendation or ''}"
    if not f.recommendation or len(f.recommendation.split()) < MIN_FIX_WORDS:
        problems.append("no concrete fix")
    if len(f.description.split()) < MIN_DESCRIPTION_WORDS:
        problems.append("description too short to act on")
    if f.title.strip().endswith("?") or f.description.strip().endswith("?"):
        problems.append("asks a question instead of stating a problem")
    if VAGUE.search(text) and not CONCRETE.search(text):
        problems.append("vague wording without a concrete code reference")
    return Actionability(problems)


def filter_actionable(findings: list[Finding]) -> tuple[list[Finding], int, int]:
    """Returns (kept findings, dropped count, downgraded count)."""
    kept: list[Finding] = []
    dropped = downgraded = 0
    for f in findings:
        a = assess(f)
        if not a.problems:
            kept.append(f)
        elif a.keep:
            downgraded += 1
            kept.append(
                f.model_copy(
                    update={
                        "severity": Severity.INFO,
                        "notes": [*f.notes, f"downgraded to info: {a.problems[0]}"],
                    }
                )
            )
        else:
            dropped += 1
    return kept, dropped, downgraded
