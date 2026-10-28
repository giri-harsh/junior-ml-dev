# ADR-010: LLM gateway (PRD S13)

Status: accepted (S8 of this run)

## Decision
Every LLM call goes through `harness/gateway/Gateway.complete`: cache (request hash) -> replay/record fixtures -> budget check -> provider chain (Groq, Gemini, Ollama; unavailable-without-key providers are skipped) with per-provider retries (full-jitter exponential backoff, only for retryable errors), a per-provider circuit breaker (closed / open / half-open with a single probe), and `AllProvidersDown` when nothing can answer, which callers turn into a deterministic fallback. `MAX_MONTHLY_USD` defaults to 0 and blocks any provider marked paid. Structured output validates against a Pydantic model with at most 2 repair rounds. Clock, sleep and RNG are injected, so tests run on fake time.

## Tested (17 unit tests, no network, no keys)
429 storm falls through the chain; breaker opens after N failures and a half-open probe recovers or re-opens; token and cost budgets are hard stops; identical requests hit the cache; record then replay is deterministic and offline; missing fixture raises; paid providers are blocked at $0; HTTP adapters parse OpenAI-shaped and map 429 to retryable (via httpx MockTransport).

## NOT RUN
No real Groq, Gemini or Ollama call has been made (no keys, no local model). Request/response shapes follow each provider's documented API but are verified only against mock transports. Resume: set `GROQ_API_KEY` / `GEMINI_API_KEY`, then call `Gateway(default_chain(), mode="record", fixtures=Fixtures(path))` once to record fixtures.
