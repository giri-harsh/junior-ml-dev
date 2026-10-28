"""Provider adapters; HTTP providers take an injectable httpx transport (no network in tests).

Env vars (see .env.example): GROQ_API_KEY, GEMINI_API_KEY, OLLAMA_BASE_URL. Without a key a
provider reports itself unavailable and the gateway moves on; nothing is invented.
"""

from __future__ import annotations

import os
from collections.abc import Callable
from typing import Any, Protocol

import httpx

from harness.gateway.models import LLMRequest, LLMResponse, ProviderError, Usage


class Provider(Protocol):
    name: str
    paid: bool

    def available(self) -> bool: ...
    def complete(self, req: LLMRequest) -> LLMResponse: ...


class MockProvider:
    """Deterministic offline provider. `fn(request, call_index)` may raise ProviderError."""

    paid = False

    def __init__(
        self, fn: Callable[[LLMRequest, int], str] | None = None, name: str = "mock"
    ) -> None:
        self.name = name
        self.calls = 0
        self._fn = fn or (lambda req, i: "mock response")

    def available(self) -> bool:
        return True

    def complete(self, req: LLMRequest) -> LLMResponse:
        i = self.calls
        self.calls += 1
        text = self._fn(req, i)
        n_in = sum(len(m.content.split()) for m in req.messages)
        return LLMResponse(
            text=text,
            provider=self.name,
            model=req.model or "mock-1",
            usage=Usage(prompt_tokens=n_in, completion_tokens=len(text.split())),
        )


def _raise_for(resp: httpx.Response) -> None:
    if resp.status_code < 400:
        return
    retryable = resp.status_code in {408, 409, 425, 429} or resp.status_code >= 500
    raise ProviderError(f"HTTP {resp.status_code}", retryable=retryable, status=resp.status_code)


class OpenAICompatProvider:
    """Groq and Ollama both expose /chat/completions in the OpenAI shape."""

    def __init__(
        self,
        name: str,
        base_url: str,
        model: str,
        api_key_env: str | None,
        *,
        paid: bool = False,
        usd_per_1k_tokens: float = 0.0,
        transport: httpx.BaseTransport | None = None,
        timeout_s: float = 30.0,
    ) -> None:
        self.name, self.base_url, self.model = name, base_url.rstrip("/"), model
        self.api_key_env, self.paid, self.price = api_key_env, paid, usd_per_1k_tokens
        self._client = httpx.Client(transport=transport, timeout=timeout_s)

    def available(self) -> bool:
        return self.api_key_env is None or bool(os.environ.get(self.api_key_env))

    def complete(self, req: LLMRequest) -> LLMResponse:
        headers = {}
        if self.api_key_env:
            headers["Authorization"] = f"Bearer {os.environ[self.api_key_env]}"
        body: dict[str, Any] = {
            "model": req.model or self.model,
            "messages": [m.model_dump() for m in req.messages],
            "temperature": req.temperature,
            "max_tokens": req.max_tokens,
        }
        try:
            resp = self._client.post(
                f"{self.base_url}/chat/completions", json=body, headers=headers
            )
        except httpx.TimeoutException as exc:
            raise ProviderError("timeout", retryable=True) from exc
        except httpx.HTTPError as exc:
            raise ProviderError(type(exc).__name__, retryable=True) from exc
        _raise_for(resp)
        data = resp.json()
        usage = data.get("usage", {})
        u = Usage(
            prompt_tokens=int(usage.get("prompt_tokens", 0)),
            completion_tokens=int(usage.get("completion_tokens", 0)),
        )
        return LLMResponse(
            text=data["choices"][0]["message"]["content"],
            provider=self.name,
            model=body["model"],
            usage=u,
            cost_usd=u.total / 1000 * self.price,
        )


class GeminiProvider:
    """Google Generative Language REST API (free tier)."""

    paid = False

    def __init__(
        self,
        model: str = "gemini-2.0-flash",
        transport: httpx.BaseTransport | None = None,
        timeout_s: float = 30.0,
    ) -> None:
        self.name, self.model = "gemini", model
        self._client = httpx.Client(transport=transport, timeout=timeout_s)

    def available(self) -> bool:
        return bool(os.environ.get("GEMINI_API_KEY"))

    def complete(self, req: LLMRequest) -> LLMResponse:
        key = os.environ["GEMINI_API_KEY"]
        url = (
            "https://generativelanguage.googleapis.com/v1beta/models/"
            f"{req.model or self.model}:generateContent"
        )
        body = {
            "contents": [
                {
                    "role": "model" if m.role == "assistant" else "user",
                    "parts": [{"text": m.content}],
                }
                for m in req.messages
            ],
            "generationConfig": {"temperature": req.temperature, "maxOutputTokens": req.max_tokens},
        }
        try:
            resp = self._client.post(url, json=body, headers={"x-goog-api-key": key})
        except httpx.HTTPError as exc:
            raise ProviderError(type(exc).__name__, retryable=True) from exc
        _raise_for(resp)
        data = resp.json()
        meta = data.get("usageMetadata", {})
        return LLMResponse(
            text=data["candidates"][0]["content"]["parts"][0]["text"],
            provider=self.name,
            model=req.model or self.model,
            usage=Usage(
                prompt_tokens=int(meta.get("promptTokenCount", 0)),
                completion_tokens=int(meta.get("candidatesTokenCount", 0)),
            ),
        )


def default_chain() -> list[Provider]:
    """Groq -> Gemini -> Ollama, each skipped by the gateway when unavailable."""
    return [
        OpenAICompatProvider(
            "groq", "https://api.groq.com/openai/v1", "openai/gpt-oss-20b", "GROQ_API_KEY"
        ),
        GeminiProvider(),
        OpenAICompatProvider(
            "ollama",
            os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434") + "/v1",
            "llama3.2",
            None,
        ),
    ]
