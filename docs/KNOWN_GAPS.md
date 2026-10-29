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
| Approvals/audit run on SQLite; Postgres + REVOKE variant not run; audit covers login and approvals only | no Postgres | port the two stores to Postgres, add integration tests, wire audit into every tool call |
| deploy: containers never started; FLAML models not bundleable | Docker unavailable; FLAML object needs repo classes | `docker compose -f data/deploy/<run>/<model>/docker-compose.yml up -d --build` then `curl localhost:8000/health` |
| Job queue is SQLite (arq + Redis STUB) | Redis/Postgres unavailable | implement `ArqJobQueue`, run tests/unit/test_queue.py contract against it |
| Agent tools run in-process (trusted service code); agent-written code path (sandbox-exec run_python) is not exercised by the scripted planner | no Docker/E2B isolation | set JMD_SANDBOX=docker once an image exists |
| Postgres run store, arq worker/queue, MinIO store, compose `app` profile (api+worker), `docker kill` resume test, generated predict-service container: code and `tests/infra` exist, NEVER RUN (no Docker/Postgres/Redis/MinIO). Compose file only YAML-validated; the minio healthcheck uses `curl`, which that image may lack | no Docker on this machine | `cp .env.example .env` (set JWT_SECRET, APPROVAL_SECRET), `python scripts/tasks.py up app`, `python scripts/tasks.py test-infra`; on failure `docker compose --profile app logs --tail 40 <svc>` |
| arq re-delivery after a killed worker waits for the in-progress key to expire (ARQ_JOB_TIMEOUT + 10 s) | arq semantics, unverified here | set ARQ_JOB_TIMEOUT=30 for the kill test |
| Docker/E2B sandbox backends still not run; subprocess sandbox has Windows job limits (2 GB, 2 processes, kill-on-close) but NO filesystem/network isolation | no Docker, no E2B key | build image, `JMD_SANDBOX=docker`, add `integration` tests |
| CI workflow (ruff, mypy, unit pytest, gitleaks, compose config, infra job) only parsed as YAML; `act` absent | no GitHub remote | push and open a PR |
| v2 post-hoc fixes not evaluated on held-out: strict id naming for numeric group candidates; reviewer `leakage_checked` | eval-once | needs a new freeze hash and an unseen partition |
| In v2 cpu_act, detect_leakage exceeded its 60 s budget (machine under light load); that run had no leakage check and the then-reviewer approved | timing sensitivity | rerun forbidden by eval-once; v3 would also raise the budget |
| LLM planner uses the LLM only for model-search choices; 21 of 35 proposals in the v3 LLM run were unusable (repeat or invalid family) and fell back to the script; it stopped the search early on kr-vs-kp and vowel and lost score there | design: prompts hold only numbers/family names | give the planner richer state (e.g. which families remain), still without dataset text |
| Free-tier keys are shared with a live demo: caps (150/day, 1 per 2 s per family) are enforced in code, usage persists in data/llm_usage.json (UTC day) | policy | raise only with the owner's agreement |
| v3 test sets are small (108-1639 rows): CIs are wide and per-task differences below ~0.02 are noise | dataset sizes | add larger unseen tasks in a future partition |
