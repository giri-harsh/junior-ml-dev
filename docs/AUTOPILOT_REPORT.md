# AUTOPILOT REPORT

Sprint numbers below are this run's labels (S5-S11), not the PRD's. **Not every PRD sprint was done**: see SKIPPED.

## STATUS
| Sprint | Status | Tag |
|---|---|---|
| S5 leakage precision + label_noise | done, 2 known false positives | s5-done |
| S6 ingest, upload, Quality Scorecard (PRD S4) | done | s6-done |
| S7 insights, claim verifier, captions (PRD S5, S7) | done (no charts/HTML) | s7-done |
| S8 LLM gateway (PRD S13) | done, never called a real provider | s8-done |
| S9 code policy, sandbox backends (PRD S10) | partial: Docker/E2B not run | s9-done |
| S10 reviewer checks, injection defence (PRD S17, S22) | partial: no LLM reviewer | s10-done |
| S11 approvals, audit chain, admin login (PRD S23) | partial: SQLite only | s11-done |

## NUMBERS (all from benchmarks/results/*.json)
- Leakage v1 (`leakage_v1.json`, hash 0cde227f6327, seed 0): eval2 recall 23/24 (bootstrap 95% CI [0.875, 1.0]); every type 3/3 except group_leak 2/3 (Wilson [0.21, 0.94]); label_noise 3/3. Clean-twin false alarms 0/24 (Wilson upper 0.138). dev (record only) 23/24.
- real_heldout (10 tasks): 3 medium/high findings, adjudicated: 1 true positive (`segment` exact duplicates), 2 false positives (`churn` group probe on a 10-valued count; `wine_quality` ordinal target read as classes). 7 tasks clean. Real-data recall is unmeasured (no ground-truth leaks).
- real_dev (tuning set): 16 datasets, 0 medium/high findings.
- Captions (`caption_verify_v0.json`): 399 insights, 807 numeric claims, 0 unverified; perturbation rejected 397/399 (2 coincidental matches).
- Injection (`injection_v0.json`): 41 cases; template payloads flagged 35/35, evasion payloads 2/6; unsafe actions executed 0/41 (simulated compliant agent vs structural guard; no LLM run).
- Profile + scorecard on 100k x 50: median 5.42 s (budget 10 s). Baselines: normalized linear 0.82 [0.61, 1.04], n=10.
- Tests: 253 passed. ruff and mypy clean at the last merge.

## DECISIONS
31-40 leakage v1 design (DiD probes, confirmation rule, ledger, incident handling); 41-44 ingest; 45-48 verifier; 49-52 gateway; 53-56 sandbox; 57-61 review/injection; 62-65 approvals/audit. One line each in docs/DECISIONS.md.

## SKIPPED / STUBBED / NOT RUN (docs/SKIPPED.md, docs/KNOWN_GAPS.md)
- Charts and HTML story (PRD S6, S7.5); React UI (S9); E2B/Docker sandbox execution and egress tests (S10, S11); predict-in-sandbox scorer (S11); experiments and deploy MCP servers (S12, S20); arq + Postgres harness, agent roles, agent benchmarks, explainability, bundle/PDF, observability/load, eval gate (S14-S16, S19, S21, S24-S28). Resume: `docs/SKIPPED.md`.
- STUB: MinIO ObjectStore, arq worker, E2BBackend, Postgres approval/audit stores.
- NOT RUN: any real Groq/Gemini/Ollama call; docker compose; CI; gitleaks (regex scan used, clean).
- The revisit pass found nothing new that is reachable without services or keys.

## KNOWN GAPS
Leakage group probe fires on strongly predictive low-cardinality integers; ordinal targets need `task_type`; positive-skewed unit mismatches missed; injection heuristic misses obfuscation (guard still holds). Sandbox subprocess backend is not isolation. Quality score weights are judgement.

## FAILURES HIT AND HOW HANDLED
- **Eval slot spent by a test bug.** A test's ledger path was bound at import time, so it ran the real v1 benchmark before the freeze tag. Thresholds and detectors were already final and unchanged; I had not read the results; I fixed the bug with a regression test, froze the same hash, and disclosed it (ADR-007 limitation 6, decision 39). The "frozen before eval" ordering holds by hash equality, not commit order.
- Merged S8 with one ruff error (fixed next commit); later merges gated on lint.
- Windows bugs found by tests and fixed: `/abs` accepted as relative; leaked SQLite connections; non-UTF-8 doc write; stray backspace characters from `\b` in a heredoc.
- Unit-mismatch log test fired on every Gaussian column; replaced (tuning round 1).
- Could not kill a stray process (permission denied for a broad kill); stopped my own background task instead.

## GIT
Branches s5..s11 merged into main with --no-ff. Tags: s4-done, s4-thresholds-frozen, s5-thresholds-frozen, s5-done ... s11-done. Last commit fbe141e (plus this report). No remote; nothing pushed.

## WALL
None.
