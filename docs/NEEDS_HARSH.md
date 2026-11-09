# Needs Harsh (true walls only)

Everything that CI can do (Docker, compose, Postgres/arq, sandbox containers) already runs there, so
it is not listed. `E2B_API_KEY` and `HF_TOKEN` ARE present in `.env` (indented lines) and in use.

| # | Question | Options | Recommendation | Resume |
|---|---|---|---|---|
| 1 | Hugging Face returned HTTP 402 for a free Docker Space ("requires a PRO subscription"). | upgrade the HF account / use a free Gradio or Streamlit Space or the static site (run 10 tries these) | Keep the free options; upgrade only if the Docker image itself matters. | `PYTHONUTF8=1 .venv/Scripts/python.exe scripts/deploy_space.py` after upgrading |
| 2 | The MinIO image still cannot be pulled on the runner (moto S3 stand-in in CI). | pin another registry/tag or a mirror / keep moto | Keep moto unless real MinIO behaviour matters. | edit the MinIO service image in `.github/workflows/infra.yml` |
| 3 | No cloud-deploy account: deploy is local-only (packaged predict service). | provide a cloud account and budget / stay local | Stay local. | add a deploy backend under `mcp_servers/deploy` |
| 4 | GitHub Actions for the private repo fail at startup (`startup_failure`) since 2026-11-09: ci, web (manual dispatch) and push runs; Actions on the PUBLIC demo repo work. Likely billing/minutes limit on the account. | fix billing/spending limit / make CI local-only | Check Settings > Billing and plans > Actions usage. | after fixing: `gh workflow run ci --ref main` |
| 5 | The public demo repo's single commit exposes the real gmail address (commit metadata), same as the project's commits. | keep / republish with a GitHub noreply address | Your call; it is only metadata. | `python scripts/deploy_static.py publish` after changing the author constant |
