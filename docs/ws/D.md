# Workstream D: fresh critic evaluation set v2 (run 9)

Status: set and script authored and hash-committed. NO LLM call made (Groq 120/120, Gemini 111/120
used on 2026-10-30; the budget resets 2026-10-31 00:00 UTC). The critic (`harness/agent/critic.py`,
prompt and schema) is unchanged: this workstream is evaluation only.

## Files

- `benchmarks/critic_v2/gen.py`: deterministic generator, seed 9301 (run 7 used 7001).
- `benchmarks/critic_v2/set_v2.json` + `set_v2.sha256`: the set, 53 items, committed before any run.
  sha256 `bfdcaf09a5aa03463394a799311f9cf150a68d3abaef55d4c8ca0104415bf628`.
- `benchmarks/critic_v2/eval.py`: the one-shot evaluation.
- `tests/critic_v2/test_set_v2.py`: regenerates the set; asserts hash, counts, per-type coverage,
  and that each rule-fail item fails the real `check_baseline_margin`.

## The set

Item shape is the run-7 shape (`run_summary_v3` output plus a hidden `planted` label outside the
summary), so `enrich_v3` and the committed prompt apply unchanged. Items are shuffled with opaque
ids (`d00`..`d52`) so neither order nor id leaks the label.

23 planted (>= 2 per type) and 30 clean:

| planted type | n | how it is planted (what the committed prompt calls a blocker) |
|---|---|---|
| unresolved_leakage | 3 | `unresolved_leakage` non-empty, `leakage_resolved=false` |
| leakage_not_run | 2 | `leakage_detection_ran=false`, `leakage_checked=false` (new vs run 7) |
| gap_beyond_family_range | 3 | `gap_over_range_top` 2.2 to 2.7 (> 1.5) |
| tiny_test | 2 | `n_rows` 45 and 130 (`small_sample`) |
| cv_instability | 2 | `cv_se_ratio` 0.30 and 0.55 (> 0.2), lift still >= 1 |
| partial_leakage_check | 3 | `leakage_coverage = incomplete` (a non-"sampled" entry present) |
| rule_fail_baseline_margin | 4 | see the rule below |
| metric_task_mismatch | 2 | `metric_matches_task=false` (regression with roc_auc / f1_macro) (new) |
| lift_below_one | 2 | `lift_over_dummy_se` < 1 (new) |

Clean (30), all rule checks true, nothing material: 10 plain; 5 in-range high gaps for hgb / rf /
flaml (`gap_over_range_top` 0.7 to 0.95); 3 rows-sampled partial coverage (`sampled_rows`); 3
small-but-ok n (200, 250, 320); 2 budget exhausted; 3 noticeable but sub-threshold CV noise
(`cv_se_ratio` 0.10 to 0.17); 2 thin passing margins over linear (3 to 5 %); 2 with dropped columns.

## Fixing run 7's set-design flaw: the baseline-margin generation rule

Source of truth: `harness/review/checks.py::check_baseline_margin(agent, linear, dummy, metric)`
passes iff `benchmarks.metrics.passes` holds against BOTH linear and dummy. For a higher-is-better
metric: if `linear >= 0.98` then `agent >= linear`, else `agent >= linear * 1.02` (PASS_MARGIN = 0.02).
So the threshold is a 2 % relative margin over the linear baseline.

Run 7 drew random margins that were merely "a bit under" that threshold (and its clean items used
`linear = cv - U(0.012, 0.05)`, some of which the real check would also fail). A model could argue
"the agent is still ahead of linear" with true numbers, and the schema legitimately accepted it.

Rule for v2, applied to every `rule_fail_baseline_margin` item:

1. `cv` in [0.74, 0.90], `se` in [0.002, 0.006], dummy = 0.5, `linear < 0.98` (ceiling clause off).
2. `linear = round(cv + m, 4)` with `m = 0` (tie) or `m = max(0.01, 3..6 x se)` (agent worse). Hence
   `cv <= linear`: the chosen model is never better than the linear baseline, far below the
   `linear * 1.02` threshold, and the gap is at least 3 standard errors when not a tie.
3. `rule_checks.baseline_margin = false` is computed by calling the real `check_baseline_margin`,
   and the generator and the test both assert it is False. The only failing rule on these items is
   `baseline_margin` (gap, leakage and metric checks pass), and `cv` stays above the dummy, so the
   failure is purely the linear comparison.

Any dissent on such an item ("the model beats linear", "margin within noise in its favour") is wrong
by construction, and the result records `baseline_margin_dissent` (count of such dissents).

Other generator fixes (set design, not tuned on results): `baseline_margin`, `train_val_gap` and
`metric_matches_task` for ALL items come from the real check functions; clean items keep the absolute
train-CV gap <= 0.12 so they truly pass `train_val_gap`; `unresolved_leakage` holds finding types
only, as `run_summary` produces.

## Decisions

