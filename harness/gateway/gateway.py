"""Resilient, budgeted, cacheable LLM path. Every call goes through `Gateway.complete`.

Clock, sleep and RNG are injected so tests use fake time (no real sleeping, no flakiness).
"""

from __future__ import annotations

import json
import os
import random
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal, TypeVar

from pydantic import BaseModel, ValidationError

from harness.gateway.models import (
    AllProvidersDown,
    BudgetExceeded,
    LLMRequest,
    LLMResponse,
    Message,
    MissingFixture,
    ProviderError,
    StructuredOutputError,
)
from harness.gateway.providers import Provider

T = TypeVar("T", bound=BaseModel)


class CircuitBreaker:
    """closed -> open after N consecutive failures; open -> half_open after reset_s; one probe."""

    def __init__(self, failure_threshold: int, reset_s: float, clock: Callable[[], float]) -> None:
        self.threshold, self.reset_s, self.clock = failure_threshold, reset_s, clock
        self.failures = 0
        self.opened_at: float | None = None
        self.state: Literal["closed", "open", "half_open"] = "closed"

    def allow(self) -> bool:
        if self.state == "open":
            assert self.opened_at is not None
            if self.clock() - self.opened_at >= self.reset_s:
                self.state = "half_open"
                return True
            return False
        return True

    def success(self) -> None:
        self.failures, self.state, self.opened_at = 0, "closed", None

    def failure(self) -> None:
        self.failures += 1
        if self.state == "half_open" or self.failures >= self.threshold:
            self.state, self.opened_at = "open", self.clock()


@dataclass
class Budget:
    """Token and dollar caps for a run. `reserve` is the pre-call worst case (max_tokens)."""

    max_tokens: int | None = None
    max_usd: float | None = None
    used_tokens: int = 0
    used_usd: float = 0.0

    def check(self, reserve_tokens: int) -> None:
        if self.max_tokens is not None and self.used_tokens + reserve_tokens > self.max_tokens:
            raise BudgetExceeded(f"token budget {self.max_tokens} would be exceeded")
        if self.max_usd is not None and self.used_usd >= self.max_usd:
            raise BudgetExceeded(f"cost budget ${self.max_usd} exhausted")

    def charge(self, resp: LLMResponse) -> None:
        self.used_tokens += resp.usage.total
        self.used_usd += resp.cost_usd


