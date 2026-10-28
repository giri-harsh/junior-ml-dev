# junior-ml-dev (P2) — Phased PRD

Owner: Harsh Giri · Source of truth for scope: `docs/SPEC.md` (the spec) as amended by the decisions in §0 · Unit of work: one **sprint = 2–3 working days** (a working day ≈ 3 h part-time) · No hard deadline: scope is never compressed to fit a date.

---

## 0. Decisions that override the spec

| Area | Decision |
|---|---|
| MCP servers | 4: `sandbox-exec`, `data-tools` (viz merged in), `experiments` (MLflow), `deploy`. `docs-rag`, `github` → stretch |
| Durable execution | arq + Postgres checkpoints (step key `(run_id, step)`, idempotent) + DB heartbeat reaper |
| Sandbox | E2B, internet disabled. Backend interface also has a `LocalDocker` impl (`--network none`, read-only, non-root) for offline dev and as fallback |
| Infra | docker-compose (`micro` + `full` profiles), Langfuse (full only), `/metrics` + 1 Grafana dashboard. No K8s, Loki, Temporal |
| Auth | Single env-configured admin login; single-use approval tokens; hash-chained audit log. No OIDC/RBAC/RLS |
| Benchmark | Tabular classification + regression only (imbalanced = subset). Time-series, text → stretch |
| Percentile | Cut. Normalized score `(agent − dummy)/(flaml − dummy)` |
| Stretch | Ask-your-data, fairness, drift, ticket→PR, UMAP, docs-rag, github MCP, time-series/text, K8s |
| Pass | hidden-test metric ≥ linear baseline × 1.02 (relative) **and** no unresolved high-severity leakage finding. Also report normalized score |
| Scorer | Never unpickles agent artifacts. Fresh no-network sandbox gets pipeline + test **features only**, returns predictions; scorer scores against labels that never leave it |

---

## 1. Product summary

**Problem.** AutoML tools and LLM agents report inflated scores (leakage, contaminated splits, overfit CV), and nobody can verify the agent's judgement.

**User.** Primary: a data-literate dev with a CSV and a goal. Evaluator: a recruiter/interviewer who needs to see autonomy, judgement and measured honesty in 90 seconds.

**USP.** "The junior ML engineer that shows its work and catches its own mistakes": hidden-test scoring the agent cannot reach, a reviewer gate, a planted-bug benchmark with clean twins that measures bug-catch and false-alarm rates, and claim-verified captions.

**Non-goals (deliberately not built).** Deep learning/GPU, LLM training, time-series and text tasks, OIDC/RBAC/multi-tenancy, K8s/Loki/Temporal, Kaggle percentile, UMAP, fairness audit, drift monitoring, ticket→PR, Ask-your-data, docs-rag, github MCP. All stretch except where noted.

