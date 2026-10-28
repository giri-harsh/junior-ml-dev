# ADR-006: data-tools MCP server, Data Story profiler and Leakage Detective

Status: accepted (S4)

## Scope note
The PRD's S4 is ingestion + quality scorecard, and its leakage detectors are S8. The S4 brief for this run asks for the data-tools MCP server with a profiler and a leakage detector, measured on the planted-bug suite. The brief wins (DECISIONS #20). Reused from the PRD: `profile.json` shape (S4), detector set and the freeze-then-evaluate-once protocol (S8), tool names (S12).

## Detector interface
`detect(df, target, meta) -> list[Finding]`, `Finding{type, severity, columns, evidence, confidence}`. Severity is `low | medium | high`. Only `medium` and `high` count as a detection in evaluation; `low` is advisory (for example "ID-like column present"). Detectors are deterministic: every model and split takes `meta.seed`; no wall-clock, no network, no labels file.

## Mapping to the planted bug types
| Planted type (`expected_detector`) | Detector | Finding type |
|---|---|---|
| target_proxy (`target_proxy`) | single-feature shallow-tree CV, out-of-fold target encoding for categoricals | `target_leakage`, `post_outcome` (name hint + lower threshold), `high_cardinality_proxy` |
| duplicate_leak (`split_overlap`) | exact and rounded duplicate-row fraction | `duplicate_rows` |
| temporal_leak (`temporal`) | random-CV minus time-ordered-CV gap on suspected time columns | `temporal_leakage` |
| group_leak (`group`) | random-CV minus GroupKFold gap on suspected group columns | `group_leakage` |
| id_correlated (`mi_spike`) | ID-like columns whose rank correlation with the target is high | `id_leak` (and advisory `id_like`) |
| unit_mismatch (`consistency`) | robust-z scale mixture check (quality, not leakage) | `unit_mismatch` |
| poisoned_name (`injection`) | instruction-like column-name heuristic (quality/safety) | `suspicious_column_name` |
| label_noise (`label_noise`) | none; no deterministic label-free detector was built | recall is expected to be 0 |

Train/test contamination is covered by `train_test_contamination`, which needs `meta.holdout` (a second frame). The planted suite has no train/test pair, so it is unit-tested only and not part of the recall numbers.

## Protocol
1. Thresholds live in `leakage/thresholds.yaml`. They are tuned on `dev` variants (0-2) only, at most 3 iterations per type; the tuning script refuses to read `eval`.
2. The file is committed and tagged `s4-thresholds-frozen` before `eval` is touched. The final run asserts the file hash equals `leakage/thresholds.frozen.sha256`.
3. `python -m benchmarks.run_benchmark --leakage` runs once: dev, eval, clean twins and the 10 real tasks, and writes `benchmarks/results/leakage_v0.json`.
4. Poor eval recall is reported as measured. No retuning, no generator edits.

## Guards (MCP layer)
Path allowlist (resolved real path under configured roots, `scorer_data` always denied), extension allowlist (csv, parquet), 50 MB file cap, 50k-row cap with seeded sampling, cooperative time budget, structured logs and `TrajectoryEvent`s keyed by `run_id`.

## Results (source: `benchmarks/results/leakage_v0.json`, seed 0, thresholds hash `2ca20d85b8f7...`)
- Recall at family level, medium+high findings only: dev 21/24, eval 21/24. On the five leakage types alone: 15/15 on dev and 15/15 on eval. Per-type n is 3, so every per-type Wilson interval is wide (lower bounds about 0.44).
- Clean-twin false alarms: 0/24 on dev, 0/24 on eval (Wilson 95% upper bound 0.138).
- `label_noise` is 0/3 on both partitions: no detector exists (see the mapping table).
- Thresholds were tuned on dev only: `temporal_leakage.min_gap` 0.04 -> 0.07 and `group_leakage.min_gap` 0.04 -> 0.015 (one iteration each, from the dev gap distributions). Eval ran once afterwards.

## Known limitations
1. **Small n.** Three variants per type per partition; the eval result says "no failures seen on these 15", not "high recall guaranteed".
2. **Synthetic suite.** The planted bugs are simple additive shortcuts on a synthetic base. Recall on real leakage is untested.
3. **Real-data false alarms.** On the 10 real tasks the detectors returned medium/high findings on every task (see `real_tasks` in the result file); none is a confirmed leak. Causes, not fixed because tuning on real tasks is outside this protocol:
   - `group_leakage` treats any discrete column with 10..n/2 distinct values as a possible group (for example `duration`, `V1`, `occupation`). With the low dev-tuned gap of 0.015 it fires on ordinary features.
   - `temporal_leakage` matched the substring `day` in `total_day_minutes`.
   - `unit_mismatch` fires on heavy-tailed columns (robust-z rule); `target_leakage` fires on strong honest features (`cpu_act`).
   - `duplicate_rows` fires on tables with naturally repeated rows (`wine_quality`, `blood-transfusion`).
   These are precision problems of the heuristics, not evidence of leakage. A follow-up should add a real-data dev partition and require group candidates to have a name hint or exact repetition structure.
4. **Single-frame view.** Train/test contamination needs `meta.holdout`; duplicate detection cannot say whether copies cross a split without it.
5. **Cooperative timeout.** The time budget is checked between detector steps; a single long model fit is not interrupted.
6. **Exact/rounded duplicate hashing**, not MinHash near-duplicates (PRD S8 names `datasketch`).
