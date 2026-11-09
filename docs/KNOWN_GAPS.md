# Known gaps (current as of run 7)

Older rows describing checks that "never ran" were removed: compose, Postgres/arq, the Docker
sandbox suite, the kill-and-resume test and the generated predict service all run in CI
(`infra.yml`, green). What remains:

| Gap | Why | Resume |
|---|---|---|
| E2B parquet paths not run live (2 tests skipped) | needs a custom E2B template with pyarrow; in-sandbox pip is impossible with internet off | build the template (`docs/ws/A.md`), then `JMD_E2B_PARQUET_TEMPLATE=... pytest tests/e2b` |
| E2B network deny is verified only from inside the VM (TCP handshake completes, no data/DNS); default template has passwordless sudo | provider behaviour | prefer a locked-down template; do not rely on E2B alone for hostile code |
| The live demo (Render free, 0.1 vCPU) skips the leakage detectors, runs without FLAML, sleeps when idle (cold start about 33 s, first run about 106 s) | the free CPU is about 22x slower than a laptop | a paid instance removes the cuts; the demo run is otherwise the real agent |
| GitHub Actions on the private repo end in `startup_failure` since 2026-11-09 (even manual dispatch of `web`) | not a workflow-file error (files unchanged since the last working run); likely an account/billing limit | check Settings > Billing > Actions; CI green is unverified for main HEAD |
| S3 in CI/compose is moto, not MinIO | MinIO images are not pullable on the runner (NEEDS_HARSH 2) | point `MINIO_ENDPOINT` at a real MinIO, rerun `tests/infra` |
| Deploy is local only | no cloud account (NEEDS_HARSH 3) | add a backend under `mcp_servers/deploy` |
| Local subprocess sandbox is not isolation (Windows job limits only) | by design for dev | use `JMD_SANDBOX=docker` |
| Hosted-runner load test shows 17.8% errors at 100 users | single-container API on a shared runner | add workers/pooling before claiming capacity |
| v5 LLM arm used 130 requests for 40 proposals (90 failed attempts) | gateway retried 429/5xx and did not record statuses | fixed in run 7 (decision 136); v5 is not rerun, new evaluations get a new freeze hash |
| Critic v3 does not catch rule-failed baseline margins (0/4 on set v2; 0/3 on v1) | the schema lets a numeric dissent stand, and the model dissents | tighten the schema (treat a failed `baseline_margin` as non-dissentable) and evaluate on a NEW set |
| Injection: the prompt scanner flags 1/14 novel evasions (8/8 on its tuning set); the 5 injected full runs never exposed the payload to the planner | planner sees no dataset text by design | a harness whose agent can actually read column names, plus a better scanner |
| Per-task differences below ~0.02 are noise; test sets are small (v3-v5) | dataset sizes | add larger unseen tasks in a future partition |
| LLM planner v2 is statistically tied with the scripted one on v5 (paired +0.001, CI includes 0) | the LLM only chooses model-search order | a planner that uses more than family order |
| Leakage detector residual false positives (low-cardinality ints, ordinal targets) | ADR-007 limitations | extend dev data, add entity checks |
