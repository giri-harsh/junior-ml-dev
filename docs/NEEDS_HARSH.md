# Needs Harsh (true walls only)

Everything that CI can do (Docker, compose, Postgres/arq, sandbox containers) already runs there, so
it is not listed. The live demo runs on Render free (no Hugging Face Space needed); the maintainer email in commit metadata stays as is.

| # | Question | Options | Recommendation | Resume |
|---|---|---|---|---|
| 2 | The MinIO image still cannot be pulled on the runner (moto S3 stand-in in CI). | pin another registry/tag or a mirror / keep moto | Keep moto unless real MinIO behaviour matters. | edit the MinIO service image in `.github/workflows/infra.yml` |
| 3 | No cloud-deploy account: deploy is local-only (packaged predict service). | provide a cloud account and budget / stay local | Stay local. | add a deploy backend under `mcp_servers/deploy` |
