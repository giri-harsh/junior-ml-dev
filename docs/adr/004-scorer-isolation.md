# ADR-004: Scorer isolation (stub, finalised in S11)

Status: proposed (S2)

## Decision
Hidden test labels live only in `scorer_data/`, mounted only by the `scorer` service (read-only). The agent-visible store holds `train.parquet` and a manifest with no label hash. Scoring takes a predictions CSV and a per-run HMAC token.

## Why
"Cannot cheat" is enforced by deployment (no mount in worker), not by convention. Tested by `test_labels_not_in_worker_mount`.

## Open (S11)
Predict-in-sandbox so the scorer never unpickles agent artifacts; one final score per run_id.
