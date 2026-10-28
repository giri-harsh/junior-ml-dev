# ADR-008: Ingest, profile and Quality Scorecard (PRD S4)

Status: accepted (S6 of this run)

## Decision
`POST /v1/datasets` stores a csv/parquet (<= 50 MB) content-addressed (`dataset_id = sha256[:16]`), then a background job parses, profiles and scans for PII shapes (flags only). `GET .../status|profile|quality`. The Quality Scorecard is a weighted mean of six sub-scores (weights in `datastory/config.yaml`): completeness, uniqueness, validity, consistency, timeliness, leakage_risk. Every deduction names columns and a suggested fix.

## Rules worth knowing
- Consistency covers case/whitespace variants and abbreviation-vs-full-name pairs (initials match, e.g. NY / New York). Semantic synonyms are out of scope.
- Timeliness runs only when the caller passes `as_of` (no wall clock, so scores are reproducible).
- leakage_risk is populated only with `?with_leakage=true&target=...` (runs the S5 detectors; slow).
- The score is a decision aid, not a truth: weights are a judgement, not fitted.

## Measured
`benchmarks/results/profile_latency_v0.json`: profile + scorecard on a seeded 100k x 50 frame, median 5.42 s (budget 10 s), reference machine.

## STUBs
Object storage is a local filesystem behind an `ObjectStore` protocol (MinIO not implemented). The profile job is a FastAPI background task, not arq. Both are listed in `docs/KNOWN_GAPS.md`.
