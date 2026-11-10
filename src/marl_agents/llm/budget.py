"""Hard token and spending caps for a pay-as-you-go provider (Groq Developer tier, D39).

`UsageBudget` keeps the cumulative input and output tokens and their estimated cost on disk, so the
caps hold across runs and restarts until the ledger is reset on purpose. Before every request the
provider calls `check()` with a *worst-case* estimate: a conservative prompt estimate (3 characters
per token, more tokens than the usual 4) plus the full output limit (`max_tokens`). If that request
could take the total past a cap, it is not sent: `check()` raises `QuotaExhaustedError`, which the
agents and runners already treat as "save a checkpoint and stop". So a cap is never exceeded.

Cost is an estimate: tokens times the prices configured from the Groq console (USD per million
input and output tokens). It is not the bill. Groq's own usage page is the authority.
Cached replies use no tokens and cost nothing.
"""

from __future__ import annotations

import json
import logging
import threading
from pathlib import Path

from pydantic import BaseModel

from marl_agents.llm.base import QuotaExhaustedError

logger = logging.getLogger(__name__)

CHARS_PER_TOKEN_WORST_CASE = 3


class Prices(BaseModel):
    """USD per million tokens. None = not configured (no cost can be computed)."""

    input_per_mtok: float | None = None
    output_per_mtok: float | None = None

    @property
    def known(self) -> bool:
        return self.input_per_mtok is not None and self.output_per_mtok is not None

    def cost(self, input_tokens: int, output_tokens: int) -> tuple[float, float] | None:
        """(input cost, output cost) in USD, or None without prices."""
        if not self.known:
            return None
        assert self.input_per_mtok is not None and self.output_per_mtok is not None
        return (
            input_tokens * self.input_per_mtok / 1_000_000,
            output_tokens * self.output_per_mtok / 1_000_000,
        )


def worst_case_input_tokens(prompt_chars: int) -> int:
    return max(1, -(-prompt_chars // CHARS_PER_TOKEN_WORST_CASE))


class UsageBudget:
    def __init__(
        self,
        path: Path | None,
        prices: Prices | None = None,
        max_total_tokens: int | None = None,
        max_cost_usd: float | None = None,
    ) -> None:
        self.path = path
        self.prices = prices or Prices()
        self.max_total_tokens = max_total_tokens
        self.max_cost_usd = max_cost_usd
        if max_cost_usd is not None and not self.prices.known:
            raise ValueError(
                "a spending cap is set but the token prices are not: set "
                "GROQ_INPUT_PRICE_PER_1M_TOKENS_USD and GROQ_OUTPUT_PRICE_PER_1M_TOKENS_USD"
            )
        self._lock = threading.Lock()
        self.requests = 0
        self.input_tokens = 0
        self.output_tokens = 0
        self._load()

    # ---- persistence ----------------------------------------------------------------------------

    def _load(self) -> None:
        if self.path is None or not self.path.is_file():
            return
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            logger.warning("Ignoring unreadable usage ledger %s", self.path.name)
            return
        self.requests = int(data.get("requests", 0))
        self.input_tokens = int(data.get("input_tokens", 0))
        self.output_tokens = int(data.get("output_tokens", 0))

    def _save(self) -> None:
        if self.path is None:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.status(locked=True), indent=2), encoding="utf-8")
        tmp.replace(self.path)

    # ---- caps -----------------------------------------------------------------------------------

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens

    def check(self, prompt_chars: int, max_output_tokens: int) -> None:
        """Raise QuotaExhaustedError if this request, at its worst case, could pass a cap."""
        need_in = worst_case_input_tokens(prompt_chars)
        with self._lock:
            if self.max_total_tokens is not None:
                worst = self.total_tokens + need_in + max_output_tokens
                if worst > self.max_total_tokens:
                    self._stop(
                        f"token cap: {self.total_tokens:,} used of {self.max_total_tokens:,}; the "
                        f"next request could use up to {need_in + max_output_tokens:,}"
                    )
            if self.max_cost_usd is not None:
                now = self.prices.cost(self.input_tokens, self.output_tokens)
                extra = self.prices.cost(need_in, max_output_tokens)
                assert now is not None and extra is not None
                if sum(now) + sum(extra) > self.max_cost_usd:
                    self._stop(
                        f"spending cap: ${sum(now):.4f} estimated of ${self.max_cost_usd:.2f}; the "
                        f"next request could cost up to ${sum(extra):.4f}"
                    )

    @staticmethod
    def _stop(why: str) -> None:
        raise QuotaExhaustedError(
            f"Usage cap reached ({why}). The run saved its progress. Raise the cap in .env to "
            "continue, then repeat the same command."
        )

    def record(self, input_tokens: int | None, output_tokens: int | None) -> None:
        with self._lock:
            self.requests += 1
            self.input_tokens += input_tokens or 0
            self.output_tokens += output_tokens or 0
            self._save()

    def status(self, locked: bool = False) -> dict[str, object]:
        def build() -> dict[str, object]:
            cost = self.prices.cost(self.input_tokens, self.output_tokens)
            return {
                "requests": self.requests,
                "input_tokens": self.input_tokens,
                "output_tokens": self.output_tokens,
                "total_tokens": self.total_tokens,
                "estimated_input_cost_usd": None if cost is None else round(cost[0], 6),
                "estimated_output_cost_usd": None if cost is None else round(cost[1], 6),
                "estimated_cost_usd": None if cost is None else round(sum(cost), 6),
                "max_total_tokens": self.max_total_tokens,
                "max_estimated_cost_usd": self.max_cost_usd,
                "input_price_per_1m_tokens_usd": self.prices.input_per_mtok,
                "output_price_per_1m_tokens_usd": self.prices.output_per_mtok,
            }

        if locked:
            return build()
        with self._lock:
            return build()
