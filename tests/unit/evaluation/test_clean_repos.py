"""Part 3.10 runner pieces: density per 1,000 lines and the unlabeled sampling sheet."""

from __future__ import annotations

import csv
from pathlib import Path

import pytest

from marl_agents.core.schemas import Category, Finding, Severity
from marl_agents.evaluation.runners.clean_repos import REPOS, SHEET_COLUMNS, density, export_sheet


def _f(i: int, sev: Severity) -> Finding:
    return Finding(id=f"CR-{i:03d}", file="a.py", start_line=1, end_line=1, category=Category.BUG,
                   severity=sev, title="t", description="d", confidence=0.5)  # fmt: skip


def test_density_per_kloc_by_severity() -> None:
    d = density([_f(1, Severity.HIGH), _f(2, Severity.LOW), _f(3, Severity.LOW)], 1500)
    assert d["findings"] == 3 and d["per_kloc"] == pytest.approx(2.0)
    assert d["by_severity"]["low"] == 2 and d["per_kloc_by_severity"]["high"] == pytest.approx(
        0.667
    )
    assert density([], 0)["per_kloc"] is None


def test_sheet_is_a_seeded_sample_with_empty_labels_and_never_overwritten(tmp_path: Path) -> None:
    rows = [{"repo": "r", "run": "x", "id": f"CR-{i}", "file": "a.py", "start_line": i,
             "end_line": i, "severity": "low", "category": "bug", "title": "t", "description": "d",
             "evidence": ["e"], "sources": ["ruff"]} for i in range(80)]  # fmt: skip
    out = tmp_path / "s.csv"
    assert export_sheet(rows, out, 50) == 50
    got = list(csv.DictReader(out.open(encoding="utf-8")))
    assert list(got[0]) == SHEET_COLUMNS and all(r["label"] == r["notes"] == "" for r in got)
    again = tmp_path / "s2.csv"
    export_sheet(rows, again, 50)
    assert out.read_text(encoding="utf-8") == again.read_text(encoding="utf-8")  # seeded
    with pytest.raises(FileExistsError):
        export_sheet(rows, out, 50)


def test_the_three_team_chosen_repositories_are_pinned() -> None:
    assert [r.name for r in REPOS] == ["requests", "flask", "pydantic"]
    assert all(len(r.commit) == 40 for r in REPOS)
