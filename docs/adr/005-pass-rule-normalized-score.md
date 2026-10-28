# ADR-005: Pass rule and normalized score

Status: accepted (S3)

## Pass rule
Pass = hidden-test metric >= linear baseline x 1.02 (relative; error metrics: <= linear x 0.98) **and** no unresolved high-severity leakage finding. Ceiling clause: if linear >= 0.98 (higher-is-better), or linear error <= 2% of target std, pass = "not worse than linear", because x1.02 is unreachable near the ceiling. Implemented in `benchmarks/metrics.py::passes`.

## Normalized score
`(agent - dummy) / (flaml - dummy)`, sign-flipped for error metrics, so 0 = dummy and 1 = FLAML under the same time budget. Undefined (None) when `|flaml - dummy| < 1e-3 * max(|dummy|, 1)` or FLAML is not better than dummy. Undefined tasks are excluded from aggregates and counted in `excluded_tasks`; they are never clipped.

## Confidence intervals
Percentile bootstrap of the mean over tasks, 10,000 resamples, seed 0. The unit is the task, so n is the number of tasks with a defined score. Ablations use a paired bootstrap on per-task differences.

## Consequences
Scores can exceed 1 (agent beats FLAML) or go negative (agent worse than dummy); both are reported as measured. Baselines are scored through the scorer code path in-process, not over HTTP between containers.
