# Needs Harsh (items the autopilot could not do alone)

| # | Question | Options | Recommendation | Resume |
|---|---|---|---|---|
| 1 | Docker Desktop is not installed, so compose/sandbox-in-container paths run only in CI. | install Docker Desktop locally / keep CI-only | Install it; then the infra suite runs locally. | `python scripts/tasks.py up app` then `python scripts/tasks.py test-infra` |
| 2 | No E2B API key, so the E2B sandbox backend has never been exercised. | create a key at e2b.dev / drop the backend | Create a key if hosted sandboxes matter. | set `E2B_API_KEY`, run the sandbox tests against the E2B backend |
| 3 | The MinIO image could not be pulled on the runner (moto S3 stand-in is used in CI). | pin another registry/tag / keep moto | Keep moto unless real MinIO behaviour matters. | edit `.github/workflows/infra.yml` service image |
| 4 | Release v0.1.0 makes the first GitHub release of a private repo. | publish / hold | Publish (private repo, notes from CHANGELOG). | `gh release create v0.1.0 --notes-file <(uv run python scripts/gen_changelog.py --notes v0.1.0)` |
