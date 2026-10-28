# Known gaps (checks that could not run on this machine)

| Gap | Why | Run later with |
|---|---|---|
| docker compose never started | Docker not installed | `python scripts/tasks.py up` then `python scripts/tasks.py test-integration` |
| Scorer container cannot see `scorer_data` at runtime | needs Docker | integration test in the compose test target; a static check exists (`test_labels_not_in_worker_mount`) |
| gitleaks | binary not installed; regex fallback used | `gitleaks detect --config .gitleaks.toml --no-banner` |
| CI workflow never executed | no GitHub remote | push the repo and open a PR |
| MCP tool-manifest pinning (PRD S12.4) | scheduled for S12 | n/a |
| Leakage detector precision on real data | see ADR-006 limitation 3 | add a real-data dev partition, re-tune, re-freeze |
