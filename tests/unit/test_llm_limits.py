from __future__ import annotations

from pathlib import Path

import httpx
import pytest

from harness.gateway.envload import load_llm_keys
from harness.gateway.gateway import Gateway
from harness.gateway.limits import CappedProvider, UsageLedger
from harness.gateway.live import build_chain
from harness.gateway.models import LLMRequest, Message, ProviderError
from harness.gateway.providers import GeminiProvider, MockProvider, OpenAICompatProvider


class Clock:
    def __init__(self) -> None:
        self.t = 0.0
        self.slept: list[float] = []

    def __call__(self) -> float:
        return self.t

    def sleep(self, s: float) -> None:
        self.slept.append(s)
        self.t += s


def req(text: str = "hi") -> LLMRequest:
    return LLMRequest(messages=[Message(role="user", content=text)])


def ledger(
    tmp_path: Path, clock: Clock, today: str = "2026-01-01", per_day: int = 3
) -> UsageLedger:
    return UsageLedger(
        tmp_path / "u.json", per_day=per_day, min_interval_s=2.0,
        today=lambda: today, clock=clock, sleep=clock.sleep,
    )  # fmt: skip


def test_requests_are_spaced_at_least_two_seconds(tmp_path: Path) -> None:
    c = Clock()
    led = ledger(tmp_path, c, per_day=10)
    for _ in range(3):
        led.acquire("groq")
    assert c.slept == [2.0, 2.0] and c.t == 4.0  # first is free, then 2 s each
    led.acquire("gemini")  # another family is not delayed by groq
    assert c.slept == [2.0, 2.0]


def test_daily_cap_is_hard_persistent_and_resets_next_day(tmp_path: Path) -> None:
    c = Clock()
    led = ledger(tmp_path, c)
    for _ in range(3):
        led.acquire("groq")
    with pytest.raises(ProviderError, match="daily cap") as ei:
        led.acquire("groq")
    assert ei.value.retryable is False
    fresh = ledger(tmp_path, Clock())  # a new process sees the same count
    assert fresh.used("groq") == 3
    with pytest.raises(ProviderError):
        fresh.acquire("groq")
    assert ledger(tmp_path, Clock(), today="2026-01-02").used("groq") == 0


def test_capped_provider_counts_attempts_even_when_the_call_fails(tmp_path: Path) -> None:
    c = Clock()
    led = ledger(tmp_path, c)

    def boom(r: LLMRequest, i: int) -> str:
        raise ProviderError("HTTP 500", retryable=True, status=500)

    p = CappedProvider(MockProvider(boom, name="groq"), "groq", led)
    for _ in range(3):
        with pytest.raises(ProviderError):
            p.complete(req())
    assert led.used("groq") == 3
    with pytest.raises(ProviderError, match="daily cap"):
        p.complete(req())


def test_gateway_falls_through_to_the_next_family_when_one_is_capped(tmp_path: Path) -> None:
    c = Clock()
    led = ledger(tmp_path, c, per_day=1)
    a = CappedProvider(MockProvider(lambda r, i: "from-a", name="groq"), "groq", led)
    b = CappedProvider(MockProvider(lambda r, i: "from-b", name="gemini"), "gemini", led)
    gw = Gateway(providers=[a, b], sleep=c.sleep)
    assert gw.complete(req("one")).text == "from-a"
    assert gw.complete(req("two")).text == "from-b"  # groq capped -> gemini
    with pytest.raises(Exception, match="daily cap"):
        gw.complete(req("three"))  # both capped: no request leaves the process


def test_both_groq_models_share_one_cap(tmp_path: Path) -> None:
    c = Clock()
    led = ledger(tmp_path, c, per_day=2)
    chain = build_chain(("groq",), led)
    assert [p.inner.model for p in chain] == [
        "openai/gpt-oss-120b",
        "openai/gpt-oss-20b",
    ]
    led.acquire("groq")
    led.acquire("groq")
    assert all(
        isinstance(p.inner, OpenAICompatProvider) and led.used(p.family) == 2  # type: ignore[attr-defined]
        for p in chain
    )


def test_gemini_request_shape_has_no_secret_in_url() -> None:
    seen: list[httpx.Request] = []

    def handler(r: httpx.Request) -> httpx.Response:
        seen.append(r)
        body = {"candidates": [{"content": {"parts": [{"text": "ok"}]}}], "usageMetadata": {}}
        return httpx.Response(200, json=body)

    import os

    os.environ["GEMINI_API_KEY"] = "test-key-not-real"
    try:
        GeminiProvider("m", transport=httpx.MockTransport(handler)).complete(req())
    finally:
        del os.environ["GEMINI_API_KEY"]
    assert "test-key" not in str(seen[0].url) and seen[0].headers["x-goog-api-key"]


def test_env_loader_reads_only_the_allowlist(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    f = tmp_path / ".env"
    f.write_text(
        "POSTGRES_PASSWORD=secret1\nGROQ_API_KEY=g-1\nQDRANT_API_KEY=q\n#GEMINI_API_KEY=no\n"
    )
    for name in ("GROQ_API_KEY", "GEMINI_API_KEY", "POSTGRES_PASSWORD", "QDRANT_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    import os

    assert load_llm_keys((f,)) == ["GROQ_API_KEY"]
    assert os.environ["GROQ_API_KEY"] == "g-1"
    assert "POSTGRES_PASSWORD" not in os.environ and "QDRANT_API_KEY" not in os.environ
    monkeypatch.delenv("GROQ_API_KEY")


def test_request_cap_counts_repairs_and_retries(tmp_path: Path) -> None:
    """Run 5's critic used 31 of 30 because a repair round trip was not counted. The cap is now
    enforced per provider attempt inside the gateway."""
    from pydantic import BaseModel

    from harness.gateway.models import BudgetExceeded, StructuredOutputError

    class Out(BaseModel):
        ok: bool

    gw = Gateway(
        providers=[MockProvider(lambda r, i: "not json")], max_requests=3, sleep=lambda s: None
    )
    with pytest.raises((StructuredOutputError, BudgetExceeded)):
        gw.complete_structured(req("x"), Out, repair_retries=5)
    assert gw.stats["calls"] == 3  # never a 4th request
    with pytest.raises(BudgetExceeded):
        gw.complete(req("another prompt"))
    assert gw.stats["calls"] == 3


def test_default_daily_cap_is_120() -> None:
    from harness.gateway.limits import DEFAULT_PER_DAY

    assert DEFAULT_PER_DAY == 120


def test_locally_refused_calls_do_not_count_as_requests(tmp_path: Path) -> None:
    c = Clock()
    led = ledger(tmp_path, c, per_day=0)  # groq is capped from the start
    capped = CappedProvider(MockProvider(lambda r, i: "x", name="groq"), "groq", led)
    ok = MockProvider(lambda r, i: "from-fallback", name="gemini")
    gw = Gateway(providers=[capped, ok], max_requests=2, sleep=c.sleep)
    for i in range(2):
        assert gw.complete(req(f"q{i}")).text == "from-fallback"
    assert gw.stats["calls"] == 2  # two real requests, not four
