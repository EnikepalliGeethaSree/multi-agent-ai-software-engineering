"""Pre-run estimate (approval gate): token sums from saved profiles, configured prices only."""

from __future__ import annotations

import pytest

from marl_agents.config import LLMSettings
from marl_agents.evaluation.estimate import PROFILES, Item, estimate, estimate_md, pending_plan


def test_costs_use_the_configured_prices_separately_for_input_and_output() -> None:
    llm = LLMSettings(provider="groq", model="openai/gpt-oss-120b", max_tokens=1000,
                      input_price_per_1m_tokens_usd=1.0, output_price_per_1m_tokens_usd=2.0,
                      requests_per_minute=10, tokens_per_minute=100_000)  # fmt: skip
    e = estimate(llm, [Item(experiment="x", calls={"planted_B": 4})])
    row = e["rows"][0]
    p = PROFILES["planted_B"]
    assert row["input_tokens"] == round(4 * p.input_tokens)
    assert row["input_cost_usd"] == pytest.approx(row["input_tokens"] / 1e6, abs=1e-4)
    assert row["output_cost_usd"] == pytest.approx(2 * row["output_tokens"] / 1e6, abs=1e-4)
    assert row["worst_case_tokens"] == round(4 * p.input_tokens * 4 / 3 + 4 * 1000)
    assert row["min_minutes_at_limits"] == pytest.approx(0.4)  # 4 calls at 10 per minute


def test_without_prices_or_limits_the_cost_and_time_are_tbd() -> None:
    e = estimate(LLMSettings(provider="groq", model="m"), pending_plan(bugs=40, runs=3))
    assert e["total"]["total_cost_usd"] is None and e["total"]["min_minutes_at_limits"] is None
    assert e["total"]["calls"] == 39 + 360 + 363 + 200 + 120 + 240
    md = estimate_md(e)
    assert "TBD (set prices)" in md and "cache misses" in md
