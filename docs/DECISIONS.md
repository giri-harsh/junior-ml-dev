# Autonomous decisions

Format: decision | alternatives | why.

1. Proceed on PRD alone; `docs/SPEC.md` is missing on this machine (only an unrelated ApplyPilot SPEC.md exists). Spec section refs (§6.3, §11, §15, §21, §23) are derived from the PRD text. | stop and ask | Step 3 of the brief says proceed and flag it.
2. Single `pyproject.toml` project, not a multi-member uv workspace. | uv workspace members | No packaging boundary needs it yet; revisit if services need separate lockfiles.
3. `scripts/tasks.py` is the real task runner; `Makefile` delegates to it. | Makefile only | Windows 11 without `make`.
4. Secret scanning: gitleaks in CI; `scripts/secret_scan.py` regex fallback for the local hook (gitleaks not installed locally). | require gitleaks locally | Brief allows a regex pre-commit fallback.
5. Docker is not installed on this machine, so compose files are written but unvalidated locally and integration tests are marked `integration` with a separate target. | skip silently | Rule: never skip integration tests silently; they are tracked in STATE.md as BLOCKED-SOFT until Docker Desktop/WSL2 is available.
6. LocalDocker sandbox cannot run here without Docker; S10 will ship a `FakeSandbox` for unit tests and gate the Docker tests as `integration`. | defer S10 | Keeps work unblocked.
7. SQLite is used only in unit tests for the DB sink; main profile is Postgres. | Postgres-only tests | Brief permits SQLite for unit tests only.
8. Python target `>=3.11`; dev interpreter is whatever uv resolves (3.14 present, 3.12 available). | pin 3.12 | CI will use uv default; pin later if a dependency lacks wheels.
9. langfuse pinned to v2 (single container + Postgres) in the `full` profile. | v3 (needs ClickHouse, Redis, S3) | RAM; v3 is too heavy for the machine.
10. `/readyz` DB probe uses a 2 s connect timeout. | default OS timeout | A down DB made the test take 130 s on Windows.
11. Git remote: `giri-harsh/junior-ml-dev` does not exist on GitHub; `gh` is authenticated. Creating a public repo is outward-facing, so S1 stays local until the user confirms visibility. | create now | Publishing is irreversible-ish and was not explicitly authorised for visibility.
12. `.gitattributes` forces LF | CRLF autoconvert | Shell hook and compose files break with CRLF on Linux/CI.
13. Remote stays local by user choice (2026-10-28); revisit at M1.
14. fetch_openml uses parser=liac-arff | parser=auto | The pandas ARFF parser raises TypeError on pandas 3 categorical columns; the fallback to synthetic hid it, so check source.json origin.
15. DVC skipped; raw data cached in gitignored data/tasks/_raw | DVC remote | Adds a tool for no gain while remote is local-only; re-fetch is deterministic.
16. Planted-bug generator uses synthetic base data (make_classification), not benchmark tasks. | derive from registry tasks | Keeps ground truth exact and runs in seconds; real-data bugs can be added in S25.
17. temporal_leak and group_leak are additive shortcuts (rows assigned to time blocks/groups whose regime matches the label with probability s); features and labels untouched. | overwrite labels | The first attempt overwrote labels and made bugged variants score lower than twins.
18. Baselines scored in-process through the scorer's FastAPI app (TestClient), not HTTP between containers. | HTTP | Same code path and auth, no Docker dependency.
19. FLAML restricted to lgbm/xgboost/rf/extra_tree, 3-fold CV, seed 0, 30 s per task. | default estimators | Predictable runtime on 16 CPUs; budget recorded in the result conditions.
20. Follow the S4 brief (data-tools MCP + leakage detector) over the PRD's S4 (ingest/quality scorecard). | do PRD S4 | The brief is the newer, explicit goal; PRD S4 profile pieces and the S8 protocol are reused.
21. Official `mcp` SDK 2.x (`MCPServer`, stdio), pinned by uv lock. | pin mcp<2 for FastMCP | v2 is current; the v1 API is gone.
22. Evaluation is at detector-family level: a medium/high finding whose family equals the planted `expected_detector` is a hit; `low` is advisory. | exact column match required | Column hits are reported separately (1.0 where defined).
23. No detector for `label_noise`; recall reported as 0. | confident-learning heuristic | No deterministic label-free method was built; not faked.
24. Dev-tuned thresholds: temporal min_gap 0.07, group min_gap 0.015 (one iteration each). | tune on eval | Brief forbids eval tuning.
25. Target-leakage scan skips only id-like and time-like columns (not group-like). | skip group-like too | A unit test showed string group-like columns hiding high-cardinality proxies; changed before the freeze.
26. Cooperative time budget instead of a hard kill. | subprocess per call | Simpler; limitation recorded in ADR-006.
27. Duplicates by exact+rounded row hash, not MinHash. | datasketch | Planted duplicates are exact; MinHash deferred.
28. Real tasks run on the agent-visible train split with row_id dropped; all findings recorded unsuppressed. | hide noisy findings | Brief says do not suppress.
29. Eval-once guard = frozen-hash assertion + refusal to overwrite leakage_v0.json. | convention only | Enforced in code and tested.
30. MCP tool-manifest hash pinning deferred to S12. | add now | Out of S4 scope.
31. Probes use difference-in-differences (cost of removing the column under random vs time/group CV), not a raw CV gap. | raw gap | A raw gap fires on any strongly predictive feature used as the sort key.
32. Medium/high requires confirming evidence; name hints alone are LOW notes. | keep name-based medium | S4 produced 100% real-task false-alarm rate.
33. Duplicates confirmed only with >=2 near-continuous matched columns. | conflicting-label rule | Natural repeats on low-resolution columns are common; copies of continuous values are not chance.
34. Identifier = string, id-named, or contiguous integer range; time tokens drop `day`/`dt`. | structural unique-ratio only | Count-like unique integers (bytes read) are features.
35. unit_mismatch = scale mixture (power-of-ten spread ratio, near-symmetric). | log-magnitude bimodality | The log test fired on every Gaussian column (tuning round 1).
36. label_noise = confident learning, classification only; regression returns a LOW N/A finding. | skip regression silently | Brief asks for an explicit not-applicable finding.
37. real_dev = 16 OpenML/sklearn tables disjoint from the 10 tasks, cached with hashes. | seaborn datasets | Already available through the same fetch path.
38. Eval-once ledger keyed by thresholds hash, claimed before running, partial results resumable. | frozen-file check only | Survives crashes without allowing a second look.
39. Spent v1 slot via test bug is disclosed, not rerun; thresholds unchanged. | rerun after tag | A rerun would only add a second look; the first run used the identical hash.
40. wine_quality/churn false positives left unfixed after freeze (ADR-007 limitations 1-2). | retune | Brief forbids retuning after the freeze.
41. Datasets content-addressed by sha256[:16]; re-upload of identical bytes is a no-op. | random ids | PRD: versioned by hash.
42. Local ObjectStore behind a Protocol; MinIO and arq are STUBs. | block on services | Docker/Redis absent; interface keeps the swap cheap.
43. Timeliness needs an explicit `as_of`. | use today's date | Keeps the scorecard deterministic.
44. Text columns detected with is_string_dtype (pandas 3 str dtype), not dtype == object. | object check | pandas 3 default string dtype.
45. Verifier derivations: ratios and percent-of across all fact pairs, sums/differences only within one unit group (key suffix). | all pairs | Cross-unit sums matched wrong numbers by coincidence (1.6k vs 1500 + 91.3).
46. Verifier accepts either half-up rounding or Python float formatting. | half-up only | 1.865 formats as 1.86 but rounds half-up to 1.87; template output must always verify.
47. Negative claims keep their sign; a positive claim may match a fact's magnitude. | strip signs | Stripping signs made "-0.74" fail against -0.7356.
48. insights.py disables a few mypy codes (pandas scalar unions). | cast everywhere | Behaviour is unit-tested; casts would add noise.
49. Hand-written retry/backoff/breaker instead of tenacity. | tenacity | Injectable clock/sleep/rng make tests deterministic without monkeypatching.
50. Breaker counts failures per provider after retries are exhausted, not per attempt. | per attempt | A single 429 burst should not open the circuit on its own.
51. Budget check reserves `max_tokens` before the call and charges actual usage after. | check after only | Gives a hard stop without overshoot.
52. Caption prompts carry facts JSON plus capped, sanitised column names inside <untrusted> tags. | raw schema | Column names are untrusted data (PRD security invariant).
53. Sandbox MCP refuses to execute unless JMD_SANDBOX is set (docker or local-unsafe). | default to subprocess | Shipping an unisolated code-execution tool on by default would be an RCE footgun.
54. Policy runs before backend resolution in the MCP tool. | backend first | Refusals must work with no backend and cost nothing.
55. open() with a non-literal path is a violation. | allow dynamic paths | A static check cannot prove a dynamic path is inside /workspace.
56. Offer run_python/check_policy/install_allowed only; fresh workspace per run. | persistent workspace tools | PRD S10.5 requires a fresh sandbox per run.
Updated rule: every Python-driven file edit must pass encoding='utf-8' (cp1252 corrupted STATE.md once).
57. Reviewer is deterministic-only in this run; no LLM reviewer. | stub LLM reviewer | Nothing to verify without a model; the PRD says code decides.
58. Injection oracle = simulated compliant agent vs structural guard; behaviour-change rate reported "not run". | fabricate an LLM rate | No LLM available; rule 1 forbids invented numbers.
59. Flagged names are aliased (col_NNN), not deleted. | drop columns | The column may be a real feature; the alias map is server-side.
60. Evasion payloads included in the suite and reported separately. | only template payloads | Template-only results would overstate the heuristic.
61. Python-driven edits must avoid backslash-b in heredoc strings (turned into backspace characters once); use chr(92) or the Edit tool. | ignore | Corrupted a regex silently.
