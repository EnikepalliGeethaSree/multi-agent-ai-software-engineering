"""Centralized API key manager: round-robin rotation with per-key and shared quotas.

Built for Groq (D38) but provider-neutral. Each key is known by a label taken from its environment
variable (``GROQ_API_KEY_3`` -> ``key3``). Labels, never secrets, reach logs, errors, ledgers,
checkpoints and result files.

Rotation
    Every new request takes the next *eligible* key after the one used last, wrapping around after
    the last key. A key is skipped while it is cooling down (per-minute limit or HTTP 429), when
    today's budget is spent, or after the server rejected it (401/403). Retries are new requests,
    so they move on to the next eligible key and the rotation never stalls on a bad key.

Limits
    Two levels are enforced together:

    * per key: requests and tokens per minute and per day;
    * shared: the same four limits for the whole organization.

    Groq applies its limits per organization, so keys of one organization share a single budget.
    The shared limits default to one key's limits for that reason: ten keys do not mean ten times
    the quota. Every limit is configurable, and the provider's own answer (headers, HTTP 429) always
    wins over these local counts.

Exhaustion
    When every key has spent today's budget (or the shared budget is spent), `acquire` raises
    `QuotaExhaustedError` with the reset time. The agents and runners already treat that error as
    "save a checkpoint and stop", so a run resumes cleanly after the reset.

Thread-safe: evaluation units may request keys concurrently.
"""

from __future__ import annotations

import logging
import os
import re
import threading
import time
from collections import deque
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from marl_agents.llm.base import LLMError, QuotaExhaustedError
from marl_agents.llm.rate_limit import DailyQuota, next_utc_midnight, utc_date

logger = logging.getLogger(__name__)

WINDOW_S = 60.0
_INDEX = re.compile(r"(\d+)$")


@dataclass(frozen=True)
class Limits:
    """Requests and tokens per minute and per day. None means "not checked"."""

    rpm: int | None = None
    tpm: int | None = None
    rpd: int | None = None
    tpd: int | None = None


def key_label(env_name: str, position: int) -> str:
    """'GROQ_API_KEY_3' -> 'key3'; a name without a number gets its position (1-based)."""
    m = _INDEX.search(env_name)
    return f"key{m.group(1) if m else position}"


def load_keys(env_names: Iterable[str]) -> list[tuple[str, str]]:
    """(label, secret) for every environment variable in `env_names` that is set and non-empty.

    Missing variables are skipped, so fewer than ten keys work. Duplicate secrets are used once.
    """
    seen: set[str] = set()
    out: list[tuple[str, str]] = []
    for position, name in enumerate(env_names, start=1):
        secret = os.environ.get(name, "").strip()
        if not secret or secret in seen:
            continue
        seen.add(secret)
        out.append((key_label(name, position), secret))
    return out


class _Window:
    """Sliding 60-second count of requests and tokens."""

    def __init__(self) -> None:
        self._entries: deque[list[float]] = deque()  # [time, tokens]

    def _expire(self, now: float) -> None:
        while self._entries and now - self._entries[0][0] >= WINDOW_S:
            self._entries.popleft()

    def wait_for(self, now: float, tokens: int, rpm: int | None, tpm: int | None) -> float:
        """Seconds until one more request of `tokens` fits; 0 if it fits now."""
        self._expire(now)
        if not self._entries:
            return 0.0
        waits = [0.0]
        if rpm and len(self._entries) >= rpm:
            waits.append(self._entries[0][0] + WINDOW_S - now)
        if tpm:
            used = sum(e[1] for e in self._entries)
            need = min(tokens, tpm)  # a request larger than the budget goes alone
            if used + need > tpm:
                freed, wait = 0.0, 0.0
                for at, tok in self._entries:
                    freed += tok
                    wait = at + WINDOW_S - now
                    if used - freed + need <= tpm:
                        break
                waits.append(wait)
        return max(waits)

    def add(self, now: float, tokens: int) -> list[float]:
        entry = [now, float(tokens)]
        self._entries.append(entry)
        return entry


@dataclass
class KeyStats:
    """Accounting for one key. Labels only: the secret is not part of this object."""

    requests: int = 0
    failed: int = 0
    rate_limited: int = 0
    input_tokens: int = 0
    output_tokens: int = 0


@dataclass
class _Key:
    label: str
    secret: str = field(repr=False)
    limits: Limits
    daily: DailyQuota
    window: _Window = field(default_factory=_Window)
    cooldown_until: float = 0.0  # monotonic clock
    exhausted_until: datetime | None = None  # server or ledger says today's budget is spent
    disabled: str | None = None  # why the server rejected this key (401/403)
    stats: KeyStats = field(default_factory=KeyStats)


@dataclass
class Lease:
    """One request's hold on a key. Pass it back to `settle`, `cool_down` or `exhaust`."""

    label: str
    secret: str = field(repr=False)
    estimate: int = 0
    _key_entry: list[float] = field(default_factory=list, repr=False)
    _shared_entry: list[float] = field(default_factory=list, repr=False)


