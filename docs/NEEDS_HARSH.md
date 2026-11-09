# Needs Harsh (true walls only)

Everything that CI can do (Docker, compose, Postgres/arq, sandbox containers) already runs there, so
it is not listed. `E2B_API_KEY` and `HF_TOKEN` ARE present in `.env` (indented lines) and in use.

| # | Question | Options | Recommendation | Resume |
|---|---|---|---|---|
| 1 | Hugging Face returned HTTP 402 for a free Docker Space ("requires a PRO subscription"). | upgrade the HF account / use a free Gradio or Streamlit Space or the static site (run 10 tries these) | Keep the free options; upgrade only if the Docker image itself matters. | `PYTHONUTF8=1 .venv/Scripts/python.exe scripts/deploy_space.py` after upgrading |
| 2 | The MinIO image still cannot be pulled on the runner (moto S3 stand-in in CI). | pin another registry/tag or a mirror / keep moto | Keep moto unless real MinIO behaviour matters. | edit the MinIO service image in `.github/workflows/infra.yml` |
| 3 | No cloud-deploy account: deploy is local-only (packaged predict service). | provide a cloud account and budget / stay local | Stay local. | add a deploy backend under `mcp_servers/deploy` |
