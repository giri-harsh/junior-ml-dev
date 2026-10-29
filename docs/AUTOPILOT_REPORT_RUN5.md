=== AUTOPILOT REPORT RUN 5 ===
Probe: repo .env has GROQ/GEMINI keys (names only; allowlist loader), no E2B key. gh authenticated, repo giri-harsh/junior-ml-dev private. Docker only on GitHub Actions runners; nothing installed on this PC except pip packages in the venv (fakeredis, pytest-timeout, opentelemetry-sdk + OTLP exporter).

Implemented:
| Sprint | Status | Tag |
|---|---|---|
| S21 Docker via GitHub Actions (ci.yml, infra.yml, Docker sandbox backend, sandboxed feature step, kill/resume) | done, CI green | s21-done |
| S22 CV selection + 1-SE rule, LLM planner v2 (dev only) | done | s22-done |
| S23 v4 benchmark (10 unseen tasks, >= 2,000 test rows), 4 arms, leakage scan | done | agent-frozen-v4, eval-v4-done |
| S24 explainability, LLM critic, OpenTelemetry, README | done | s24-done |
Not done: E2B (no key). The real-LLM injection suite was not rerun in run 5 (run 4 result stands).

Verification: local gate before every push: ruff, ruff format --check, mypy, pytest -m "not infra and not llm and not compose" = 391 passed, secret scan clean. CI: last runs 40921824749 (ci) and 40921824753 (infra) both success. Earlier failures were real and fixed: YAML colon, MinIO images/binaries no longer pullable (S3 service is now a moto stand-in), gitleaks false positive on cassette hashes, mlflow in app profile, httpx/joblib/scipy missing from runtime deps, Linux path guard rejecting absolute paths, numpy stub differences, FLAML/LightGBM rejecting "fLength:"-style names. CI budget: 18 workflow runs listed this run (<=20), about 77 minutes wall (<=400). I merged one commit with a red test once (fixed within minutes, decision log); otherwise gates preceded merges.

Infra results (CI, real services): Postgres store contract PASS; arq worker executes an agent run into Postgres PASS; S3 object store round trip PASS (moto, not MinIO); generated predict-service container /health + /predict equals in-process predictions PASS; Docker sandbox: normal code + output files, network blocked, writes outside workdir denied, fork bomb contained by pids limit, timeout kills the container, agent-written feature code end to end PASS; compose kill test PASS: worker container `docker kill`ed mid-run, restarted, no step repeated, contiguous checkpoints, same chosen family and validation score as an uninterrupted run (arq job timeout 30 s for re-delivery).

v4 numbers (agent_v4_scripted.json, agent_v4_llm.json; scorer test scores, n=10 tasks, 9 with a defined normalized score because ailerons' FLAML-dummy gap is ~0; FLAML = 1; 95% bootstrap CIs):
- Linear 0.708 [0.522, 0.873].
- SCRIPTED planner (no LLM): 0.988 [0.954, 1.016]; vs linear +0.279 [0.122, 0.461]; vs FLAML -0.012 [-0.046, 0.016]; pass vs linear 10/10 (Wilson 0.72-1.00).
- REAL-LLM planner v2 (Groq gpt-oss, Gemini spill-over): 0.978 [0.939, 1.014]; vs linear +0.270 [0.122, 0.441]; vs FLAML -0.022 [-0.061, 0.014]; pass 10/10.
- Paired LLM minus scripted: -0.009 [-0.026, 0.001]: no gain from the LLM; neither arm is distinguishable from FLAML.
- LLM arm cost: 50 requests, 20,722 tokens, $0 (free tiers), 38/39 proposals valid first try, 1 repair, 0 step fallbacks; wall 18-356 s per task (scripted 55-409 s).
- Reviewer: scripted arm 1 REQUEST_CHANGES (ailerons: leakage detection hit its time budget, so leakage_checked failed); LLM arm 0. Brazilian_houses' target is nearly a linear sum of other columns (linear RMSE 12.9, FLAML 298.7): the detector missed it, kept as is.
- v1-v3 stay historical; none was rerun. Per-task differences below ~0.02 are noise.

S22 dev before/after (5 dev tasks, real LLM, 37 of 60 allowed requests): proposal fallbacks 8/17 (47%, planner v1 + holdout) -> 0/20 (0%, planner v2 + CV). Scores equal within noise (normalized 1.26 vs 1.21; dev is easy). Scripted holdout 1.20 vs scripted CV 1.27, same caveat.

Leakage v4: scan of the 10 v4 training sets found 1 medium/high finding: jm1 duplicate_rows = TRUE POSITIVE (1463 exact duplicate rows of 8708, 67 duplicate groups with conflicting labels; benchmarks/adjudication_real_v4.json). The other 9 had none. leakage_v2.json (run 4) is the current headline for detector recall.

Critic (advisory, real LLM, <=30 requests): agreement with the rule-based reviewer 9/19 = 0.47 [0.27, 0.68]; it called REQUEST_CHANGES on 10 runs the rules approved (mostly train-vs-CV gaps of tree models) and agreed on the one run the rules flagged. 31 requests used (cap overshoot by one repair), 19 of 20 runs covered.

Requests per provider (UTC day): Groq 150/150 (cap reached exactly; the chain then used Gemini), Gemini 37/150; 2 s spacing enforced; cassettes make reruns free.

Decisions added: 109-118 (see docs/DECISIONS.md). Skipped/not run: E2B; real-MinIO verification; real-LLM injection rerun; calibration of the critic prompt.
Remaining issues: see docs/KNOWN_GAPS.md (linear-combination leakage, detector time budget on ailerons, critic over-strictness, moto stand-in, E2B).

Failures + handling: listed above under Verification (each fixed in code, not by skipping tests); the benchmark FLAML names bug was fixed before any v4 agent run.

Git: branch main (work done directly with gates; no remote branches), tags s21-done, s22-done, s24-done, agent-frozen-v4, eval-v4-done; remote https://github.com/giri-harsh/junior-ml-dev private=true; pushed. Attribution check (local and remote history, last 100 commits): 0 hits for Claude/Anthropic/Co-Authored-By/Generated with; single author Harsh Giri.
WALL: E2B needs an E2B_API_KEY (create one at e2b.dev, put it in .env). Nothing else.
Next steps: calibrate the critic on dev; raise the leakage time budget and add a linear-combination check (new partition v5); run real MinIO in CI; E2B.
Estimated PRD completion: about 70% by sprint count (estimate, not measured).