class KeyManager:
    def __init__(
        self,
        keys: list[tuple[str, str]],
        per_key: Limits | None = None,
        shared: Limits | None = None,
        ledger_dir: Path | None = None,
        ledger_prefix: str = "keys",
        shared_org: bool = True,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        if not keys:
            raise ValueError("at least one API key is required")
        self.per_key = per_key or Limits()
        self.shared_limits = shared or Limits()
        # True when the keys belong to one organization, so a limit reported on one key (HTTP 429,
        # daily limit) applies to all of them. Groq counts limits per organization.
        self.shared_org = shared_org
        self._clock = clock
        self._sleep = sleep
        self._now = now
        self._lock = threading.Lock()
        self._next = 0
        self.waited_s = 0.0

        def ledger(name: str, limits: Limits) -> DailyQuota:
            path = ledger_dir / f"{ledger_prefix}_{name}.json" if ledger_dir else None
            return DailyQuota(
                path, limits.rpd, limits.tpd, clock=now, day_of=utc_date,
                next_reset=next_utc_midnight,
            )  # fmt: skip

        self._keys = [
            _Key(label, secret, self.per_key, ledger(label, self.per_key)) for label, secret in keys
        ]
        self._shared_window = _Window()
        self._shared_daily = ledger("shared", self.shared_limits)
        self._shared_cooldown = 0.0

    # ---- selection ------------------------------------------------------------------------------

    @property
    def labels(self) -> list[str]:
        return [k.label for k in self._keys]

    def acquire(self, estimated_tokens: int) -> Lease:
        """Block until a key can take one more request; return it. Round-robin over eligible keys.

        Raises QuotaExhaustedError when no key can be used again today.
        """
        while True:
            with self._lock:
                now = self._clock()
                lease, wait = self._try_acquire(now, estimated_tokens)
                if lease is not None:
                    return lease
            wait = max(wait, 0.05)
            self.waited_s += wait
            self._sleep(wait)

    def _try_acquire(self, now: float, tokens: int) -> tuple[Lease | None, float]:
        today_now = self._now()
        shared_used = self._shared_daily.exhausted(tokens)
        if shared_used is not None:
            self._raise_exhausted(f"shared daily limit, {shared_used}", shared=True)
        shared_wait = max(
            self._shared_window.wait_for(
                now, tokens, self.shared_limits.rpm, self.shared_limits.tpm
            ),
            self._shared_cooldown - now,
        )
        n = len(self._keys)
        waits: list[float] = []
        usable = 0
        for step in range(n):
            idx = (self._next + step) % n
            key = self._keys[idx]
            if key.disabled:
                continue
            if key.exhausted_until is not None:
                if today_now < key.exhausted_until:
                    continue
                key.exhausted_until = None
            if key.daily.exhausted(tokens) is not None:
                continue
            usable += 1
            wait = max(
                key.window.wait_for(now, tokens, key.limits.rpm, key.limits.tpm),
                key.cooldown_until - now,
            )
            if wait <= 0 and shared_wait <= 0:
                self._next = (idx + 1) % n
                return (
                    Lease(
                        key.label,
                        key.secret,
                        tokens,
                        key.window.add(now, tokens),
                        self._shared_window.add(now, tokens),
                    ),
                    0.0,
                )
            waits.append(max(wait, shared_wait))
        if usable == 0:
            if all(k.disabled for k in self._keys):
                reasons = ", ".join(f"{k.label}: {k.disabled}" for k in self._keys)
                raise LLMError(f"every API key was rejected by the server ({reasons})")
            self._raise_exhausted("every key has used today's budget")
        return None, min(waits)

    def _raise_exhausted(self, why: str, shared: bool = False) -> None:
        if shared:
            reset = self._shared_daily.resets_at()
        else:  # the first key to come back decides when the run can resume
            reset = min(
                k.exhausted_until or k.daily.resets_at() for k in self._keys if not k.disabled
            )
        raise QuotaExhaustedError(
            f"All API keys reached their daily limit ({why}). The run saved its progress; "
            f"resume after {reset.isoformat(timespec='minutes')} with the same command.",
            resets_at=reset.isoformat(),
        )

    # ---- outcomes -------------------------------------------------------------------------------

    def _key(self, lease: Lease) -> _Key:
        return next(k for k in self._keys if k.label == lease.label)

    def settle(
        self, lease: Lease, ok: bool, input_tokens: int | None = None,
        output_tokens: int | None = None,
    ) -> None:  # fmt: skip
        """Record the outcome. A request that reached the server counts against the budgets."""
        total = (input_tokens or 0) + (output_tokens or 0)
        with self._lock:
            key = self._key(lease)
            if ok:
                key.stats.requests += 1
                key.stats.input_tokens += input_tokens or 0
                key.stats.output_tokens += output_tokens or 0
                if input_tokens is not None or output_tokens is not None:
                    lease._key_entry[1] = lease._shared_entry[1] = float(total)
            else:
                key.stats.failed += 1
                lease._key_entry[1] = lease._shared_entry[1] = 0.0
        if ok:
            key.daily.record(total)
            self._shared_daily.record(total)

    def release(self, lease: Lease) -> None:
        """Give a lease back unused (e.g. after listing models): it counts against nothing."""
        with self._lock:
            lease._key_entry[1] = lease._shared_entry[1] = 0.0

    def cool_down(self, lease: Lease, seconds: float, shared: bool = False) -> None:
        """Per-minute limit hit (HTTP 429): rest this key (or every key) for `seconds`."""
        with self._lock:
            key = self._key(lease)
            key.stats.rate_limited += 1
            until = self._clock() + max(seconds, 0.0)
            key.cooldown_until = max(key.cooldown_until, until)
            if shared or self.shared_org:
                self._shared_cooldown = max(self._shared_cooldown, until)
        scope = "every key" if shared or self.shared_org else "it"
        logger.info("%s rate limited; resting %s for %.1fs", lease.label, scope, seconds)

    def exhaust(self, lease: Lease, seconds: float | None = None) -> None:
        """Daily limit hit: skip this key until the server's reset (or the next UTC midnight)."""
        with self._lock:
            key = self._key(lease)
            key.stats.rate_limited += 1
            now = self._now()
            until = now + timedelta(seconds=seconds) if seconds else next_utc_midnight(now)
            for k in self._keys if self.shared_org else [key]:
                k.exhausted_until = until
        logger.warning(
            "%s reached its daily limit; skipping %s until %s",
            lease.label,
            "every key (shared organization limit)" if self.shared_org else "it",
            until.isoformat(timespec="minutes"),
        )

    def disable(self, lease: Lease, reason: str) -> None:
        """The server rejected the key itself (401/403): never use it again in this process."""
        with self._lock:
            self._key(lease).disabled = reason
        logger.error("%s was rejected by the server (%s); continuing with the other keys",
                     lease.label, reason)  # fmt: skip

    def apply_headers(self, lease: Lease, headers: Any, next_estimate: int) -> None:
        """Follow the server's `x-ratelimit-*` headers.

        Groq: `*-requests` describe requests per day, `*-tokens` tokens per minute. A known limit
        replaces the configured one for this key; a low remaining count rests the key until reset.
        """

        def num(name: str) -> int | None:
            try:
                return int(float(headers.get(name)))
            except (TypeError, ValueError):
                return None

        from marl_agents.llm.openai_compat import parse_duration

        limit_req, limit_tok = num("x-ratelimit-limit-requests"), num("x-ratelimit-limit-tokens")
        rem_req, rem_tok = (
            num("x-ratelimit-remaining-requests"),
            num("x-ratelimit-remaining-tokens"),
        )
        with self._lock:
            key = self._key(lease)
            if limit_req or limit_tok:
                key.limits = Limits(
                    rpm=key.limits.rpm,
                    tpm=limit_tok or key.limits.tpm,
                    rpd=limit_req or key.limits.rpd,
                    tpd=key.limits.tpd,
                )
                key.daily.rpd = key.limits.rpd
        if rem_req is not None and rem_req <= 0:
            self.exhaust(lease, parse_duration(headers.get("x-ratelimit-reset-requests")))
        elif rem_tok is not None and rem_tok < next_estimate:
            reset = parse_duration(headers.get("x-ratelimit-reset-tokens"))
            if reset:
                with self._lock:
                    key.cooldown_until = max(key.cooldown_until, self._clock() + min(reset, 60.0))

    # ---- reporting ------------------------------------------------------------------------------

    def status(self) -> list[dict[str, Any]]:
        """Per-key accounting and availability. Contains labels only, never secrets."""
        rows: list[dict[str, Any]] = []
        with self._lock:
            now = self._clock()
            for k in self._keys:
                day = k.daily.status()
                state = "available"
                if k.disabled:
                    state = f"rejected ({k.disabled})"
                elif k.exhausted_until is not None and self._now() < k.exhausted_until:
                    state = f"daily limit until {k.exhausted_until.isoformat(timespec='minutes')}"
                elif k.cooldown_until > now:
                    state = f"cooling down {k.cooldown_until - now:.0f}s"
                rows.append({
                    "key": k.label,
                    "state": state,
                    "requests": k.stats.requests,
                    "failed": k.stats.failed,
                    "rate_limited": k.stats.rate_limited,
                    "input_tokens": k.stats.input_tokens,
                    "output_tokens": k.stats.output_tokens,
                    "requests_today": day["requests_used"],
                    "tokens_today": day["tokens_used"],
                })  # fmt: skip
        return rows

    def shared_status(self) -> dict[str, object]:
        return self._shared_daily.status()
