# data-tools MCP server

Run (stdio): `python -m mcp_servers.data_tools.server`. Built on the official `mcp` SDK (2.x, `MCPServer`).

## Guards
| Guard | Value |
|---|---|
| Path allowlist | real path must be under `DATA_TOOLS_ROOTS` (os.pathsep list; default `data`, `benchmarks`) |
| Always denied | any path containing a `scorer_data` component |
| File types | `.csv`, `.parquet` |
| File size | 50 MB |
| Rows | `max_rows` 100..200,000 (default 50,000); larger files are seeded-sampled, sample info is returned |
| Time | `time_budget_s` 0..300 (default 60), cooperative |
| Logging | JSON lines on stderr and a `TrajectoryEvent` per call, keyed by `run_id` |

Dataset contents, column names and file names are untrusted data. Errors are returned as MCP tool errors with a short message.

## Tools
All tools take one object argument named `request`.

### profile_dataset
`{path, target?, run_id?, max_rows?, seed?}` -> `{run_id, profile}`. Profile: row/column counts, duplicates, per-column dtype / semantic type / missingness / uniques / near-constant / association with target, target balance or skew, suspected id/time/group columns.

### detect_leakage
`{path, target, run_id?, max_rows?, seed?, time_budget_s?}` -> `{run_id, target, task_type, findings[], counts, thresholds_sha256, sample}`.
Finding: `{type, severity: low|medium|high, columns[], evidence{}, confidence}`. Types: `target_leakage`, `post_outcome`, `high_cardinality_proxy`, `duplicate_rows`, `temporal_leakage`, `group_leakage`, `id_leak`, `id_like` (low), `unit_mismatch`, `suspicious_column_name`, `label_noise` (classification only; regression returns a LOW not-applicable finding). `train_test_contamination` needs a second frame and is available through the Python API (`DetectionMeta.holdout`).

### data_story
Same request as `detect_leakage` -> `{profile, findings, markdown, meta}`. The markdown is deterministic text built from the profile and findings.

## Example (Python client)
```python
args = {"request": {"path": "data/tasks/credit-g/train.parquet", "target": "class"}}
result = await session.call_tool("detect_leakage", args)
```

## Severity semantics (v1)
`medium`/`high` = confirmed by a seeded probe or structural test. `low` = suspicion (for example a name hint) or advisory; `evidence.unconfirmed` marks unconfirmed suspicions. Pass `task_type` when the target is an ordinal score. Probe cost and rules: ADR-007.

## Evaluation
`python -m benchmarks.tune_leakage` (planted dev + real_dev only) and `python -m benchmarks.run_benchmark --leakage` (frozen thresholds, once per hash via `benchmarks/eval_ledger.json`). Results: `benchmarks/results/leakage_v1.json` (v0 kept for history). Design and limitations: `docs/adr/006-data-tools-leakage-detective.md`.
