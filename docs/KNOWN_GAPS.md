# Known gaps (checks that could not run on this machine)

| Gap | Why | Run later with |
|---|---|---|
| docker compose never started | Docker not installed | `python scripts/tasks.py up` then `python scripts/tasks.py test-integration` |
| Scorer container cannot see `scorer_data` at runtime | needs Docker | integration test in the compose test target; a static check exists (`test_labels_not_in_worker_mount`) |
| gitleaks | binary not installed; regex fallback used | `gitleaks detect --config .gitleaks.toml --no-banner` |
| CI workflow never executed | no GitHub remote | push the repo and open a PR |
| MCP tool-manifest pinning (PRD S12.4) | scheduled for S12 | n/a |
| Leakage detector residual false positives (group probe on predictive low-cardinality ints; ordinal targets read as classes) | ADR-007 limitations 1-2 | extend real_dev, add structural entity check, re-tune, re-freeze (new hash, new eval partition needed) |
| ObjectStore is local filesystem only (MinIO/S3 STUB) | Docker/MinIO unavailable | implement `MinioObjectStore` against the protocol in `apps/api/store.py`, then `python scripts/tasks.py test-integration` |
| Profile job runs as a FastAPI background task (arq worker STUB) | Redis unavailable | arq worker arrives with the harness sprint |
| LLM providers never called for real (Groq/Gemini/Ollama) | no keys, no local model | set GROQ_API_KEY or GEMINI_API_KEY and record fixtures (ADR-010) |
| Sandbox egress/FS-escape/fork-bomb tests; LocalDockerBackend execution; E2B backend | no Docker, no E2B key | build image, set JMD_SANDBOX=docker, add integration tests (marker `integration`) |
