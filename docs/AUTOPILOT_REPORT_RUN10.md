# Autopilot report - run 10 (multi-agent close-out -> v0.3.0)

## CI status of main HEAD
UNVERIFIED. Since 2026-11-09 every GitHub Actions run on the PRIVATE repo ends in `startup_failure`
(push runs 42583961889, manual dispatch of `ci` 42584524699 and `web` 42584606495). The workflow
files are unchanged since the last runs that started (2026-10-31) and the public demo repo's Pages
workflow runs fine, so this looks like an account/billing limit (NEEDS_HARSH 4). Last real results:
`ci` red 2026-10-31 (mypy on the optional `e2b` import; fixed here), `infra` green.
Local gate: ruff, format, mypy clean; 672 passed, 10 skipped (no GTK on Windows), coverage 92.60%
(floor 91%; it was 90.66% before the coverage-fill tests; the floor was NOT lowered).

## Agents
| Agent | Status | Verifier | Key numbers |
|---|---|---|---|
| A2 E2B live | merged | PASS | 20/20 execs, total p50 1.87 s / p95 2.67 s; suite 8 passed, 2 skipped; 48/60 creations |
| B2 demo | merged | PASS (+4 fixes, republished) | static site live, 10/10 checks, p50 page 9.5 ms |
| C2 injection verify | done | PASS | numbers reproduce; wording caveats applied to docs |
| D2 critic completion | merged | PASS | recall 18/23, false alarms 0/30 |
| F coverage fill | merged | self-gated | +56 offline tests, 90.66% -> 92.60% |

## Demo
Option used: (3) static site (Hugging Face returned 402 for Docker and Gradio Spaces; streamlit is
no longer an SDK). URL https://giri-harsh.github.io/junior-ml-dev-demo/ , public repo
`giri-harsh/junior-ml-dev-demo` (13 files, 1 commit). Verified live: all pages 200 and byte-identical
to `site/`, 3 example runs rendered (scripted planner; 88.0 / 68.5 / 77.6 s under load). No cold
start (static). The source repo stays private. Public commit metadata shows the real gmail address
(NEEDS_HARSH 5).

## E2B
8 passed, 0 failed, 0 xfailed, 2 skipped (parquet tests need a custom template; in-sandbox pip is
impossible with internet off). Network deny holds (no data, no DNS) though the TCP handshake
completes; the default template has passwordless sudo. Source `benchmarks/results/e2b_v1.json`.

## Injection verification (C2)
PASS. Fresh set hash e45a51c0 precedes the result by about 23 h; 0/14 attacker actions (Wilson upper
0.215); the 1 non-train/finish proposal was a benign `read_file train.csv`; scanner flagged 1/14
(8/8 on its tuning set). The 5 injected runs never exposed the payload to the planner, so they show a
null exposure, not robustness.

## Critic v2 (completed)
First pass 15/20 and 0/25 (8 items lost to the gateway token budget, not provider failures);
completion of those 8 with the same prompt: 18/23 (Wilson 0.58-0.90), 0/30 false alarms
(0.00-0.11). Failing-margin items stay 0/4 (numeric dissent). Different set from v1, not paired.

## Release
v0.3.0 (notes state that CI could not run).

## Budgets
LLM today (UTC 2026-11-09): groq 8, gemini 0 (cap 120 each). E2B 48/60. HF builds 0/6. CI ledger
4/20 runs, 4/250 min (startup failures plus the demo repo's Pages run).

## NEEDS_HARSH (real walls)
HF PRO for Docker Spaces; real MinIO; a cloud-deploy account; GitHub Actions billing for the private
repo; decision on the gmail address in the public demo repo's commit metadata.

## Decisions
140 critic completion (token-budget cause corrected); 141 static demo after HF 402; 142 coverage floor
kept at 91 (tests added); 143 release with CI unverifiable, stated in the notes.

## Git
Tags (new only, no -f): v0.3.0, plus r7-* from run 7. Merged local branches deleted with -d; clean
worktrees removed (B2's ignored `data/demo` scratch went with its worktree; the site is already
published); `ws-f-coverage` worktree left (locked). Attribution grep over 80 commits: empty. Pushed.

## Estimated complete
About 93%; open: CI (billing) and a live Space.
