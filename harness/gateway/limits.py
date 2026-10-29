"""Hard request caps for shared free-tier keys, enforced in code, persisted across processes.

Caps (per provider FAMILY, e.g. both Groq models share "groq"): at most `per_day` requests per UTC
day and one request per `min_interval_s`. Every HTTP attempt counts, including failed ones. A
reached cap raises a non-retryable ProviderError so the gateway moves to the next provider and,
when all are capped, to the cache / scripted planner.
"""

from __future__ import annotations

import json
import os
import threading
import time
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

from harness.gateway.models import LLMRequest, LLMResponse, ProviderError
from harness.gateway.providers import Provider

DEFAULT_PER_DAY = 120  # run 6 policy (the keys also serve a live demo)
DEFAULT_MIN_INTERVAL_S = 2.0


def _utc_today() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%d")


class UsageLedger:
    """JSON file {date: {family: count}}; one process at a time (a lock guards threads)."""

    def __init__(
        self,
        path: Path | str,
        per_day: int = DEFAULT_PER_DAY,
        min_interval_s: float = DEFAULT_MIN_INTERVAL_S,
        today: Callable[[], str] = _utc_today,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.path = Path(path)
        self.per_day, self.min_interval_s = per_day, min_interval_s
        self.today, self.clock, self.sleep = today, clock, sleep
        self._last: dict[str, float] = {}
        self._lock = threading.Lock()

    def _load(self) -> dict[str, dict[str, int]]:
        if not self.path.exists():
            return {}
        return dict(json.loads(self.path.read_text(encoding="utf-8")))

    def used(self, family: str) -> int:
        return int(self._load().get(self.today(), {}).get(family, 0))

    def acquire(self, family: str) -> None:
        """Wait for the spacing window, then count one request. Raises when the cap is reached."""
        with self._lock:
            data = self._load()
            day = data.setdefault(self.today(), {})
            if day.get(family, 0) >= self.per_day:
                raise ProviderError(
                    f"daily cap of {self.per_day} requests reached for {family}", retryable=False
                )
            wait = self._last.get(family, -1e18) + self.min_interval_s - self.clock()
            if wait > 0:
                self.sleep(wait)
            day[family] = day.get(family, 0) + 1
            self._last[family] = self.clock()
            tmp = self.path.with_suffix(".tmp")
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp.write_text(json.dumps(data, sort_keys=True), encoding="utf-8")
            os.replace(tmp, self.path)


class CappedProvider:
    def __init__(self, inner: Provider, family: str, ledger: UsageLedger) -> None:
        self.inner, self.family, self.ledger = inner, family, ledger
        self.name = inner.name
        self.paid = inner.paid

    def available(self) -> bool:
        return self.inner.available()

    def complete(self, req: LLMRequest) -> LLMResponse:
        self.ledger.acquire(self.family)
        return self.inner.complete(req)
