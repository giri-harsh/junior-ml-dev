# Needs Harsh (true walls only)

Everything that CI can do (Docker, compose, Postgres/arq, sandbox containers) already runs there, so
it is not listed. These need an account, key or money:

| # | Question | Options | Recommendation | Resume |
|---|---|---|---|---|
| 1 | No E2B API key, so the E2B sandbox backend has never been exercised. | create a key at e2b.dev / drop the backend | Create a key only if hosted sandboxes matter. | set `E2B_API_KEY`, run the sandbox tests against the E2B backend |
| 2 | The MinIO image still cannot be pulled on the runner (moto S3 stand-in in CI). | pin another registry/tag or a self-hosted mirror / keep moto | Keep moto unless real MinIO behaviour matters. | edit the MinIO service image in `.github/workflows/infra.yml` |
| 3 | No cloud-deploy account: deploy is local-only (packaged predict service). | provide a cloud account and budget / stay local | Stay local; a cloud target needs your account. | add a deploy backend under `mcp_servers/deploy` |
