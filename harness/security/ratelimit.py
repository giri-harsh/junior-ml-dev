"""Small in-process token-bucket rate limiter (one bucket per key), injectable clock.

Used on the runs API: a single admin can still hammer POST /v1/runs by accident (or a stolen
cookie can), and each run costs real compute. In-process only: one limiter per API process
(documented limit; a shared store would be needed behind several replicas).
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable


class RateLimiter:
    def __init__(
        self, capacity: int, per_seconds: float, clock: Callable[[], float] = time.monotonic
    ) -> None:
        if capacity < 1 or per_seconds <= 0:
            raise ValueError("capacity >= 1 and per_seconds > 0 required")
        self.capacity, self.rate = capacity, capacity / per_seconds
        self.clock = clock
        self._state: dict[str, tuple[float, float]] = {}  # key -> (tokens, last)
        self._lock = threading.Lock()

    def allow(self, key: str) -> bool:
        now = self.clock()
        with self._lock:
            tokens, last = self._state.get(key, (float(self.capacity), now))
            tokens = min(float(self.capacity), tokens + (now - last) * self.rate)
            if tokens < 1.0:
                self._state[key] = (tokens, now)
                return False
            self._state[key] = (tokens - 1.0, now)
            return True

    def retry_after(self, key: str) -> float:
        tokens, _ = self._state.get(key, (float(self.capacity), 0.0))
        return max(0.0, (1.0 - tokens) / self.rate)
