# ADR-007: Leakage precision layer and label_noise detector

Status: accepted (S5). Supersedes the detector rules of ADR-006; the interface and protocol are unchanged.

## Why
S4 (ADR-006) caught 21/24 planted bugs with 0/24 clean-twin false alarms, but every one of the 10 real tasks received medium/high findings and none was a confirmed leak. The heuristics were precise on synthetic data and noisy on real data. `label_noise` had no detector.

## Partitions
| Partition | Content | Use |
|---|---|---|
| dev | planted variants 0-2 | tuning |
| eval_v0 | planted variants 3-5 | spent in S4, record only |
| eval2 | planted variants 6-8 (new seeds, same construction, strengths of base indices 5,3,1) | evaluated once, after the freeze |
| real_dev | 16 real datasets disjoint from the 10 benchmark tasks (`benchmarks/real_dev.py`, cached under `data/real_dev` with content hashes) | tuning and adjudication |
| real_heldout | the 10 benchmark tasks | evaluated once, after the freeze |

Variants 0-5 are byte-identical to S4 (hash-checked against `planted_bugs_v0.json`).

## Rule: medium/high needs confirming evidence
Name hints and other suspicions produce LOW notes (`evidence.unconfirmed = true`).
- **temporal / group:** difference-in-differences probe. Remove the candidate column (plus group-constant companions) and compare the cost under random CV versus time-ordered or group CV. A shortcut helps only when near neighbours can be matched; an honest predictive column helps in both. Three seeded repeats on at most 4000 rows; the median must clear the threshold and two thirds of repeats must clear half of it. Cost per candidate: 3 x 18 forest fits (30 trees) on at most 4000 rows, roughly 8 s on the reference machine; the slowest real_dev dataset took 26 s end to end.
- **target / post-outcome / high-cardinality proxy:** single-feature gini far above the runner-up (dominance) and a leave-one-column-out CV drop. With a name hint the dominance requirement is dropped but the gini floor and LOCO drop still apply.
- **duplicate_rows:** confirmed only when the duplicate rows match on at least two near-continuous columns (chance collisions negligible). Repeats on low-resolution columns are LOW.
- **unit_mismatch:** scale-mixture evidence: at least 15% of values beyond 10 robust spreads, near-symmetric column, and cluster spread ratio within 0.1 decades of a power of ten. Heavy positive tails alone are not enough. Skewed positive columns with genuinely mixed units are therefore missed.
- **id roles:** a unique-valued integer column is an identifier only if it is contiguous (row-number-like), id-named or a string. Wide-range unique counts are ordinary features. Time-name tokens no longer include `day` or `dt`.
- **label_noise:** confident learning (seeded 5-fold random-forest out-of-fold probabilities, per-class thresholds, calibrated confident joint). Classification only; regression returns a LOW not-applicable finding. Reports the estimated noise rate and up to 50 suspect indices.

## Tuning record (dev + real_dev only)
Round 1: the new log-scale unit test fired on every Gaussian column (log-magnitude is left-skewed), so it was replaced by the scale-mixture test. Round 2: gap and noise thresholds set from dev/real_dev distributions (temporal 0.04, group 0.05, label_noise 0.31). Round 3: `max_abs_skew` 1.0 -> 1.5 because one dev bugged variant had skew 1.008. Gates before freeze: dev recall 23/24, label_noise 3/3, twin false alarms 0/24, 0 medium/high findings on 16 real_dev datasets. real_dev contains no known true leak, so its zero says nothing about real-data recall.

## Result (source: `benchmarks/results/leakage_v1.json`, thresholds hash `0cde227f6327...`, tag `s5-thresholds-frozen`)
- eval2: 23/24 overall; the miss is `group_leak_08`. Per-type n is 3 (Wilson lower bounds about 0.44, group_leak 0.21). All other types 3/3, including label_noise.
- Twin false alarms on eval2: 0/24 (Wilson 95% upper bound 0.138).
- real_heldout: 3 medium/high findings, adjudicated in `benchmarks/adjudication_real_heldout.json`: 1 true positive (`segment` duplicate rows), 2 false positives (`churn` group_leakage; `wine_quality` label_noise). The other 7 tasks had none.

## Known limitations
1. **Group probe false positive.** GroupKFold on a strongly predictive low-cardinality integer (churn `number_customer_service_calls`, 10 values) hides the feature in every test fold, so the probe reads it as a shortcut. A structural check (repeating entity rows with group-constant companions) is needed; not added because tuning after the freeze is not allowed.
2. **Task-type inference.** Numeric targets with at most 20 distinct values are classified as classification, so ordinal scores (wine quality) are read as multiclass and adjacent-level confusion looks like label noise. The caller should pass `task_type`.
3. **Small n.** Three variants per type; zero misses on a type means "none seen in 3".
4. **No real ground truth.** Recall on real leaks is unmeasured; real_dev and real_heldout only measure false-positive behaviour.
5. **Positive-skewed unit mismatches** are not detected at medium.
6. **Process incident.** A test with a ledger path bound at import time ran the real v1 benchmark before the freeze commit and spent the ledger slot. The thresholds and detectors were already final (hash unchanged between that run and the freeze; no result was read before freezing, and nothing was changed afterwards). The bug is fixed with a regression test; the freeze tag was created after the run, so the "frozen before eval" ordering is by intent and hash equality, not by commit order.
