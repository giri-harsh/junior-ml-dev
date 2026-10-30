# Known gaps (current as of run 7)

Older rows describing checks that "never ran" were removed: compose, Postgres/arq, the Docker
sandbox suite, the kill-and-resume test and the generated predict service all run in CI
(`infra.yml`, green). What remains:

| Gap | Why | Resume |
|---|---|---|
| E2B backend never run | no `E2B_API_KEY` (NEEDS_HARSH 1) | create a key, run the sandbox suite against it |
| S3 in CI/compose is moto, not MinIO | MinIO images are not pullable on the runner (NEEDS_HARSH 2) | point `MINIO_ENDPOINT` at a real MinIO, rerun `tests/infra` |
| Deploy is local only | no cloud account (NEEDS_HARSH 3) | add a backend under `mcp_servers/deploy` |
| Local subprocess sandbox is not isolation (Windows job limits only) | by design for dev | use `JMD_SANDBOX=docker` |
| Hosted-runner load test shows 17.8% errors at 100 users | single-container API on a shared runner | add workers/pooling before claiming capacity |
| v5 LLM arm used 130 requests for 40 proposals (90 failed attempts) | gateway retried 429/5xx and did not record statuses | fixed in run 7 (decision 136); v5 is not rerun, new evaluations get a new freeze hash |
| Critic v3 fresh-set recall 10/15, false alarms 1/19, 4 clean items not run | 40-request cap; set design let numeric dissent through on 3 rule-fail items | a new, larger planted set (burned set cannot be reused) |
| Injection results are proposals from a wider action space than production | the production planner sees no dataset text | an end-to-end injected-run harness with the production tool set (5 runs done in run 7) |
| Per-task differences below ~0.02 are noise; test sets are small (v3-v5) | dataset sizes | add larger unseen tasks in a future partition |
| LLM planner v2 is statistically tied with the scripted one on v5 (paired +0.001, CI includes 0) | the LLM only chooses model-search order | a planner that uses more than family order |
| Leakage detector residual false positives (low-cardinality ints, ordinal targets) | ADR-007 limitations | extend dev data, add entity checks |