- Result guard and file: `benchmarks/results/critic_v4.json` already exists and is committed (the old
  v4-run critic agreement result, rendered by `scripts/render_results.py`), so a guard on it would
  refuse forever and writing to it would overwrite a published result. The guard and the result
  therefore use `benchmarks/critic_v2/critic_v2_eval.json` (inside the owned paths). Requested
  cross-path follow-up: after the run, a METRICS/render step can copy it where wanted.
- Providers: default chain (groq then gemini) as in run 7 for comparability; `eval.py` reserves 60
  requests on BOTH `groq` and `gemini` via `scripts/budget.py` (the actual provider is not known in
  advance), caps the gateway at 60 requests in total (`gw.max_requests`), then commits the actual
  per-provider usage (difference of `data/llm_usage.json`) and releases the rest, also on error.
- 53 items cost 53 requests uncached; 7 spare for repair/429 retries. `--complete` re-runs the SAME
  prompt for items that got no output, with the cap reduced by what the first pass spent.
- `requests_used` in the result is the cumulative count of uncached requests over all passes
  (`gw.stats["calls"]` already excludes cache and fixture hits); `--complete` reads it from the prior
  result, so repeated completions can never exceed the 60 total. Gateway construction sits inside the
  try/finally that settles the budget reservation.
- Pacing: 6 s after every uncached request (free Gemini tier rate-limits bursts).
- `scripts/budget.py` is not on this branch (added on another branch of the run); the script calls
  it by path and works once merged. Tests mock the helper.

## Resume command (after the budget reset, 2026-10-31 00:00 UTC; not before)

    PYTHONUTF8=1 .venv/Scripts/python.exe -m benchmarks.critic_v2.eval

It verifies the sha256, refuses if `benchmarks/critic_v2/critic_v2_eval.json` exists, reserves 60 per
provider through `scripts/budget.py` (a denial aborts with no call), runs critic v3 once over the
set with cassette `tests/cassettes/critic_v2.jsonl`, writes the result (recall and false-alarm rate
with Wilson 95 % CIs, per-type recall, `requests_used`, `error_statuses`, `vs_run7`) and commits the
actual usage. If items got no output: add `--complete`. Dry check without any LLM call: `--check`.

The result's `vs_run7` field compares with run 7 (10/15 recall, 1/19 false alarms) and says
explicitly: DIFFERENT set, not paired.

## First pass (run on 2026-10-31, source `benchmarks/critic_v2/critic_v2_eval.json`)

Partial: 45 of 53 items answered, 8 without output (d45, d46, d47, d50, d52 clean; d48, d51
unresolved_leakage; d49 cv_instability). Recall 15/20 (Wilson 95 % 0.53 to 0.89), false alarms 0/25
(0.00 to 0.13). Per type: cv_instability 1/1, gap_beyond_family_range 3/3, leakage_not_run 2/2,
lift_below_one 2/2, metric_task_mismatch 2/2, partial_leakage_check 3/3, tiny_test 1/2,
unresolved_leakage 1/1, rule_fail_baseline_margin 0/4. All four failing-margin items got an APPROVE
with a numeric `dissent` on `baseline_margin` even though cv <= linear: a documented weakness of the
committed critic, not changed here. 45 requests, no error statuses, `gateway_stats.structured_failed`
0, no cache or fixture hits.

## Completion (run 9, D2): `--complete` only fills the 8 no-output items

Same prompt, critic (`LLMCriticV3`), set (sha256 bfdcaf09...), cassette. The pass is labelled
`completion` in the result. Behaviour of the script after this change:

- reviews ONLY the rows whose `critic` is null; the other 45 rows are kept as they are;
- reserves `min(60 - requests_used, 20)` per provider (15 for the 45 already spent), caps the
  gateway at that number and settles the reservation in a `finally`;
- extends the result JSON: top-level numbers are the completed ones over all 53 items; the original
  first-pass results are kept verbatim under `first_pass` (with `first_pass_meta` = date and git sha
  of that run) and never overwritten, also over repeated completions; `completion` carries the label,
  attempted / filled / still-no-output ids, its own request count, gateway stats and error statuses;
- an item whose answer is schema-invalid after the one repair stays no-output (listed in
  `completion.still_no_output`); for items with a failed rule check the committed critic then
  defaults to concurring, counted in `forced_concurrence`.

Status: PENDING. No LLM call was made in this session: the live gateway has to load the provider keys
from a `.env` (the repo `.env` exists only in the main checkout, the loader also falls back to a
file outside the repo), and the auto-mode classifier denied loading them for the worktree run. The
budget was NOT reserved (reservation happens inside the script right before the calls). Budget on
2026-11-09: Groq 0/120, Gemini 0/120.

Resume command, from a checkout that has the keys in its `.env` (the main checkout):

    PYTHONUTF8=1 .venv/Scripts/python.exe -m benchmarks.critic_v2.eval --complete

Expected cost: at most 8 requests (15 reserved per provider, released afterwards), 6 s pacing.
