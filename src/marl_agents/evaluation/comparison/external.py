"""Part 3.14: the original CodeReviewer paper as an external reference row (values filled by hand).

The values live in experiments/external_reference/codereviewer_paper.json, entered by the team from
the paper. Anything not a number is shown as TBD. The row is never paired with ours, never enters a
fairness check or an observation, and always says that our set is the Python subset.
"""

from __future__ import annotations

import json
from typing import Any

from marl_agents.config import PROJECT_ROOT
from marl_agents.evaluation.comparison.models import Row

REFERENCE = PROJECT_ROOT / "experiments" / "external_reference" / "codereviewer_paper.json"
LABEL = "External reference: original CodeReviewer paper (published, all languages)"


def external_row(task: str, columns: list[str]) -> Row | None:
    try:
        data: dict[str, Any] = json.loads(REFERENCE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    published = data.get(task) or {}
    row = Row(label=LABEL, status="ok", n_runs=0)
    for col in columns:
        value = published.get(col)
        if isinstance(value, int | float) and not isinstance(value, bool):
            row.values[col] = value
        else:
            row.values[col] = None
            row.na[col] = "TBD: fill in from the paper (experiments/external_reference/)"
    row.notes.append(str(data.get("scope", "")))
    return row
