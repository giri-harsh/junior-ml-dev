# Needs Harsh (true walls only)

Everything that CI can do (Docker, compose, Postgres/arq, sandbox containers) already runs there, so
it is not listed. The live demo runs on Render free (no Hugging Face Space needed); the maintainer email in commit metadata stays as is.

| # | Question | Options | Recommendation | Resume |
|---|---|---|---|---|
| 2 | The MinIO image still cannot be pulled on the runner (moto S3 stand-in in CI). | pin another registry/tag or a mirror / keep moto | Keep moto unless real MinIO behaviour matters. | edit the MinIO service image in `.github/workflows/infra.yml` |
| 3 | No cloud-deploy account: deploy is local-only (packaged predict service). | provide a cloud account and budget / stay local | Stay local. | add a deploy backend under `mcp_servers/deploy` |
| 6 | **Done 2026-11-16.** `ml.harshgiri.site` is a verified Render custom domain (certificate issued) with a Namecheap `CNAME ml -> junior-ml-dev-demo.onrender.com`. | - | - | README and `LIVE_URL` now point at `https://ml.harshgiri.site`, with the Render URL as the fallback (`docs/ws/R.md`) |
| 7 | The static frontend (`apps/web/demo-static/`) is built but not deployed: `ml.harshgiri.site` still points at the Render backend. | deploy it on Vercel and move the domain / keep the backend-served pages | Deploy it: first paint no longer waits for the backend. | Vercel project with root `apps/web/demo-static` (env `DEMO_API_URL=https://junior-ml-dev-demo.onrender.com`); remove `ml.harshgiri.site` from Render, add it in Vercel, Namecheap `CNAME ml -> cname.vercel-dns.com`; then enable `keepalive` in Actions (`docs/ws/R.md`) |
