# Needs Harsh (true walls only)

Everything that CI can do (Docker, compose, Postgres/arq, sandbox containers) already runs there, so
it is not listed.

| # | Question | Options | Recommendation | Resume |
|---|---|---|---|---|
| 1 | E2B backend (run 8 part A) NOT started: `E2B_API_KEY` is absent from `.env` (the run-8 brief carried the placeholder `<paste e2b key>`, not a key). | add the real key / drop the backend | Add the key. | append `E2B_API_KEY=<key>` to `.env`, then re-run the run-8 brief, part A |
| 2 | Live demo on Hugging Face Spaces (run 8 part B) NOT started: `HF_TOKEN` is absent from `.env` (placeholder `<paste hf token>` in the brief). Also pick `DEMO_PRIVATE` (default public). | add a write-scope token / skip the demo | Add the token. | append `HF_TOKEN=<token>` (and optionally `DEMO_PRIVATE=1`) to `.env`, then re-run the run-8 brief, part B |
| 3 | The MinIO image still cannot be pulled on the runner (moto S3 stand-in in CI). | pin another registry/tag or a mirror / keep moto | Keep moto unless real MinIO behaviour matters. | edit the MinIO service image in `.github/workflows/infra.yml` |
| 4 | No cloud-deploy account: deploy is local-only (packaged predict service). | provide a cloud account and budget / stay local | Stay local. | add a deploy backend under `mcp_servers/deploy` |
| 5 | The injection completion (evasion DEV, fresh held-out, 5 injected runs) needs the LLM caps to reset, no human input. | none | run after 00:00 UTC 2026-10-31 | commands in docs/PROGRESS.md |
