"""Hunk risk model v2: calibrated logistic score, guardrail, monotone signals."""

from __future__ import annotations

import math

import pytest

from marl_agents.agents.code_review import risk
from marl_agents.agents.code_review.risk import HunkView, score_hunk
from marl_agents.core.schemas import ChangedSymbol, Finding


def _view(added: list[str], deleted: int = 0) -> HunkView:
    return HunkView("a.py", 10, 10 + max(len(added), 1) - 1, added, deleted, "@@")


def _finding(sev: str, line: int = 10) -> Finding:
    return Finding(
        id=f"CR-{sev}", file="a.py", start_line=line, end_line=line, category="bug",
        severity=sev, title="t", description="d", confidence=0.8,  # type: ignore[arg-type]
        sources=["ruff"],  # type: ignore[list-item]
    )  # fmt: skip


def test_score_is_the_calibrated_logistic() -> None:
    h = score_hunk(_view(["x = 1"]), [], [])
    expected = 100 / (1 + math.exp(-(risk.INTERCEPT + risk.W_LOG2_SIZE * math.log2(2))))
    assert h.score == pytest.approx(expected, abs=0.05) and h.level == "low"
    sens = score_hunk(_view(["try:", "    eval(x)", "except ValueError:", "    raise"]), [], [])
    assert {"changes error handling"} <= set(sens.reasons)
    assert any(r.startswith("touches security-sensitive code: eval") for r in sens.reasons)
    assert sens.score > h.score and sens.level == "high"


def test_every_signal_is_monotone() -> None:
    base = score_hunk(_view(["x = 1"]), [], []).score
    sym = ChangedSymbol(
        file="a.py", qualname="f", kind="modified", line=10, end_line=10,
        signature_changed=True, callers=3, callers_not_updated=3,
    )  # fmt: skip
    for kwargs in (
        {"findings": [_finding("medium")], "symbols": []},
        {"findings": [], "symbols": [sym]},
        {"findings": [], "symbols": [sym.model_copy(update={"kind": "removed"})]},
    ):
        assert score_hunk(_view(["x = 1"], deleted=1), **kwargs).score >= base  # type: ignore[arg-type]
    big = score_hunk(_view(["x = 1"] * 60), [], [])
    assert big.score > base and "large hunk (60 changed lines)" in big.reasons


def test_guardrail_never_buries_severe_findings() -> None:
    crit = score_hunk(_view(["x = 1"]), [_finding("critical")], [])
    high = score_hunk(_view(["x = 1"]), [_finding("high")], [])
    low = score_hunk(_view(["x = 1"]), [_finding("low")], [])
    assert (crit.level, high.level, low.level) == ("high", "medium", "low")
    assert crit.finding_ids == ["CR-critical"]
    assert crit.reasons[0] == "1 finding(s) in this hunk (worst: critical)"
