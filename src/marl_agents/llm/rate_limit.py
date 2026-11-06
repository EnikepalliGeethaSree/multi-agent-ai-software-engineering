"""Client-side rate limiting for hosted LLM APIs with per-minute quotas (e.g. Groq).

A sliding 60-second window tracks requests and tokens. `acquire()` blocks until one more
request with the estimated token count fits; `settle()` replaces the estimate with the real
usage afterwards. Thread-safe, because the agent reviews units concurrently.
"""

from __future__ import annotations

import json
import logging
import threading
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

logger = logging.getLogger(__name__)

WINDOW_S = 60.0


@dataclass
class _Entry:
    at: float
    tokens: int


class RateLimiter:
    def __init__(
        self,
        requests_per_minute: int | None = None,
        tokens_per_minute: int | None = None,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.rpm = requests_per_minute
        self.tpm = tokens_per_minute
        self._clock = clock
        self._sleep = sleep
        self._window: deque[_Entry] = deque()
        self._lock = threading.Lock()
        self._blocked_until = 0.0
        self.waited_s = 0.0

    @property
    def enabled(self) -> bool:
        return bool(self.rpm or self.tpm)

    @property
    def usage_last_minute(self) -> tuple[int, int]:
        """(requests, tokens) currently counted in the window."""
        with self._lock:
            self._expire(self._clock())
            return len(self._window), sum(e.tokens for e in self._window)

    def _expire(self, now: float) -> None:
        while self._window and now - self._window[0].at >= WINDOW_S:
            self._window.popleft()

    def _wait_needed(self, now: float, tokens: int) -> float:
        if not self._window:
            return 0.0
        waits = [0.0]
        if self.rpm and len(self._window) >= self.rpm:
            waits.append(self._window[0].at + WINDOW_S - now)
        if self.tpm:
            used = sum(e.tokens for e in self._window)
            # A request larger than the whole budget waits for an empty window, then goes alone.
            need = min(tokens, self.tpm)
            if used + need > self.tpm:
                freed, wait = 0, 0.0
                for e in self._window:
                    freed += e.tokens
                    wait = e.at + WINDOW_S - now
                    if used - freed + need <= self.tpm:
                        break
                waits.append(wait)
        return max(waits)

    def acquire(self, estimated_tokens: int) -> _Entry:
        """Block until the request fits the quota; returns a handle for `settle`."""
        while True:
            with self._lock:
                now = self._clock()
                self._expire(now)
                wait = self._wait_needed(now, estimated_tokens) if self.enabled else 0.0
                wait = max(wait, self._blocked_until - now)
                if wait <= 0:
                    entry = _Entry(now, estimated_tokens)
                    self._window.append(entry)
                    return entry
            wait = max(wait, 0.05)
            self.waited_s += wait
            self._sleep(wait)

    def settle(self, entry: _Entry, actual_tokens: int | None) -> None:
        if actual_tokens is not None:
            with self._lock:
                entry.tokens = actual_tokens

    def pause(self, seconds: float) -> None:
        """Server said slow down (HTTP 429): hold back every caller for `seconds`."""
        with self._lock:
            self._blocked_until = max(self._blocked_until, self._clock() + seconds)


def estimate_tokens(text: str) -> int:
    """Rough token count (~4 characters per token for English and code)."""
    return max(1, len(text) // 4)


def _pacific() -> ZoneInfo | None:
    try:
        return ZoneInfo("America/Los_Angeles")
    except ZoneInfoNotFoundError:  # Windows without the tzdata package
        return None


def next_pacific_midnight(now: datetime | None = None) -> datetime:
    """Next midnight Pacific time, when Gemini's daily quotas reset (as a UTC datetime)."""
    now = now or datetime.now(UTC)
    zone = _pacific()
    if zone is None:  # fixed PST: during daylight saving the reset is reported an hour late
        local = now - timedelta(hours=8)
        midnight = (local + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
        return midnight + timedelta(hours=8)
    local = now.astimezone(zone)
    midnight = (local + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    return midnight.astimezone(UTC)


def pacific_date(now: datetime | None = None) -> str:
    """The Pacific calendar day of `now`: quota days run midnight to midnight Pacific."""
    return (next_pacific_midnight(now) - timedelta(hours=12)).date().isoformat()


class DailyQuota:
    """Local count of today's requests and tokens, kept on disk so restarts do not forget it.

    It only sees calls made from this machine. The provider's own count is the authority, and a
    429 from the server always wins. The purpose is to stop *before* sending a request that is
    bound to fail, and to show the remaining budget. A limit of None is not checked.
    """

    def __init__(
        self,
        path: Path | None,
        requests_per_day: int | None = None,
        tokens_per_day: int | None = None,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self.path = path
        self.rpd = requests_per_day
        self.tpd = tokens_per_day
        self._clock = clock
        self._lock = threading.Lock()
        self._day = pacific_date(clock())
        self.requests = 0
        self.tokens = 0
        self._load()

    def _load(self) -> None:
        if self.path is None or not self.path.is_file():
            return
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            logger.warning("Ignoring unreadable quota ledger %s", self.path.name)
            return
        if data.get("day") == self._day:
            self.requests = int(data.get("requests", 0))
            self.tokens = int(data.get("tokens", 0))

    def _roll(self) -> None:
        today = pacific_date(self._clock())
        if today != self._day:
            self._day, self.requests, self.tokens = today, 0, 0

    def _save(self) -> None:
        if self.path is None:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        payload = {"day": self._day, "requests": self.requests, "tokens": self.tokens}
        tmp.write_text(json.dumps(payload), encoding="utf-8")
        tmp.replace(self.path)

    def exhausted(self, estimated_tokens: int = 0) -> str | None:
        """Why the next request would exceed today's budget, or None if it fits."""
        with self._lock:
            self._roll()
            if self.rpd is not None and self.requests >= self.rpd:
                return f"{self.requests}/{self.rpd} requests used today"
            if self.tpd is not None and self.tokens + estimated_tokens > self.tpd:
                return f"{self.tokens}/{self.tpd} tokens used today"
            return None

    def record(self, tokens: int | None) -> None:
        with self._lock:
            self._roll()
            self.requests += 1
            self.tokens += tokens or 0
            self._save()

    def status(self) -> dict[str, object]:
        with self._lock:
            self._roll()
            return {
                "day": self._day,
                "requests_used": self.requests,
                "requests_limit": self.rpd,
                "tokens_used": self.tokens,
                "tokens_limit": self.tpd,
                "resets_at": next_pacific_midnight(self._clock()).isoformat(),
            }
