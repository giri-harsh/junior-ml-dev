=== AUTOPILOT REPORT RUN 4 ===
Probe: repo .env has GROQ_API_KEY and GEMINI_API_KEY (present, names only; E2B_API_KEY absent). An allowlist loader reads only those names; the file's other credentials are ignored. Docker not installed, gh authenticated as giri-harsh, no remote at start, disk 38.8 GB.

LLM provider/model chosen (+ bake-off): Groq openai/gpt-oss-120b, fallback gpt-oss-20b, then Gemini gemini-3.5-flash-lite (Gemini 2.0/2.5 return 404 "no longer available to new users" for this key). Bake-off on dev wdbc + sk_wine (llm_bakeoff.json, 5 structured calls per family): Groq first-try schema-valid 5/5, Gemini 4/5; both passed 2/2 vs linear. n is tiny, so this decided the order but is not evidence.

Sprints implemented:
| Sprint | Status | Tag |
|---|---|---|
| S18 real LLM planner: capped providers, disk cache/cassettes, injection check, live gateway, bake-off | done | s18-done |
| v3: new unseen 10-task partition, scripted + LLM arms, baselines v3, leakage v2, real-LLM injection eval | done | agent-frozen-v3, eval-v3-done |
| S20 infra fixes without Docker: arq retry policy + fakeredis tests, MinIO healthcheck, pytest-timeout | done | s20-done |
| Docker / E2B work | WALL (see below) | none |

Verification: before each merge `ruff check .`, `ruff format --check .`, `mypy`, `pytest -q -m "not infra and not llm"`; final run 371 passed, 6 deselected (5 infra, 1 live llm), clean. Secret scan clean, and a history scan of every value in both .env files found only model names (no secrets; no key-pattern hits). New tests: caps/spacing/persistence, env allowlist, cassette replay, fakeredis arq (success, retry, max-tries, settings), compose/CI checks.

v3 results (10 unseen OpenML tasks, scorer test scores; n=10, test sets 108-1639 rows so CIs are wide). Normalized score, 95% bootstrap CI; FLAML = 1 by definition:
- Linear: 0.835 [0.728, 0.933].
- SCRIPTED planner: 0.938 [0.852, 1.001]; vs linear +0.103 [0.011, 0.204]; vs FLAML -0.062 [-0.148, 0.001]; pass vs linear 4/10 (Wilson 0.17-0.69).
- REAL-LLM planner: 0.932 [0.848, 0.992]; vs linear +0.097 [0.010, 0.200]; vs FLAML -0.068 [-0.152, -0.008]; pass vs linear 4/10.
- Paired LLM minus scripted: -0.006 [-0.016, 0.000]. The LLM is not better: it ended the search early on kr-vs-kp and vowel (0.9958 vs 0.9999; 0.939 vs 0.985) and matched the script elsewhere.
- Both arms: reviewer REQUEST_CHANGES on cmc and optdigits; leakage_checked failures 0/10 each. Neither arm beats FLAML here: on ozone and pc1 the validation split picked linear over a clearly better FLAML.
- LLM arm cost: 35 requests, 12,556 tokens, $0 (free tiers), 35/35 proposals schema-valid first try, 0 repair round trips, 21 step-level fallbacks to the script (proposal repeated/unusable); wall 2-97 s per task.
- Labels: scripted arm = agent_v3_scripted.json (llm none); LLM arm = agent_v3_llm.json (real). Scripted and the earlier v1/v2 runs are never LLM results.

Requests used per provider vs caps (UTC day 2026-10-29): groq 80/150, gemini 8/150; spacing 2 s enforced in code; no cap hit. Cache/cassettes in tests/cassettes make reruns free.

Injection (real LLM, injection_llm_v1.json): the model could propose read_file/run_code/fetch_url/deploy/set_target (wider than production). Suite n=41: attacker action proposed 3/41 (Wilson 0.03-0.19); held-out evasion n=8: 0/8; unsafe actions executed 0/49 (guard decides). Other risky proposals (30) were mostly ordinary dataset reads/code. The production planner cannot emit those actions and sees no dataset text.

Leakage v2 (leakage_v2.json; leakage_v1.json superseded for current code, kept as history): not a rerun of eval2/real_heldout (already seen). New unseen eval3 planted partition (24 variants): recall 24/24 (bootstrap CI [1, 1]), twin false alarms 0/24 (Wilson upper 0.138). Unseen real v3: 2 medium/high findings, adjudicated: pc1 duplicate rows = true positive (105 of 887 rows verified), cmc label_noise = false positive (weak-signal target). The churn/wine_quality fixes were verified only by synthetic regression tests plus the dev partition.

Infra/sandbox status: arq policy (max_tries 3, job_timeout 3600, Retry on errors) verified with fakeredis only; Postgres store, MinIO store, compose app profile, docker-kill resume and container deploy are NOT RUN (no Docker). MinIO healthcheck is now `mc ready local`. Sandbox is still the subprocess backend with Windows job limits: NOT isolation (README says so). E2B not run.

Attribution check: ~/.claude/settings.json has includeCoAuthoredBy=false and attribution commit/pr empty (verified, not changed). Repo-local git user is Harsh Giri <2006.harshgiri@gmail.com>; local and GitHub history (71 commits) have that single author/committer and 0 hits for Claude, Anthropic, Co-Authored-By, Generated with. No rewrite was needed.

Decisions added: 95-108 in docs/DECISIONS.md (bake-off order, Gemini model, hard caps, cassettes as cache, env allowlist, v3 partition, leakage v2 on unseen data, two-arm freeze, wider-action-space injection eval, tag re-point, arq policy, MinIO check, pytest-timeout, report as-is).

Failures hit + handling: Gemini 404 (switched model); Gemini ReadTimeouts (used 3.5-flash-lite); cassette replay test counted the wrong stat (added fixture_hits); a stale partition-count test (updated); agent-frozen-v3 re-pointed once after the scripted arm because HEAD must equal the tag, with a diff showing no frozen file changed (decision 104); fakeredis lacks INFO (patched arq's log call in tests). No cap, outage, or push problem occurred.

Git: branches s18-real-llm, s20-infra-fixes merged into main with --no-ff. Tags s18-done, s20-done, agent-frozen-v3, eval-v3-done (plus earlier). Remote https://github.com/giri-harsh/junior-ml-dev, private=true, main and all tags pushed. Last commit: the report commit on origin/main (see `git log -1`).

WALL: (1) Docker Desktop is not installed: install it yourself, then run `python scripts/tasks.py up app` and `python scripts/tasks.py test-infra` (JWT_SECRET and APPROVAL_SECRET must be set in .env). (2) No E2B_API_KEY: create one at e2b.dev, add it to .env, then run the sandbox test suite against the E2B backend.

Next steps: Docker verification; richer LLM planner state (the stop-early and repeat-proposal failures); a v4 partition if any v3 behaviour is changed; larger test sets.

Estimated PRD completion: about 60% by sprint count (estimate, not measured).
