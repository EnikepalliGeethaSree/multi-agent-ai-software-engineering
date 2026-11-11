"""Pre-run estimate for the pending Groq experiments (the approval gate before any paid call).

Per-call token profiles come from saved runs (named in PROFILES), never from guesses:
- input tokens: planted from the Groq gpt-oss-120b runs of 2026-10-12; CodeReviewer and BugsInPy
  from the current code's prompts (Ollama runs of 2026-11-08/09; another tokenizer, so approximate);
- output tokens: the Groq gpt-oss-120b planted runs (reasoning included), per configuration, since
  the local model's short replies say nothing about gpt-oss output.

Costs use the prices configured in .env (GROQ_*_PRICE_PER_1M_TOKENS_USD); without them the cost is
TBD. Estimates assume cache misses: every request is sent (repeated runs use --no-cache, or they
would replay the first run). The worst case uses the full output limit and 3 characters per token.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from marl_agents.config import LLMSettings
from marl_agents.llm.budget import Prices


class Profile(BaseModel):
    input_tokens: float
    output_tokens: float
    source: str


# Output per call of gpt-oss-120b on Groq: planted runs 20261012T161026Z (B), 161133Z (C) and
# 161434Z (D).
OUT = {"B": 5710 / 4, "C": 6154 / 4, "D": 7255 / 4}
PROFILES: dict[str, Profile] = {
    "planted_B": Profile(input_tokens=5080 / 4, output_tokens=OUT["B"],
                         source="20261012T161026Z_planted_llm_only (Groq)"),
    "planted_C": Profile(input_tokens=5808 / 4, output_tokens=OUT["C"],
                         source="20261012T161133Z_planted_static_llm (Groq)"),
    "planted_D": Profile(input_tokens=8305 / 4, output_tokens=OUT["D"],
                         source="20261012T161434Z_planted_static_llm_rag (Groq)"),
    "crmsg_B": Profile(input_tokens=2741.7, output_tokens=OUT["B"],
                       source="20261109T084547Z_codereviewer_msg_test_llm_only_n40 (input)"),
    "crmsg_C": Profile(input_tokens=2857.5, output_tokens=OUT["C"],
                       source="20261109T100904Z_codereviewer_msg_test_static_llm_n40 (input)"),
    "crmsg_D": Profile(input_tokens=4389.2, output_tokens=OUT["D"],
                       source="20261109T114916Z_codereviewer_msg_test_static_llm_rag_n40 (input)"),
    "runtime": Profile(input_tokens=54615 / 19, output_tokens=OUT["D"],
                       source="20261106T162014Z_runtime_full_r5 (input per call)"),
    "loc_B": Profile(input_tokens=26950 / 5, output_tokens=OUT["B"],
                     source="20261108T091827Z_bugsinpy_localization_dev_llm_only_n5 (input)"),
    "loc_C": Profile(input_tokens=28443 / 5, output_tokens=OUT["C"],
                     source="20261108T091827Z_bugsinpy_localization_dev_static_llm_n5 (input)"),
    "loc_D": Profile(input_tokens=28556 / 5, output_tokens=OUT["D"],
                     source="20261108T091827Z_bugsinpy_localization_dev_static_llm_rag_n5 (input)"),
    "det_B": Profile(input_tokens=16488 / 10, output_tokens=OUT["B"],
                     source="20261108T095449Z_bugsinpy_detection_dev_llm_only_n5 (input)"),
    "det_C": Profile(input_tokens=16712 / 10, output_tokens=OUT["C"],
                     source="20261108T095449Z_bugsinpy_detection_dev_static_llm_n5 (input)"),
    "det_D": Profile(input_tokens=38063 / 10, output_tokens=OUT["D"],
                     source="20261108T095449Z_bugsinpy_detection_dev_static_llm_rag_n5 (input)"),
}  # fmt: skip


class Item(BaseModel):
    experiment: str
    calls: dict[str, int]  # profile -> number of calls


def pending_plan(bugs: int = 40, runs: int = 3, samples: int = 40) -> list[Item]:
    """The approved pending experiments (3.1, 3.12, Part 4). 3.10 waits for the repositories."""
    return [
        # Planted: 4 review units per LLM configuration, plus about 1 fix suggestion in D
        # (the Gemini group used 4 + 4 + 5 requests).
        Item(experiment=f"3.1 Planted issues B/C/D x {runs} runs",
             calls={"planted_B": 4 * runs, "planted_C": 4 * runs, "planted_D": 5 * runs}),
        Item(experiment=f"3.1 CodeReviewer comments B/C/D x {runs} runs x {samples}",
             calls={f"crmsg_{c}": samples * runs for c in "BCD"}),
        # Clean repositories, configuration D: review units counted offline (requests 48, flask 73,
        # pydantic 218 in their package folders) plus at most 8 fix suggestions per repository.
        Item(experiment="3.10 Clean repos (requests, flask, pydantic), D: 339 units + fixes",
             calls={"runtime": 339 + 3 * 8}),
        Item(experiment="3.12 Runtime benchmark (cap 200 calls)", calls={"runtime": 200}),
        Item(experiment=f"4 BugsInPy localization B/C/D, {bugs} bugs (dev + test)",
             calls={f"loc_{c}": bugs for c in "BCD"}),
        Item(experiment=f"4 BugsInPy detection B/C/D, {bugs} bugs x buggy + fixed",
             calls={f"det_{c}": 2 * bugs for c in "BCD"}),
    ]  # fmt: skip


def _row(item: Item, prices: Prices, max_tokens: int) -> dict[str, Any]:
    calls = sum(item.calls.values())
    tin = sum(PROFILES[p].input_tokens * n for p, n in item.calls.items())
    tout = sum(PROFILES[p].output_tokens * n for p, n in item.calls.items())
    cost = prices.cost(round(tin), round(tout))
    worst = tin * 4 / 3 + calls * max_tokens  # 3 chars/token instead of 4; full output limit
    return {
        "experiment": item.experiment,
        "calls": calls,
        "input_tokens": round(tin),
        "output_tokens": round(tout),
        "total_tokens": round(tin + tout),
        "input_cost_usd": None if cost is None else round(cost[0], 4),
        "output_cost_usd": None if cost is None else round(cost[1], 4),
        "total_cost_usd": None if cost is None else round(sum(cost), 4),
        "worst_case_tokens": round(worst),
    }


def _minutes(calls: int, tokens: int, llm: LLMSettings) -> float | None:
    """Lower bound from the configured per-minute limits; None when they are not configured."""
    if not llm.requests_per_minute or not llm.tokens_per_minute:
        return None
    return max(calls / llm.requests_per_minute, tokens / llm.tokens_per_minute)


def estimate(llm: LLMSettings, plan: list[Item]) -> dict[str, Any]:
    prices = Prices(
        input_per_mtok=llm.input_price_per_1m_tokens_usd,
        output_per_mtok=llm.output_price_per_1m_tokens_usd,
    )
    rows = [_row(i, prices, llm.max_tokens) for i in plan]
    for r in rows:
        r["min_minutes_at_limits"] = _minutes(r["calls"], r["total_tokens"], llm)
    keys = ("calls", "input_tokens", "output_tokens", "total_tokens", "worst_case_tokens")
    total: dict[str, Any] = {"experiment": "TOTAL (all pending)"}
    total.update({k: sum(r[k] for r in rows) for k in keys})
    for k in ("input_cost_usd", "output_cost_usd", "total_cost_usd"):
        total[k] = None if any(r[k] is None for r in rows) else round(sum(r[k] for r in rows), 4)
    total["min_minutes_at_limits"] = _minutes(total["calls"], total["total_tokens"], llm)
    return {
        "model": llm.model,
        "prices_per_1m_tokens_usd": {
            "input": prices.input_per_mtok,
            "output": prices.output_per_mtok,
        },
        "caps": {"max_total_tokens": llm.max_total_tokens,
                 "max_estimated_cost_usd": llm.max_estimated_cost_usd},
        "rate_limits": {"rpm": llm.requests_per_minute, "tpm": llm.tokens_per_minute},
        "assumes": "cache misses (every request sent); repeated runs use --no-cache",
        "rows": rows,
        "total": total,
        "profiles": {k: v.model_dump() for k, v in PROFILES.items()},
    }  # fmt: skip


def estimate_md(e: dict[str, Any]) -> str:
    def money(x: float | None) -> str:
        return "TBD (set prices)" if x is None else f"${x:.2f}"

    def mins(x: float | None) -> str:
        return "TBD (set GROQ_RPM/TPM)" if x is None else f"{x:.0f} min"

    p, caps, rl = e["prices_per_1m_tokens_usd"], e["caps"], e["rate_limits"]
    lines = [
        "# Estimate for the pending Groq experiments",
        "",
        f"- Model: `{e['model']}`",
        f"- Prices (USD per 1M tokens, from .env): input {p['input'] or 'TBD'}, output "
        f"{p['output'] or 'TBD'}",
        f"- Rate limits (from .env): RPM {rl['rpm'] or 'TBD'}, TPM {rl['tpm'] or 'TBD'}",
        f"- Hard token cap: {caps['max_total_tokens'] or 'TBD (required)'}; spending cap: "
        f"{caps['max_estimated_cost_usd'] or 'TBD'}",
        f"- Assumes {e['assumes']}.",
        "",
        "| Experiment | Calls | Input tokens | Output tokens | Total tokens | Input cost | "
        "Output cost | Total cost | Worst-case tokens | Time at the limits |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for r in [*e["rows"], e["total"]]:
        lines.append(
            f"| {r['experiment']} | {r['calls']:,} | {r['input_tokens']:,} | "
            f"{r['output_tokens']:,} | {r['total_tokens']:,} | {money(r['input_cost_usd'])} | "
            f"{money(r['output_cost_usd'])} | {money(r['total_cost_usd'])} | "
            f"{r['worst_case_tokens']:,} | {mins(r['min_minutes_at_limits'])} |"
        )
    lines += ["", "Per-call profiles (tokens) and their source runs:", ""]
    for k, v in e["profiles"].items():
        lines.append(f"- {k}: input {v['input_tokens']:.0f}, output {v['output_tokens']:.0f} "
                     f"({v['source']})")  # fmt: skip
    return "\n".join(lines) + "\n"
