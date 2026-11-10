# Needs Harsh (true walls only)

Everything that CI can do (Docker, compose, Postgres/arq, sandbox containers) already runs there, so
it is not listed. The live demo runs on Render free (no Hugging Face Space needed); the maintainer email in commit metadata stays as is.

| # | Question | Options | Recommendation | Resume |
|---|---|---|---|---|
| 2 | The MinIO image still cannot be pulled on the runner (moto S3 stand-in in CI). | pin another registry/tag or a mirror / keep moto | Keep moto unless real MinIO behaviour matters. | edit the MinIO service image in `.github/workflows/infra.yml` |
| 3 | No cloud-deploy account: deploy is local-only (packaged predict service). | provide a cloud account and budget / stay local | Stay local. | add a deploy backend under `mcp_servers/deploy` |
| 4 | GitHub Actions cannot run for this account: jobs fail in ~2 s with 0 steps and the annotation "The job was not started because your account is locked due to a billing issue." (workflow_dispatch of ci/infra/web on 2026-11-10 after the repo went public, runs 42748248801, 42748253418, 42748258808). | fix the billing/payment issue on the GitHub account / keep CI local-only | Settings > Billing and plans. | after fixing: `gh workflow run ci --ref main`, then infra and web |
