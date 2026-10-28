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

## Known limitations (filled in after the eval run)
See the section appended below once `leakage_v0.json` exists.
