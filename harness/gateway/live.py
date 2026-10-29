"""Builds the live (cloud) gateway: capped providers in a fixed order, disk cache, key loading.

Order is decided by a recorded bake-off (see docs/DECISIONS.md); only Gemini and Groq are used, so
nothing is ever installed or run locally. Keys are read from the environment / allowlisted .env.
"""

from __future__ import annotations

import os
from pathlib import Path

from harness.gateway.envload import load_llm_keys
from harness.gateway.gateway import Budget, Fixtures, Gateway
from harness.gateway.limits import CappedProvider, UsageLedger
from harness.gateway.providers import GeminiProvider, OpenAICompatProvider, Provider

USAGE_PATH = Path(os.environ.get("LLM_USAGE_PATH", "data/llm_usage.json"))
GEMINI_MODEL = os.environ.get("JMD_GEMINI_MODEL", "gemini-3.5-flash-lite")
GROQ_PRIMARY = "openai/gpt-oss-120b"
GROQ_FALLBACK = "openai/gpt-oss-20b"


def _groq(model: str, ledger: UsageLedger) -> Provider:
    p = OpenAICompatProvider(
        "groq",
        "https://api.groq.com/openai/v1",
        model,
        "GROQ_API_KEY",
        timeout_s=60.0,
        extra_body={"reasoning_effort": "low"},  # gpt-oss: keep reasoning tokens small
    )
    return CappedProvider(p, "groq", ledger)


def build_chain(order: tuple[str, ...], ledger: UsageLedger) -> list[Provider]:
    chain: list[Provider] = []
    for fam in order:
        if fam == "gemini":
            chain.append(CappedProvider(GeminiProvider(GEMINI_MODEL), "gemini", ledger))
        elif fam == "groq":
            chain += [_groq(GROQ_PRIMARY, ledger), _groq(GROQ_FALLBACK, ledger)]
        else:
            raise ValueError(f"unknown provider family {fam!r}")
    return chain


def build_live_gateway(
    fixtures_path: Path,
    order: tuple[str, ...] = ("groq", "gemini"),
    max_tokens: int | None = 40_000,
    usage_path: Path | None = None,
) -> Gateway:
    """Record-mode gateway: cache hits cost nothing, misses call the capped providers."""
    load_llm_keys()
    ledger = UsageLedger(usage_path or USAGE_PATH)
    return Gateway(
        providers=build_chain(order, ledger),
        mode="record",
        fixtures=Fixtures(fixtures_path),
        budget=Budget(max_tokens=max_tokens),
        max_retries=2,
    )
