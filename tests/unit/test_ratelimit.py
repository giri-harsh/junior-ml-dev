from __future__ import annotations

import pytest

from harness.security.ratelimit import RateLimiter


class Clock:
    def __init__(self) -> None:
        self.t = 100.0

    def __call__(self) -> float:
        return self.t


def test_bucket_allows_a_burst_then_refills_over_time() -> None:
    c = Clock()
    rl = RateLimiter(3, 60.0, clock=c)  # 3 per minute = one token / 20 s
    assert [rl.allow("a") for _ in range(4)] == [True, True, True, False]
    assert 19 < rl.retry_after("a") <= 20
    c.t += 20
    assert rl.allow("a") and not rl.allow("a")
    c.t += 600
    assert [rl.allow("a") for _ in range(4)] == [True, True, True, False]  # capped at capacity


def test_keys_are_independent_and_config_is_validated() -> None:
    rl = RateLimiter(1, 60.0, clock=Clock())
    assert rl.allow("a") and not rl.allow("a") and rl.allow("b")
    with pytest.raises(ValueError):
        RateLimiter(0, 10.0)
