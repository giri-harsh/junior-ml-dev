# ADR-012: Deterministic reviewer checks and injection defence (PRD S17, S22)

Status: accepted (S10 of this run)

## Reviewer (deterministic part only)
`harness/review/checks.py`: split integrity on actual folds (train/val overlap, reused validation rows, identical rows, group and time order), AST pipeline check (transformers fitted outside a Pipeline/ColumnTransformer, including inline `Scaler().fit_transform`), seeds set, baseline margin via `benchmarks.metrics.passes`, train-validation gap, CV stability, unresolved medium/high leakage findings, metric-matches-task. Any failed check means REQUEST_CHANGES. Heuristic limits: one file, literal sklearn-style names; aliasing, `exec`, or fitting inside a helper function evades it. The LLM reviewer sub-agent (PRD S18) is not built; an LLM may only ever add to this verdict.

## Injection defence
- `harness/policies/untrusted.py`: NFKC + control/zero-width/bidi stripping, length caps, signal-based injection score, delimited `<UNTRUSTED>` rendering, aliasing of flagged names (`col_001`) with a server-side map, and a packer guard that rejects raw untrusted text in instruction slots.
- `harness/policies/actions.py`: structural guard for run_code (code policy), read_file (path policy), fetch_url (no egress), deploy (approval token required), set_target (immutable after start). It decides regardless of what the model does.
- `benchmarks/injection/suite.py`: 41 cases (5 channels x templates + 6 evasion). Oracle: a simulated fully-compliant agent attempts each payload's action.

## Measured (`benchmarks/results/injection_v0.json`)
41 cases; template payloads flagged 35/35; evasion payloads (zero-width split, full-width letters, paraphrase, Spanish, indirect wording) flagged only 2/6; unsafe actions executed 0/41 (guard refused all). Behaviour-change rate on a real LLM: **not run**.

## Limits
The template payloads were written by the same author as the signal list, so 35/35 is optimistic; the evasion set shows the realistic gap. Protection against evasion rests on the structural guard, not on the heuristic. The suite never ran a model, so it proves the gates hold, not that a model resists.