class Fixtures:
    """VCR-style JSONL store keyed by request hash. `replay` never reaches a provider."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._data: dict[str, LLMResponse] = {}
        if path.exists():
            for line in path.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    rec = json.loads(line)
                    self._data[rec["key"]] = LLMResponse.model_validate(rec["response"])

    def get(self, key: str) -> LLMResponse | None:
        return self._data.get(key)

    def put(self, key: str, resp: LLMResponse) -> None:
        if key in self._data:
            return
        self._data[key] = resp
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps({"key": key, "response": resp.model_dump()}, sort_keys=True) + "\n")


@dataclass
class Gateway:
    providers: list[Provider]
    mode: Literal["live", "record", "replay"] = "live"
    fixtures: Fixtures | None = None
    budget: Budget = field(default_factory=Budget)
    max_monthly_usd: float = field(
        default_factory=lambda: float(os.environ.get("MAX_MONTHLY_USD", "0"))
    )
    max_retries: int = 3
    base_delay_s: float = 0.5
    max_delay_s: float = 8.0
    breaker_threshold: int = 3
    breaker_reset_s: float = 30.0
    clock: Callable[[], float] = time.monotonic
    sleep: Callable[[float], None] = time.sleep
    rng: random.Random = field(default_factory=lambda: random.Random(0))
    on_event: Callable[[dict[str, object]], None] | None = None
    max_requests: int | None = None  # hard cap on provider attempts for this gateway object

    def __post_init__(self) -> None:
        self.cache: dict[str, LLMResponse] = {}
        self.breakers = {
            p.name: CircuitBreaker(self.breaker_threshold, self.breaker_reset_s, self.clock)
            for p in self.providers
        }
        self.stats = {
            "calls": 0, "cache_hits": 0, "retries": 0, "fallbacks": 0,
            "fixture_hits": 0, "structured": 0, "structured_first_try_valid": 0,
            "repairs": 0, "structured_failed": 0,
        }  # fmt: skip

    def _emit(self, **ev: object) -> None:
        if self.on_event:
            self.on_event(ev)

    def backoff_delay(self, attempt: int) -> float:
        """Full jitter: uniform(0, min(cap, base * 2^attempt))."""
        return self.rng.uniform(0, min(self.max_delay_s, self.base_delay_s * 2**attempt))

    def complete(self, req: LLMRequest) -> LLMResponse:
        key = req.cache_key()
        if key in self.cache:
            self.stats["cache_hits"] += 1
            return self.cache[key].model_copy(update={"cached": True})
        if self.mode in {"replay", "record"} and self.fixtures:
            hit = self.fixtures.get(key)
            if hit is not None:
                self.stats["fixture_hits"] += 1
                self.cache[key] = hit
                return hit.model_copy(update={"cached": True})
            if self.mode == "replay":
                raise MissingFixture(f"no recorded response for request {key[:12]}")
        self.budget.check(req.max_tokens)
        resp = self._call_chain(req)
        self.budget.charge(resp)
        self.cache[key] = resp
        if self.mode == "record" and self.fixtures:
            self.fixtures.put(key, resp)
        self._emit(
            kind="budget",
            provider=resp.provider,
            tokens=resp.usage.total,
            cost_usd=resp.cost_usd,
            used_tokens=self.budget.used_tokens,
        )
        return resp

    def _call_chain(self, req: LLMRequest) -> LLMResponse:
        errors: list[str] = []
        for idx, p in enumerate(self.providers):
            if p.paid and self.max_monthly_usd <= 0:
                errors.append(f"{p.name}: paid provider blocked (MAX_MONTHLY_USD=0)")
                continue
            if not p.available():
                errors.append(f"{p.name}: unavailable (no key)")
                continue
            br = self.breakers[p.name]
            if not br.allow():
                errors.append(f"{p.name}: circuit open")
                continue
            try:
                resp = self._with_retries(p, req)
            except ProviderError as exc:
                br.failure()
                errors.append(f"{p.name}: {exc}")
                continue
            br.success()
            if idx > 0 or errors:
                self.stats["fallbacks"] += 1
            return resp
        raise AllProvidersDown("; ".join(errors) or "no providers configured")

    def _with_retries(self, p: Provider, req: LLMRequest) -> LLMResponse:
        for attempt in range(self.max_retries + 1):
            if self.max_requests is not None and self.stats["calls"] >= self.max_requests:
                raise BudgetExceeded(f"request cap {self.max_requests} reached")
            self.stats["calls"] += 1
            try:
                return p.complete(req)
            except ProviderError as exc:
                if getattr(exc, "not_sent", False):
                    self.stats["calls"] -= 1  # a locally refused call is not a request
                if not exc.retryable or attempt == self.max_retries:
                    raise
                self.stats["retries"] += 1
                self.sleep(self.backoff_delay(attempt))
        raise AssertionError("unreachable")

    def complete_structured(
        self, req: LLMRequest, model_cls: type[T], repair_retries: int = 2
    ) -> T:
        """Parse JSON into `model_cls`; on failure ask the model to repair (bounded)."""
        messages = list(req.messages)
        last_error = ""
        self.stats["structured"] += 1
        for attempt in range(repair_retries + 1):
            resp = self.complete(req.model_copy(update={"messages": messages}))
            try:
                parsed = model_cls.model_validate_json(_extract_json(resp.text))
                if attempt == 0:
                    self.stats["structured_first_try_valid"] += 1
                return parsed
            except (ValidationError, ValueError) as exc:
                last_error = str(exc)[:300]
                if attempt < repair_retries:
                    self.stats["repairs"] += 1
                messages = [
                    *messages,
                    Message(role="assistant", content=resp.text),
                    Message(
                        role="user",
                        content="That was not valid for the required schema. Return only JSON. "
                        f"Error: {last_error}",
                    ),
                ]
        self.stats["structured_failed"] += 1
        raise StructuredOutputError(f"no valid output after {repair_retries} repairs: {last_error}")


def _extract_json(text: str) -> str:
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end < start:
        raise ValueError("no JSON object in response")
    return text[start : end + 1]