**Choices flagged (one line each).**
- Pass rule: spec's "×1.02" is impossible when linear AUC ≥ 0.98, so: if linear ≥ 0.98 (or error ≤ 2% of scale) pass = "not worse than linear". Documented in ADR-005.
- CV evaluation is a preinstalled `jmd_runtime.cv_evaluate` library in the sandbox template, not LLM-written, so splitting/metrics are deterministic and leakage-by-construction is harder.
- Charts: Vega-Lite via Altair (JSON-native, `vl-convert-python` for SVG/PNG export) over Plotly.
- Data Story HTML embeds pre-rendered SVG + spec JSON (self-contained, no JS); interactivity lives in the web UI.
- PDF: WeasyPrint (pure Python + system libs) over headless-browser printing.
- Deploy image is built by the host Docker daemon (E2B can't run Docker); spec says "in the sandbox".
- Injection classifier = heuristics + alias-renaming of untrusted names, no paid judge model.
- pandas + DuckDB only (no Polars) for sklearn compatibility.

---

## 2. Sprint roadmap

| # | Name | Goal | Depends | Days | Spec phase |
|---|---|---|---|---|---|
| S1 | Foundations | Repo, compose, CI, trajectory schema | — | 2 | 0 |
| S2 | Tasks + scorer core | Registry, deterministic splits, metrics, scorer service, 10 datasets | S1 | 3 | 0 |
| S3 | Baselines + bug generator | Dummy/linear/FLAML, normalized score, CIs, planted bugs + clean twins | S2 | 3 | 0/10 |
| S4 | Ingest + profile + quality | Upload, profile.json, Quality Scorecard | S1 | 3 | 1 |
| S5 | Insight mining | Typed insights, sampled pairwise stats | S4 | 3 | 1 |
| S6 | Charts | Candidate generation, ranking, Vega-Lite specs | S5 | 3 | 1 |
| S7 | Captions + verifier | Grounded captions, claim verifier, HTML export | S6 | 3 | 1 |
| S8 | Leakage Detective | Detectors, before/after, measured on bug suite | S3,S5 | 3 | 1 |
| S9 | Minimal UI | Upload → Story → Leakage card (**Milestone M1**) | S7,S8 | 3 | 1 |
| S10 | sandbox-exec MCP | E2B backend, LocalDocker backend, code policy | S1 | 3 | 2 |
| S11 | Scorer sandbox protocol | Predict-in-sandbox scoring + isolation tests | S2,S10 | 3 | 2 |
| S12 | data-tools + experiments MCP | Profile/query/viz tools, MLflow tools, pinned manifests | S7,S10 | 3 | 2 |
| S13 | LLM gateway | Fallback, retry, breaker, cache, budgets, recorded mode | S7 | 3 | 2/4 |
| S14 | Harness core | RunState, arq, checkpoints, loop, heartbeat reaper, chaos test | S1,S13 | 3 | 2/4 |
| S15 | Roles + modelling loop | Context packer, planner/analyst/modeller, 5-dataset runs | S11–S14 | 3 | 2 |
| S16 | Live events + first benchmark | SSE, Run Theater v1, 10-dataset benchmark (**M2**) | S15 | 3 | 2/5 |
| S17 | Reviewer: deterministic | Split/pipeline/baseline/gap checks | S15 | 3 | 3 |
| S18 | Reviewer: sub-agent | LLM reviewer, loop-back, `review_mode` switch | S17 | 2 | 3 |
| S19 | Explainability + results | SHAP, PDP, error slices, results page | S16 | 3 | 3 |
| S20 | deploy MCP | FastAPI gen, Docker, contract tests, model card | S17 | 3 | 3 |
| S21 | Bundle + PDF | Reproducibility bundle, stakeholder PDF (**M3**) | S19,S20 | 2 | 3 |
| S22 | Injection defence | Untrusted-data handling + injection suite | S15 | 3 | 4 |
| S23 | Approvals + audit + auth | Single-use tokens, hash chain, admin login | S20 | 3 | 4 |
| S24 | Observability + load | OTel, Langfuse, metrics, dashboard, backpressure, load test (**M4**) | S14 | 3 | 4 |
| S25 | Benchmark scale-up | 30 datasets, planted-bug agent scoring, baselines | S18,S22 | 3 | 5 |
| S26 | Full benchmark | 3 models + FLAML, 2 ablations, CIs | S25 | 3 | 5 |
| S27 | Eval gate + pipelines + export | Blocking CI gate, Prefect flows, trajectory export | S26 | 3 | 5 |
| S28 | Polish + launch | Recruiter mode, landing, a11y/Lighthouse, README, demo video | S27 | 3 | 5 |

Total ≈ 81 working days ≈ 220–240 h, slightly above the 180–220 h estimate; the margin is the cost of not compressing. Stretch backlog (after S28): ST1 Ask-your-data, ST2 fairness, ST3 docs-rag + github MCP + ticket→PR, ST4 drift, ST5 time-series/text, ST6 K8s.

---

## 3. Sprint PRDs

Conventions used in every sprint: new code paths emit `TrajectoryEvent`s (test `test_emits_trajectory`); tests ship with the feature; any metric shown anywhere comes from `benchmarks/results/` or reads "pending"; `ruff`, `mypy`, `pytest`, `gitleaks` stay green.

---

### S1 — Foundations · 2d · Phase 0
**Goal / outcome:** fresh clone → `make up && make test` green; every future step has a place to log trajectories.
**Scope in:** monorepo skeleton, compose, CI, trajectory schema, results-writer. **Out:** any ML.
**Tasks**
- [ ] S1.1 Skeleton per spec §15 (only in-scope dirs); `uv` workspace, `pyproject.toml`, `ruff`, `mypy`, `pytest`, `Makefile` (`up`, `down`, `test`, `lint`).
- [ ] S1.2 `deploy/compose/docker-compose.yml` micro profile: postgres, redis, minio, mlflow; `full` profile adds langfuse.
- [ ] S1.3 `.github/workflows/ci.yml`: ruff, mypy, pytest, gitleaks. `.gitleaks.toml`, pre-commit hook.
- [ ] S1.4 `trajectory/`: `TrajectoryEvent` model, append-only JSONL writer, Postgres `events` table (Alembic), `emit()` helper.
- [ ] S1.5 `benchmarks/results_writer.py`: every result file stamped with command, git SHA, date, conditions (`llm: real|mocked|recorded`, `sandbox: e2b|local|fake`, `n`, machine id).
- [ ] S1.6 `docs/reference-machine.md` (your laptop specs), README skeleton with only `pending` placeholders, ADR-001 (architecture), ADR-015 (scope cuts = §0 table).
**Files:** `pyproject.toml`, `Makefile`, `deploy/compose/*`, `.github/workflows/ci.yml`, `trajectory/{models,writer,db}.py`, `benchmarks/results_writer.py`, `docs/adr/001*.md`.
**Models/APIs:** `TrajectoryEvent{run_id, seq, ts, kind: state|prompt|llm_output|tool_call|observation|decision|budget|pipeline_step, agent_version, prompt_hash?, payload, outcome_labels?}`; `GET /healthz`, `/readyz` stub.
**Acceptance:** compose healthy from clean clone; CI green on a PR; a pushed fake secret is caught by gitleaks; JSONL event round-trips through the schema.
**Tests:** unit (schema, writer ordering/`seq` monotonic), CI self-test (gitleaks fixture).
**Demo:** `make up`, emit 3 events, show JSONL + DB rows.
**Learning:** why append-only event logs; why typed schemas over free-form logs. Q: (1) Why store trajectories with outcome labels from day one? (2) What makes an event log replayable? (3) What does gitleaks catch that code review misses?
**Risk/fallback:** compose RAM pressure → drop mlflow/minio into `full` until S12.

---

### S2 — Task registry + scorer core · 3d · Phase 0
**Goal / outcome:** 10 datasets with fixed hidden test sets held only by the scorer.
**Scope in:** registry, fetch, splits, metrics, scorer service (labels + metric). **Out:** sandbox predict protocol (S11).
**Tasks**
- [ ] S2.1 `benchmarks/tasks/registry.yaml`: per task `name, source (OpenML by name; record dataset_id + licence at fetch), task_type, target, metric, group_col?, time_col?, role: dev|test|p3_heldout`. 10 tasks: mix of binary, multiclass, regression, ≥2 imbalanced (e.g. a churn, a fraud-like, an income set, a house-price set, a credit set; pick by name, don't invent IDs).
- [ ] S2.2 `benchmarks/fetch.py` (+ DVC tracking) writes `data/tasks/{name}/` raw.
- [ ] S2.3 `apps/scorer/splits.py`: deterministic seeded split (stratified / group / time-ordered by registry), content-hash manifest; train side → agent-visible store; test labels → `scorer_data/` volume only.
- [ ] S2.4 `apps/scorer/metrics.py`: `roc_auc, f1_macro, pr_auc, rmse, mae` (higher-is-better normalised direction flag).
- [ ] S2.5 Scorer FastAPI: `POST /v1/score-predictions` (predictions CSV `row_id,pred` → metric), run-token auth. Compose: scorer has its own volume/network; worker has no mount of it.
- [ ] S2.6 `p3_heldout` partition fixed now (≥2 of the 10; grows in S25). ADR-004 stub (scorer isolation).
**Files:** `benchmarks/tasks/`, `benchmarks/fetch.py`, `apps/scorer/*`.
**Acceptance:** split reproducible byte-for-byte (hash equal across two runs); metrics equal sklearn on fixtures; worker container cannot see `scorer_data` (test).
**Tests:** unit (splits, metrics), security `test_labels_not_in_worker_mount`.
**Demo:** `python -m benchmarks.fetch --all`; score a perfect and a dummy prediction file.
**Learning:** stratified vs group vs time splits; PR-AUC vs ROC-AUC; why hidden labels live in a separate service. Q: (1) When is a random split wrong, and what do you use instead? (2) Why PR-AUC for a 1% positive class? (3) How is "can't cheat" enforced here vs merely promised?
**Risk/fallback:** OpenML flakiness → cache raw files in DVC remote (local).

---

### S3 — Baselines + bug generator · 3d · Phase 0
**Goal / outcome:** the measuring stick (baselines, normalized score, CIs) and the planted-bug suite exist before any detector.
**Scope in:** baselines, metrics, generator. **Out:** agent runs.
**Tasks**
- [ ] S3.1 `benchmarks/baselines.py`: dummy (prior/mean), linear (LogReg / Ridge with scaling+OHE in a Pipeline), FLAML AutoML with `time_budget` param; scored through the scorer path.
- [ ] S3.2 `benchmarks/metrics.py`: normalized score (flag undefined when `|flaml − dummy|` tiny; exclude and count), pass rule incl. ceiling clause, percentile bootstrap CI over tasks (10k resamples, seeded).
- [ ] S3.3 `benchmarks/planted_bugs/generate.py`: bug types `target_proxy, duplicate_leak, temporal_leak, group_leak, id_correlated, label_noise, unit_mismatch, poisoned_name`; each emits bugged variant + **clean twin** + `labels.json {bug_type, columns, expected_detector}`; seeded, deterministic.
- [ ] S3.4 Partition variants into `dev` (tune thresholds) and `eval` (report once).
- [ ] S3.5 `benchmarks/run_benchmark.py` skeleton + baseline run on all 10 tasks → `benchmarks/results/baselines_v0.json` via results writer. ADR-005 (pass rule, normalized score).
**Files:** `benchmarks/{baselines,metrics,run_benchmark}.py`, `benchmarks/planted_bugs/*`.
**Acceptance:** baselines committed for 10 tasks with conditions block; generator output hash stable; for leakage-type bugs naive-CV(bugged) > naive-CV(twin) (asserted per variant).
**Tests:** unit (metrics, bootstrap on known samples), property (normalized score monotone in agent score), generator determinism.
**Demo:** table of dummy/linear/FLAML per task; one bugged-vs-twin score pair.
**Learning:** bootstrap CIs; why clean twins give a false-alarm rate; normalization pitfalls. Q: (1) What does a 95% bootstrap CI over tasks mean here and what's its n? (2) Why can normalized score blow up and how do you handle it? (3) Why tune detector thresholds on a different partition than you report on?
**Risk/fallback:** FLAML slow → fewer tasks at first, smaller `time_budget`; record budget in conditions.

---

### S4 — Ingestion, profiling, Quality Scorecard · 3d · Phase 1
**Goal / outcome:** upload a CSV → `profile.json` + 0–100 quality score with sub-scores.
**Scope in:** upload endpoint, profiling, scorecard. **Out:** insights, charts.
**Tasks**
- [ ] S4.1 `POST /v1/datasets` (multipart): extension/MIME/size (≤50 MB) check, content hash, store in MinIO, versioned by hash.
- [ ] S4.2 Schema inference + Pandera schema; PII regex scan (email/phone/ID-shaped) → flags only.
- [ ] S4.3 `datastory/profile.py`: semantic types (numeric, categorical, boolean, datetime, text, id, constant, high-card), per-column stats (missing, unique, quantiles, skew, kurtosis, zeros, IQR + robust-z outliers), dataset-level (rows, dup rows, class balance).
- [ ] S4.4 `datastory/quality.py`: Completeness, Uniqueness, Validity, Consistency (case/spelling variants via normalized grouping), Timeliness, Leakage-risk placeholder (filled in S8); weights in `datastory/config.yaml`; each deduction links columns/rows + suggested fix.
- [ ] S4.5 `GET /v1/datasets/{id}/quality`; async profile job on arq (stub worker OK).
**Files:** `datastory/{profile,quality,types}.py`, `apps/api/routes/datasets.py`.
**Models/APIs:** `ColumnProfile`, `QualityReport{score, subscores, deductions[]}`; `POST /v1/datasets`, `GET /v1/datasets/{id}/quality`.
**Acceptance:** profiling 100k×50 ≤ 10 s on the reference machine (measured, committed); semantic types ≥ labelled fixtures; injected dirty cells (neg ages, "NY"/"New York") each cause a scorecard deduction.
**Tests:** unit; Hypothesis (profile never crashes on random frames; percents ∈ [0,100]); upload rejection (oversize, wrong type).
**Demo:** upload a messy CSV, show the scorecard and the deductions.
**Learning:** type inference heuristics; IQR vs robust z; skew/kurtosis. Q: (1) How do you decide a column is an ID, and why exclude it? (2) When does IQR flag false outliers? (3) Why is a quality score a decision aid, not a truth?
**Risk/fallback:** consistency checks sprawl → ship case/whitespace variants only.

---

### S5 — Insight mining · 3d · Phase 1
**Goal / outcome:** typed `Insight` objects with importance scores and a facts dict (the only numbers captions may use).
**Scope in:** detectors, sampled pairwise stats. **Out:** charts, captions.
**Tasks**
- [ ] S5.1 `datastory/sampling.py`: stratified ≤20k-row sample; `sample_meta{n_full, n_sample}` carried into output.
- [ ] S5.2 Target MI (full data via sampled MI estimator), top-k=15 features by MI selected for pairwise work; Pearson/Spearman, Cramér's V, correlation ratio η on the k features only.
- [ ] S5.3 `datastory/insights.py` detectors: imbalance, skew, correlation, id_column, missing_pattern (co-missingness), outlier, segment (rate by category with Wilson CI, min support, lift threshold), seasonality (weekly autocorr, only if datetime), leakage_risk hook (MI spike, consumed by S8).
- [ ] S5.4 Importance scoring function (config-driven, ADR-006 with sampling rationale).
- [ ] S5.5 `insights.json` writer; `GET /v1/datasets/{id}/story` returns insights (charts empty for now).
**Files:** `datastory/{sampling,insights,pairwise}.py`.
**Models/APIs:** `Insight` (spec §11).
**Acceptance:** profile + insights ≤ 22 s p95 on 100k×50 (budget leaves 8 s for charts+captions); every `facts` value reproducible by an independent recompute in tests; sample size surfaced.
**Tests:** unit on synthetic frames with known properties (planted skew, planted correlation, planted segment); golden snapshot of insights for 3 datasets.
**Demo:** print top-10 insights for churn-like data with importance.
**Learning:** MI vs correlation; Cramér's V and η; why sample pairwise stats; Wilson interval. Q: (1) Why top-k by MI before pairwise stats? (2) Why Spearman beside Pearson? (3) Why a CI on segment rates?
**Risk/fallback:** time budget missed → reduce k to 10 and sample to 10k; record in ADR-006.

---

### S6 — Chart candidates, ranking, Vega-Lite · 3d · Phase 1
**Goal / outcome:** 8–12 ranked chart specs per dataset, each mapped to an insight.
**Scope in:** templates, ranking, rendering. **Out:** captions.
**Tasks**
- [ ] S6.1 `datastory/charts/templates.py` (Altair): histogram+density, top-k+other bar, target balance, box-by-class (+density strip), rate-by-category with CI bars, clustered heatmap (order via `scipy.cluster.hierarchy`), missingness matrix + co-occurrence, time trend + rolling mean, MI bar, 2-D PCA scatter.
- [ ] S6.2 Insight→template mapping; server-side aggregation/sampling (≤5k points/chart).
- [ ] S6.3 Ranking = importance × clarity prior × novelty penalty (column-set Jaccard); top 8–12 to gallery, rest "More charts". ADR-007.
- [ ] S6.4 Deterministic alt text per template; SVG/PNG export via `vl-convert-python`.
- [ ] S6.5 `ChartSpec` persisted; story endpoint returns specs.
**Files:** `datastory/charts/*`, `datastory/ranking.py`.
**Acceptance:** 100% of specs compile under `vl-convert`; each spec ≤500 KB; 100% have alt text; no two gallery charts share an identical column set; charts stage ≤5 s.
**Tests:** unit (templates on fixtures), golden ranking snapshot, schema validation.
**Demo:** render the gallery to a static page of SVGs for 3 datasets.
**Learning:** grammar of graphics; why specs not images; chart-choice rules. Q: (1) Why is a spec better than a PNG here? (2) How does the novelty penalty prevent redundant charts? (3) Why aggregate server-side?
**Risk/fallback:** drop PCA scatter and co-occurrence heatmap first.

---

### S7 — Captions, claim verifier, HTML export · 3d · Phase 1
**Goal / outcome:** hallucination-proof captions and a downloadable self-contained report.
**Scope in:** thin LLM client, caption prompts, verifier, narrative, HTML. **Out:** full gateway (S13), PDF (S21).
**Tasks**
- [ ] S7.1 `harness/gateway/thin.py`: Groq (OpenAI-compatible) + Gemini + `mock` provider returning templated text; env-selected.
- [ ] S7.2 Caption prompt takes **only** the `facts` JSON; output schema `{caption, modelling_note}` (Pydantic).
- [ ] S7.3 `datastory/verify.py`: extract numbers (%, decimals, ×, k/M suffixes), match to `facts` with rounding tolerance or a derived-ratio rule; mismatch → one regeneration → templated fallback. ADR-008.
- [ ] S7.4 Story narrative: 5–8 findings + next steps from top insights, same verification.
- [ ] S7.5 Jinja2 self-contained HTML export (inline SVG + embedded spec JSON); `GET /v1/datasets/{id}/story.html`.
**Acceptance:** **0** unverified numeric claims across 10 datasets × all gallery charts; with LLM unavailable the story still completes with templated captions; captions stage ≤3 s p95 (templated) / measured with real LLM.
**Tests:** unit; **Hypothesis**: perturbing any number in a caption makes the verifier reject; fallback test (provider down); column names/cells passed to prompts are length-capped and delimited (pre-S22 minimum).
**Demo:** Story HTML for 3 datasets; show a rejected-and-regenerated caption in the log.
**Learning:** grounding vs RAG; why verification beats prompting. Q: (1) How does the verifier handle "about 4%" vs 4.2? (2) Why never give the LLM raw rows? (3) What's your fallback when verification keeps failing?
**Risk/fallback:** verifier false rejects → widen tolerance modestly; log reject rate as a metric.

---

### S8 — Leakage Detective · 3d · Phase 1
**Goal / outcome:** detectors with measured catch and false-alarm rates; before/after score per finding.
**Scope in:** all detectors except `encoding` (static check lands S17). **Out:** agent integration.
**Tasks**
- [ ] S8.1 `leakage/target_proxy.py`: each feature alone, 3-fold shallow tree / logistic CV, flag when score exceeds a dummy-relative threshold.
- [ ] S8.2 `leakage/mi_spike.py` (robust z of MI vs others) and `leakage/post_outcome.py` (name hints: refund, cancel, closed, outcome, result…; plus temporal ordering where a time column exists).
- [ ] S8.3 `leakage/split_overlap.py`: exact row hash + MinHash LSH (`datasketch`); `temporal.py` (random-vs-time-split gap); `group.py` (random-vs-GroupKFold gap on id-like columns).
- [ ] S8.4 `LeakageFinding` with `score_before/after` (drop columns, re-CV); wire the Quality "leakage risk" sub-score and the story's leakage insight.
- [ ] S8.5 Tune thresholds on **dev** partition → freeze `leakage/thresholds.yaml` (commit) → evaluate once on **eval** + clean twins → `benchmarks/results/leakage_v1.json` (catch rate by bug type, false-alarm rate, Wilson CIs, thresholds hash).
**Acceptance:** results file committed with thresholds hash and honest rates (the spec's ≥90% is a target, reported as measured); `GET /v1/datasets/{id}/leakage`; eval-partition run happens after thresholds commit (script asserts hash match).
**Tests:** unit per detector; property (no finding on shuffled-label data); integration on generator outputs.
**Demo:** bugged vs twin: "0.99 → 0.81 AUC after removing `refund_issued`".
**Learning:** the five leakage routes; why CV gap detects group/time leakage. Q: (1) Walk through 5 ways leakage happens and which detector covers each. (2) Why would a high single-feature score not always be leakage? (3) How do you know your false-alarm rate is honest?
**Risk/fallback:** low catch on some type → report it, don't tune on eval; add to open risks.

---

### S9 — Minimal UI · 3d · Phase 1 · **Milestone M1**
**Goal / outcome:** upload a CSV in a browser, see Story + Quality + Leakage before/after card.
**Scope in:** React+TS+Vite pages: Upload, Story, Leakage panel; sample-dataset button. **Out:** runs, theater.
**Tasks**
- [ ] S9.1 `apps/web` scaffold (Vite, TanStack Query, `vega-embed`), API client from OpenAPI types.
- [ ] S9.2 Upload page + progress polling (arq job status).
- [ ] S9.3 Story page: progressive gallery, narrative, quality radial (Vega-Lite arc), "More charts".
- [ ] S9.4 Leakage panel with the before/after card.
- [ ] S9.5 Playwright e2e: upload sample → story visible; time-to-story measured on 100k×50 synthetic → `benchmarks/results/datastory_latency_v1.json`.
**Acceptance:** end-to-end Data Story ≤30 s p95 on 100k×50 (measured); dark/light; no inline scripts.
**Tests:** e2e (Playwright), component smoke.
**Demo:** steps 1–3 of the §23 demo script on the sample churn set.
**Learning:** end-to-end latency budgeting. Q: (1) Where does the 30 s go, stage by stage? (2) What would you cut if it missed? (3) Why is the sample size shown in the UI?
**Risk/fallback:** UI time-sink → no styling beyond a token set; polish deferred to S28.

---

### S10 — sandbox-exec MCP · 3d · Phase 2
**Goal / outcome:** run untrusted Python safely behind an MCP server.
**Scope in:** MCP server, E2B + LocalDocker backends, code policy. **Out:** scorer protocol.
**Tasks**
- [ ] S10.1 `mcp_servers/sandbox_exec/` with official `mcp` SDK, streamable HTTP, bearer auth; tools `run_python(code, timeout_s)`, `list_files`, `read_file`, `upload_workspace(files)`, `install_allowed(pkg)` (allow-list: sklearn, lightgbm, xgboost, catboost, optuna, shap, scipy, pandas, numpy).
- [ ] S10.2 `SandboxBackend` interface; `E2BBackend` (internet disabled at creation; verify the current SDK parameter name in the docs) and `LocalDockerBackend` (`--network none --read-only`, non-root, cpu/mem caps).
- [ ] S10.3 Custom E2B template with ML libs preinstalled, `jmd_runtime` package (`cv_evaluate`, metric printers) and pinned `requirements.lock`.
- [ ] S10.4 `harness/policies/code_policy.py`: AST check — banned imports (`socket, subprocess, requests, urllib, http, ftplib, smtplib, ctypes`), banned calls (`eval, exec, compile, __import__, os.system, os.popen`), `open()` only under `/workspace`, no paths matching hidden/scorer names.
- [ ] S10.5 Fresh sandbox per run; timeout kill; ADR-002.
**Acceptance:** egress attempts (socket, `curl`, pip to arbitrary host) fail inside the sandbox; policy blocks every banned fixture; timeouts kill within cap.
**Tests:** security (egress, FS escape, banned imports, fork bomb contained), integration per backend, MCP contract test.
**Demo:** run a training snippet; show a blocked `import socket`.
**Learning:** why policy checks plus isolation (defence in depth); MCP vs function calling. Q: (1) Why isn't an AST check sufficient alone? (2) What does MCP buy over plain function calling here? (3) What does a fresh sandbox per run protect against?
**Risk/fallback:** E2B credits low → default to LocalDocker for dev/CI, E2B for demo/benchmark.

---

### S11 — Scorer sandbox protocol · 3d · Phase 2
**Goal / outcome:** hidden-test scoring where the scorer never executes agent code in its own process.
**Tasks**
- [ ] S11.1 Artifact contract: `bundle/{pipeline.joblib, predict.py, requirements.lock}`; worker uploads to scorer.
- [ ] S11.2 Scorer starts its own no-network sandbox with the bundle + test **features only**, runs `predict.py`, reads `predictions.csv`.
- [ ] S11.3 Validate predictions (length, `row_id` set, finite, dtype); score vs labels in scorer memory.
- [ ] S11.4 One final score per `run_id` (409 on repeat) to stop hill-climbing the hidden set; dev feedback only via CV.
- [ ] S11.5 Isolation test suite; finalize ADR-004.
**Acceptance:** malicious pickle trying to read labels/network/scorer FS gets nothing and doesn't affect scorer; repeat scoring → 409; malformed predictions rejected with typed error.
**Tests:** security (malicious artifact), integration (good artifact scores equal to local reference), idempotency.
**Demo:** score a real baseline artifact; show the malicious one failing harmlessly.
**Learning:** pickle risk; train/serve skew; reward hacking. Q: (1) Why is unpickling in the scorer unsafe? (2) How does single-score-per-run prevent test-set overfitting? (3) What can a malicious `predict.py` still do, and what bounds it?
**Risk/fallback:** E2B cost → LocalDocker scorer backend for CI.

---

### S12 — data-tools + experiments MCP · 3d · Phase 2
**Goal / outcome:** the agent's two remaining toolboxes, with pinned manifests.
**Tasks**
- [ ] S12.1 `data_tools`: `profile_dataset`, `query(sql)` (DuckDB, read-only, row/time caps), `validate(schema)`, `sample_rows(n≤20, cell-truncated)`, `detect_pii`.
- [ ] S12.2 `data_tools` viz: `generate_chart_candidates`, `render_spec`, `caption_chart`, `verify_claims` (wrap S5–S7).
- [ ] S12.3 `experiments`: `log_run` (params, metrics, hypothesis tag, agent_version), `compare_runs`, `get_best`, `register_model` (stage `candidate`) over MLflow.
- [ ] S12.4 `tool_manifest.json` per server; harness refuses to start if descriptions' hashes differ from pinned values (tool-poisoning defence).
- [ ] S12.5 All servers write audit/trajectory events per call.
**Acceptance:** data-tools can't resolve any scorer/hidden path (test); SQL write attempts rejected; manifest tamper test fails startup.
**Tests:** integration (testcontainers: MLflow, MinIO), security (path traversal, DuckDB `COPY`/`ATTACH` blocked), contract tests.
**Demo:** query a dataset via MCP client; log and compare two runs in MLflow UI.
**Learning:** MLflow tracking vs registry; DuckDB safety. Q: (1) Why pin tool descriptions? (2) How do you stop SQL from touching files? (3) Why log a hypothesis with each run?
**Risk/fallback:** viz tools slip → keep inside datastory and expose in S15.

---

### S13 — LLM gateway · 3d · Phase 2/4
**Goal / outcome:** every LLM call goes through one resilient, budgeted, cacheable path.
**Tasks**
- [ ] S13.1 Providers: Groq, Gemini, Ollama; config-driven fallback chain; per-request timeout.
- [ ] S13.2 Retries with exponential backoff + jitter (`tenacity`); own circuit breaker (closed/open/half-open) per provider.
- [ ] S13.3 Response cache (hash of model+messages+params; Redis/disk) and a **recorded mode** (VCR-style fixtures) for deterministic tests/CI.
- [ ] S13.4 Budgets (tokens, cost, per run and per day) → `BudgetExceeded`; usage emitted to events.
- [ ] S13.5 Structured output: Pydantic validation + ≤2 repair retries; `AllProvidersDown` for callers to fall back deterministically. Replace `thin.py` callers. ADR-009.
**Acceptance:** 429 storm falls through the chain; breaker opens after N failures and half-open probes; budget stop is hard; identical prompts hit cache; `MAX_MONTHLY_USD=0` blocks paid providers.
**Tests:** unit (breaker state machine, backoff bounds), fault injection (5xx/429), recorded-mode determinism.
**Demo:** kill the primary provider mid-run; show fallback and breaker state.
**Learning:** backoff+jitter; breakers; caching with temperature. Q: (1) Why jitter? (2) When does a half-open breaker re-close? (3) What can you safely cache?
**Risk/fallback:** Ollama too slow → use it only in benchmark rows.

---

### S14 — Harness core · 3d · Phase 2/4
**Goal / outcome:** a durable run loop that survives worker death, tested without an LLM.
**Tasks**
- [ ] S14.1 `harness/state.py`: `RunState`, `TaskSpec`, `Experiment`, `ReviewVerdict` (spec §11); Postgres `runs`, `run_steps(run_id, step, state_json, UNIQUE(run_id, step))`, `runs.heartbeat_at`.
- [ ] S14.2 `apps/worker` (arq): `execute_run` loads latest checkpoint, runs loop (§6.3), step commit via `INSERT … ON CONFLICT DO NOTHING`; tool calls carry idempotency key `(run_id, step)`.
- [ ] S14.3 Scripted fake-LLM planner for tests; termination conditions; loop guards (same error ×3 → replan; no progress N steps → honest stop).
- [ ] S14.4 Heartbeat + reaper (arq cron re-enqueues runs with stale heartbeat); pause/resume/stop flags checked each step.
- [ ] S14.5 `POST /v1/runs`, `GET /v1/runs/{id}`, `POST /v1/runs/{id}/{pause|resume|stop|hint}`.
- [ ] S14.6 Chaos script: `kill -9` worker mid-run; assert completion and identical final-state hash; record recovery time → results file. ADR-003.
**Acceptance:** zero duplicated step executions after kill; recovery time measured and committed; budgets live in state.
**Tests:** unit (state transitions), integration (compose chaos), property (replaying any prefix yields same state).
**Demo:** start a run, kill the worker, watch it finish.
**Learning:** idempotency, at-least-once vs exactly-once, checkpoint design. Q: (1) What happens when the worker dies between tool call and commit? (2) Why typed state, not chat history? (3) How does the reaper avoid double-running a live worker?
**Risk/fallback:** reaper races → advisory lock per run_id.

---

### S15 — Roles + modelling loop · 3d · Phase 2
**Goal / outcome:** the agent trains and tunes models on real datasets and gets scored by the scorer.
**Tasks**
- [ ] S15.1 `harness/context/packer.py`: typed slots with token budgets (task, plan, top insights, last N experiments as compact rows, current error); `compaction.py` deterministic log summary (exception type, failing line, head/tail).
- [ ] S15.2 `harness/framing.py`: deterministic CV strategy + metric from data/task (stratified/group/time).
- [ ] S15.3 Roles: planner (`Plan` schema), analyst (mostly deterministic: profile+insights+leakage into state), modeller (LLM fills `# BEGIN AGENT CODE` regions in a template; baselines run first via `jmd_runtime`).
- [ ] S15.4 Pipeline: policy check → sandbox → parse sentinel JSON metrics → `log_run` → state update; budgeted Optuna HPO allowed in template.
- [ ] S15.5 Final: submit bundle to scorer once; write outcome labels onto the trajectory.
- [ ] S15.6 Run on 5 datasets with a real LLM; commit `benchmarks/results/agent_v0.json`.
**Acceptance:** all steps checkpointed; hidden test never touched outside the scorer (test); every run ends in success or an honest failure report; pass rate reported as measured (no pre-set threshold).
**Tests:** golden runs (recorded LLM), unit (packer slots, compaction), security (hidden path attempts blocked).
**Demo:** one live run end-to-end in the terminal.
**Learning:** context engineering; why baselines first; why CV code isn't LLM-written. Q: (1) What goes in each context slot and why? (2) How does the agent decide group vs stratified CV? (3) Why must transforms live inside the Pipeline?
**Risk/fallback:** weak small-model runs → start with the strongest free model, defer comparisons to S26.

---

### S16 — Live events + first benchmark · 3d · Phase 2/5 · **Milestone M2**
**Goal / outcome:** watch a run live; first honest benchmark table on 10 tasks.
**Tasks**
- [ ] S16.1 `GET /v1/runs/{id}/events` SSE from `events` table, sanitised (no prompts/keys, truncated outputs).
- [ ] S16.2 Run Theater v1: timeline cards (plan/tool/code/output/metric), live best-CV chart, budget meter, pause/resume/hint buttons, leaderboard table (`GET /v1/runs/{id}/leaderboard`).
- [ ] S16.3 `run_benchmark.py --models --tasks` full loop incl. scoring; results: pass rate, normalized score, cost/task, steps, wall-clock.
- [ ] S16.4 CI smoke: 3 tasks with recorded LLM (non-blocking until S27).
**Acceptance:** UI reconnects after SSE drop and resumes from last seq; benchmark file has conditions + n; unscrubbed fields never reach the browser (test).
**Tests:** e2e (live run in Playwright with recorded LLM), SSE reconnect test.
**Demo:** a live run on a chosen dataset.
**Learning:** SSE vs WebSocket; event sanitisation. Q: (1) Why SSE here? (2) What must never leave the BFF/event layer? (3) How do you make a benchmark resumable?
**Risk/fallback:** cost → run benchmark with one model only.

---

### S17 — Reviewer: deterministic checks · 3d · Phase 3
**Goal / outcome:** code-enforced review checklist.
**Tasks**
- [ ] S17.1 Split integrity on the actual folds (row-hash, group, time order).
- [ ] S17.2 AST pipeline check: fit/transform of scalers/encoders/target encoders only inside the `Pipeline`/`ColumnTransformer` passed to `cv_evaluate`; documented heuristic limits (also closes leakage `encoding` type).
- [ ] S17.3 Baseline margin (≥ both baselines × 1.02 by the pass rule), train–val gap, CV std ratio, unresolved leakage findings, metric-matches-task, seeds set + pinned versions.
- [ ] S17.4 `ReviewVerdict.checks` dict; ADR-010 (what's deterministic vs LLM).
**Acceptance:** each bad-pipeline fixture (scaler on full X, target-encode before split, missing seeds, overlapping folds) is caught; good fixture passes.
**Tests:** unit with fixture corpus; mutation tests (inject leakage into a good pipeline → check flips).
**Demo:** run checks on a deliberately leaky generated script.
**Learning:** fit-inside-fold; why static checks have blind spots. Q: (1) Why must target encoding be fit inside folds? (2) What can your AST check miss? (3) What's a train–val gap threshold telling you?
**Risk/fallback:** AST false positives → allow-list known-safe patterns.

---

### S18 — Reviewer: sub-agent · 2d · Phase 3
**Tasks**
- [ ] S18.1 Reviewer role: separate system prompt; role→tool allow-list enforced in the policy layer (no `run_python`, no writes).
- [ ] S18.2 Verdict logic: APPROVE only if all deterministic checks pass AND LLM concurs; LLM may add `REQUEST_CHANGES`, never override a failed check.
- [ ] S18.3 Loop-back: findings → modeller context slot; max 3 rounds; disagreements logged.
- [ ] S18.4 Run config `review_mode: off | deterministic | full` (ablation switch for S26).
**Acceptance:** on a bugged task the reviewer requests changes ≥1 time; loop ends ≤ max rounds; reviewer calling `run_python` is denied (test).
**Tests:** integration (recorded LLM), policy tests.
**Demo:** run with a leaky modeller; show REQUEST_CHANGES → fix → APPROVE.
**Learning:** why a separate reviewer helps. Q: (1) Why no write access? (2) Why can't the LLM override a failed check? (3) How will you measure the reviewer's value?
**Risk/fallback:** loops → cap rounds at 2 and report.

---

### S19 — Explainability + results page · 3d · Phase 3
**Tasks**
- [ ] S19.1 Runtime lib: SHAP (Tree/Linear explainers; Kernel capped), PDP for top-3, confusion matrix/ROC/PR/calibration/residuals — emitted as values, rendered to Vega-Lite (consistent theme).
- [ ] S19.2 Error slicing: per-category/quantile-bin scan, min support + CI, top-5 worst slices.
- [ ] S19.3 `GET /v1/runs/{id}/explain`; Results page: leaderboard, before/after leakage card, explain tabs.
**Acceptance:** on a synthetic dataset with known generating features, SHAP top-3 contains all true features; planted weak segment appears in top-3 slices.
**Tests:** unit (known-truth synthetic), schema tests.
**Demo:** explain a trained churn model; pick a row waterfall.
**Learning:** SHAP meaning and limits; PDP vs ICE. Q: (1) What does a SHAP value actually represent? (2) When is it misleading (correlated features)? (3) How would you verify a "worst slice" isn't noise?
**Risk/fallback:** Kernel SHAP slow → tree/linear only; flag others unsupported.

---

### S20 — deploy MCP · 3d · Phase 3
**Tasks**
- [ ] S20.1 Jinja templates → `serving/app.py` (FastAPI), request model from training schema via `pydantic.create_model`, `/health`, `/predict`.
- [ ] S20.2 Dockerfile from `requirements.lock`; `build_image` via host Docker SDK. ADR on host build.
- [ ] S20.3 Contract tests generated + run: valid→200, invalid→422, missing field→422, p95 latency under budget (100 requests), OpenAPI snapshot.
- [ ] S20.4 `deploy_endpoint` (gated; real token validation lands S23, stub flag only in tests), `rollback`.
- [ ] S20.5 Model card (intended use, data summary, metrics from results, limitations from findings) via the claim verifier; curl example.
**Acceptance:** contract tests pass for ≥5 generated endpoints; latency p50/p95 recorded with conditions.
**Tests:** integration (container up/down), contract, card-number verification.
**Demo:** deploy a model, curl it.
**Learning:** serving schema from training data; contract testing. Q: (1) How is the request schema derived? (2) Why test 422s? (3) What risk comes from loading an agent-produced pickle in serving, and how is it contained?
**Risk/fallback:** Docker-in-compose pain → run serving via plain `uvicorn` subprocess for dev.

---

### S21 — Reproducibility bundle + stakeholder PDF · 2d · Phase 3 · **Milestone M3**
**Tasks**
- [ ] S21.1 `nbformat` notebook from the final accepted code; `requirements.lock`, Python version, seeds, profile/insights/story HTML, model artifact + card, MLflow run export, `REPRODUCE.md`; `GET /v1/runs/{id}/bundle`.
- [ ] S21.2 `scripts/verify_bundle.py`: unzip → execute via `nbclient` in a clean env → compare CV within tolerance.
- [ ] S21.3 Stakeholder PDF (Jinja2 + WeasyPrint), ≤3 charts, business-term metrics computed deterministically, verified numbers; `GET /v1/runs/{id}/report.pdf`.
**Acceptance:** bundle reproduces CV within tolerance on 3 datasets in CI; PDF is exactly 1 page (`pypdf` assert); all numbers verified.
**Tests:** e2e bundle verify, PDF page-count, verifier on report text.
**Demo:** download bundle, run it, show matching CV; open the PDF.
**Learning:** reproducibility = seeds + pins + data hash. Q: (1) What else breaks reproducibility besides seeds? (2) How do you translate recall/precision into manager language without inventing numbers? (3) What tolerance and why?
**Risk/fallback:** notebook drift → generate from the same code artifact, never re-prompt.

---

### S22 — Injection defence + suite · 3d · Phase 4
**Tasks**
- [ ] S22.1 `harness/policies/untrusted.py`: sanitise names/cells (length caps, strip control/zero-width chars), render in delimited `UNTRUSTED` data slots only (packer rejects untrusted text in instruction slots); heuristic injection scorer; flagged names aliased (`col_017`) with an alias map for all LLM-visible text.
- [ ] S22.2 Same treatment for tool outputs and filenames.
- [ ] S22.3 `benchmarks/injection/` ≥30 cases: column-name, cell, filename, tool-output, mixed; each with an `unsafe_action` oracle (read scorer path, banned import, deploy without approval, URL exfil, change target).
- [ ] S22.4 Metrics: block rate, unsafe-action count (target 0), behaviour-change rate on a 10-case real-LLM subset; results file + ADR-013.
**Acceptance:** unsafe actions = 0 on suite (if >0, fix before merge, else document as open risk); security counters logged.
**Tests:** the suite itself; property (sanitiser idempotent, caps hold).
**Demo:** upload a CSV with a hostile column name; show alias + blocked action.
**Learning:** direct vs indirect injection; data/instruction separation. Q: (1) Why is a CSV an injection vector? (2) Why alias instead of delete? (3) What does your suite NOT cover?
**Risk/fallback:** heuristic misses → keep as reported limitation.

---

### S23 — Approvals, audit chain, admin auth · 3d · Phase 4
**Tasks**
- [ ] S23.1 Admin login: env `ADMIN_USER` + argon2 `ADMIN_PASSWORD_HASH`; short-lived JWT in httpOnly SameSite=Strict cookie.
- [ ] S23.2 `ApprovalRequest` persisted; UI approve → HMAC token over `(approval_id, action, run_id, payload_hash, exp)`; consumption by atomic `UPDATE … WHERE used_at IS NULL AND expires_at > now() RETURNING`; TTL 10 min; deploy MCP validates action/run/payload match. ADR-011.
- [ ] S23.3 `audit_log` (`prev_hash`, `hash = SHA256(prev_hash ‖ canonical_json)`), serialized appends, `REVOKE UPDATE, DELETE` for the app role; `verify_chain()` CLI + `GET /v1/audit`, `/v1/audit/verify`. ADR-012.
- [ ] S23.4 Audit every tool call (code + code hash), approval, deploy, login, setting change.
**Acceptance:** token reuse → 409; wrong payload hash/action → rejected; expired → rejected; direct DB tampering is pinpointed by `verify_chain`; concurrent appends keep the chain valid.
**Tests:** security (reuse, tamper, expiry, race), property (chain verifies for random sequences).
**Demo:** deploy blocked → approve → deploys once → replay fails; tamper a row, verify flags it.
**Learning:** tamper-evident ≠ tamper-proof (anchor head hash externally). Q: (1) Why single-use and payload-bound? (2) What does the hash chain prove and not prove? (3) How is the append race handled?
**Risk/fallback:** none; keep it small (~50 lines for the chain).

---

### S24 — Observability + load test · 3d · Phase 4 · **Milestone M4**
**Tasks**
- [ ] S24.1 OTel spans run→step→tool/LLM with GenAI attributes; Langfuse export (full profile); secret-scrubbing span processor.
- [ ] S24.2 `/metrics` (prometheus-client): runs, steps/run, time-to-result, queue depth, tokens/cost by provider, LLM errors, fallbacks, breaker state, sandbox start latency.
- [ ] S24.3 One Grafana dashboard JSON (Ops+Cost) + 3 Prometheus alert-rule files (error rate, cost spike, queue backlog).
- [ ] S24.4 Backpressure: queue-depth cap → `429 Retry-After`; per-run concurrency limit.
- [ ] S24.5 Locust load test with mocked LLM + fake sandbox; results labelled accordingly (runs/hour, p95 time-to-result, 429 rate).
**Acceptance:** planted fake key in tool output never appears in exported spans (test); dashboard provisioned from code; load numbers committed with `llm: mocked, sandbox: fake`.
**Tests:** unit (scrubber), integration (metrics endpoint), load.
**Demo:** run traffic, show dashboard and a Langfuse trace.
**Learning:** metrics vs traces vs logs; backpressure. Q: (1) Why reject with 429 instead of queueing forever? (2) What must never appear in a trace? (3) What does a mocked-LLM load test prove and not?
**Risk/fallback:** Langfuse heavy → full profile only.

---

### S25 — Benchmark scale-up · 3d · Phase 5
**Tasks**
- [ ] S25.1 Registry 10→30 tasks (≥5 imbalanced; licence per task); expand `p3_heldout` (≥6, frozen; never used to tune prompts).
- [ ] S25.2 Baselines (dummy/linear/FLAML, same time budget) for all 30.
- [ ] S25.3 `benchmarks/score_run.py`: per-run record — pass, normalized score, bug-catch (agent report vs `labels.json`: kind + columns), honest-score (reported ≤ post-fix score + ε), false-alarm on twins.
- [ ] S25.4 Resumable, cached grid runner keyed `(task, model, config, seed)`; run planted-bug variants through the agent with one model.
**Acceptance:** 30/30 baselines committed; scoring script unit-tested on fixtures; runs resumable; quota-friendly scheduling documented.
**Tests:** unit (score_run), integration (resume after interruption).
**Demo:** bug-catch and honest-score table for the first model.
**Learning:** honest-score metric; reward hacking. Q: (1) Define honest-score and why it exists. (2) How do you prevent prompt-tuning on the P3 heldout? (3) Why a clean twin per bug?
**Risk/fallback:** quota → fewer bug variants per type, state it.

---

### S26 — Full benchmark · 3d · Phase 5
**Tasks**
- [ ] S26.1 Grid: Gemini, gpt-oss-120b (Groq), small Ollama model, FLAML; main grid 1 seed.
- [ ] S26.2 Ablations on the cheapest strong model: `review_mode` (full vs off), Data-Story-insights-in-context (on vs off); 2 seeds on a 10-task subset (choose which model at start of sprint by remaining quota).
- [ ] S26.3 `benchmarks/make_tables.py` → `benchmarks/README.md` + `results/v1/*.json`; paired bootstrap on per-task differences for ablations; failures listed; conditions block.
**Acceptance:** all tables regenerate from raw records with one command; each cell shows n and 95% CI.
**Tests:** table-generator golden test; CI recompute check.
**Demo:** the benchmark table and ablation deltas.
**Learning:** paired vs unpaired bootstrap; seeds vs tasks as the unit. Q: (1) Why paired bootstrap for ablations? (2) What does 1 seed hide? (3) Why report failures?
**Risk/fallback:** quotas → spread over days; never drop CIs.

---

### S27 — Eval gate, pipelines, trajectory export · 3d · Phase 5
**Tasks**
- [ ] S27.1 `.github/workflows/eval-gate.yml`: fast subset (3 tasks, 3 planted bugs, 5 injection cases, caption-verify) with **recorded** LLM vs `benchmarks/results/gate_baseline.json`; block on: any unsafe action, hidden-access test failure, unverified claim >0, pass-count drop >1, bug-catch drop.
- [ ] S27.2 Prefect flows (local): `nightly_benchmark_subset`, `export_trajectories`, `retention_cleanup`.
- [ ] S27.3 Trajectory export: JSONL (state, prompt hashes, outputs, tool calls, observations, budgets, outcome labels) + chat-format SFT (successful = pass ∧ honest ∧ review APPROVE; dedupe by task+plan hash; PII scrub; **exclude `p3_heldout`**) + dataset card; DVC-tracked.
**Acceptance:** gate blocks a seeded regression PR in a test; export validates against schema; zero heldout rows (test); counts reported, not targeted.
**Tests:** gate dry-run on a seeded regression, export schema/heldout tests.
**Demo:** PR blocked by the gate; show export summary.
**Learning:** eval gates vs unit tests; flakiness control via recorded LLM. Q: (1) Why recorded LLM in the gate? (2) How does the gate decide to block? (3) Why exclude heldout from SFT data?
**Risk/fallback:** gate flaky → widen to "drop >1" and document.

---

### S28 — Polish + launch · 3d · Phase 5
**Tasks**
- [ ] S28.1 Recruiter mode: showcase runs stored as event JSONL; replay controller (speed/step); network trace shows 0 LLM calls; `DEMO_MAX_RUNS_PER_DAY` for live runs.
- [ ] S28.2 Landing: pitch, benchmark cards from `/v1/benchmarks` (reads results; `pending` if absent), architecture SVG, showcase chips; Deployments + Admin(audit) minimal pages.
- [ ] S28.3 A11y (axe in Playwright), Lighthouse CI mobile, CSP via reverse proxy (no inline).
- [ ] S28.4 README with screenshots, §23 demo video, reproduce-from-scratch, ADR index; demo deploy on a small VM + E2B for live runs, budget caps + billing alerts.
- [ ] S28.5 Interview rehearsal: answer every §21 question aloud without notes.
**Acceptance:** Lighthouse mobile ≥90 (measured); recruiter mode replays full showcase with 0 LLM calls; fresh-clone `docker compose up` works; video recorded.
**Tests:** e2e (recorded + live), axe, Lighthouse CI.
**Demo:** the 90-second script, §23.
**Learning:** everything in §21. Q: (1) Walk the architecture in 90 s. (2) What are the three weakest points and how did you measure them? (3) What would break at 100× load?
**Risk/fallback:** time → ship recruiter mode first, live runs second.

---

## 4. Cross-cutting

**ADR schedule**

| ADR | Topic | Written in |
|---|---|---|
| 001 | Architecture | S1 |
| 015 | Scope cuts (§0) | S1 |
| 004 | Scorer isolation + predict-in-sandbox | S2 (stub), S11 (final) |
| 005 | Pass rule + normalized score | S3 |
| 006 | Sampling for pairwise stats | S5 |
| 007 | Chart ranking | S6 |
| 008 | Claim verifier | S7 |
| 002 | Sandbox (E2B + LocalDocker) | S10 |
| 009 | LLM gateway | S13 |
| 003 | arq + Postgres checkpoints | S14 |
| 010 | Reviewer: deterministic vs LLM | S17 |
| 013 | Injection defences | S22 |
| 011 | Approval tokens | S23 |
| 012 | Audit hash chain | S23 |

**CI / eval gate build-up.** S1: lint, type, unit, gitleaks. S3: benchmark primitives unit tests. S8: leakage eval smoke (non-blocking). S16: agent smoke on 3 tasks, recorded LLM (non-blocking). S27: blocking gate per its rule. Until S27, regressions are caught by unit/security tests only.

**Cost / free-tier constraints.** Groq, Gemini free tiers + Ollama locally; E2B free credits (LocalDocker for dev/CI); Langfuse self-hosted in `full` profile only; no paid services; `MAX_MONTHLY_USD=0` default blocks paid providers; aggressive response cache; benchmark grid staggered across days; load tests use mocked LLM + fake sandbox and are labelled so.

**P3 trajectory logging from sprint 1.**
- S1: `TrajectoryEvent` schema + writer is the **only** logging path.
- S4–S9: pipeline stages emit `pipeline_step` events (not agent steps, still useful for provenance).
- S12–S15: every tool call, prompt (by hash), model output and observation emits; `agent_version` hash stamped.
- S15: `outcome_labels` (task success, review verdict, bugs caught, honest-score flag) written at run end.
- S2/S25: `p3_heldout` task partition frozen and excluded from any prompt tuning.
- S27: JSONL + chat-format SFT export, dataset card, DVC; heldout exclusion test.

**Security invariants (tested, never relaxed).** Hidden labels only in the scorer; scorer never unpickles; code policy before every execution; untrusted text only in data slots; gated actions need single-use tokens; secrets never in prompts/logs/traces.

---

## 5. Definition of done (whole project)

- [ ] S1–S28 acceptance criteria met; each measured number committed under `benchmarks/results/` with command, conditions, n, CIs.
- [ ] README/UI numbers all trace to result files (else "pending").
- [ ] Hidden-test isolation, sandbox egress, injection suite (0 unsafe actions), approval, audit-chain tests green in CI.
- [ ] Worker-kill chaos test: recovery time recorded, no duplicate steps.
- [ ] Benchmark v1: 30 tasks, 3 models + FLAML, 2 ablations, reproducible with one command.
- [ ] Eval-gated CI blocking; gitleaks clean; ADRs 001–015 present.
- [ ] Fresh-clone `docker compose up` (micro profile) works; recruiter mode works with 0 LLM calls; demo video linked.
- [ ] Trajectory dataset v1 exported with card; P3 heldout excluded.
- [ ] Every §21 question answered aloud without notes.
