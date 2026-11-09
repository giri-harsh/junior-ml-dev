# Workstream A: E2B sandbox backend

Status: implemented, unit-tested against a mocked SDK, and run LIVE on 2026-11-07 against E2B with
e2b SDK 2.62.0 (the version coded and type-checked against). Numbers below come from
`benchmarks/results/e2b_v1.json`; per-test results are from the live pytest runs of that day.

## What exists

- `harness/sandbox/backends.py`: `E2BBackend` behind the existing `SandboxBackend` protocol
  (`run_python(code, timeout_s, files) -> ExecResult`), selected with `JMD_SANDBOX=e2b`.
  `E2BUnavailable` subclasses both `NotImplementedError` and `RuntimeError` and is raised when the
  key or the SDK is missing (nothing is spent).
- `harness/sandbox/e2b_live.py`: budget-gated `BudgetedE2B` (one `scripts/budget.py reserve e2b 1`
  per exec) and the latency measurement (`python -m harness.sandbox.e2b_live`).
- `tests/sandbox_e2b/`: mocked-SDK unit tests (always run, no network, no key, no `e2b` needed;
  two SDK-shape tests run only when `e2b` is installed).
- `tests/e2b/`: live suite, marker `e2b`, skipped (not failed) without `E2B_API_KEY`/`e2b`.

## Behaviour per exec

1. Refuse if `E2B_API_KEY` is unset; validate upload paths with `safe_relpath` (before any spend).
2. `Sandbox.create(timeout=timeout_s+30, allow_internet_access=False, metadata=..., api_key=...)`.
   The `+30` is a server-side expiry that bounds cost even if our kill call fails.
3. Create `/workspace` (same path as the Docker backend), upload `main.py` and only the files
   passed in `files`.
4. `python3 main.py` in `/workspace` with the SDK command `timeout`, inside a worker thread with a
   hard wall clock of `timeout_s + 5s`. If the call hangs past that, the sandbox is killed from
   the caller thread, which breaks the blocked call. Result: `timed_out=True, exit_code=-9,
   stderr="timeout"` (identical to the Docker backend).
5. Download only top-level `out_*` regular files <= 50 MB (same rule as `collect_outputs`).
6. `finally`: `box.kill()` always, also on timeout, upload failure, or any SDK error. A kill failure
   is counted (`kill_failures`) and logged, never masks the result. Per-stage timings are kept in
   `last_timings` (create/upload/exec/download/kill).

## Live results (2026-11-07)

Latency, 20 sequential execs of a tiny stdlib program, default template, internet disabled,
20/20 ok (`benchmarks/results/e2b_v1.json`, `total_s` = create+upload+exec+download):

| stage    | p50 s | p95 s | max s |
|----------|-------|-------|-------|
| total    | 1.871 | 2.673 | 2.682 |
| create   | 0.378 | 1.049 | 1.182 |
| upload   | 0.557 | 1.357 | 1.393 |
| exec     | 0.338 | 0.402 | 1.143 |
| download | 0.552 | 0.572 | 0.579 |
| kill     | 0.257 | 0.277 | 0.939 |

Kill time is not part of `total_s`. Small sample (n=20, one machine, one afternoon): treat as an
order-of-magnitude figure, not a benchmark.

Live suite on the default template (`pytest tests/e2b -q -rs`):

| test | result |
|------|--------|
| normal exec + `out_*` download | pass (stdlib-only program) |
| uploaded file visible in workdir | pass |
| non-zero exit and stderr reported | pass |
| network blocked | pass after the test was fixed (see below) |
| writes outside the workdir (`/etc`, `/usr`, `/root`) | pass: all 3 denied |
| fork bomb contained | pass: call returned within the wall clock, `kill_failures == 0` |
| timeout kills the sandbox | pass: `timed_out=True`, `exit_code=-9` |
| pandas parquet round trip | skipped without `JMD_E2B_PARQUET_TEMPLATE`; FAILS on `code-interpreter-v1` (no parquet engine) |
| end-to-end feature step through the agent runner (parquet) | skipped without `JMD_E2B_PARQUET_TEMPLATE`; FAILS on `code-interpreter-v1` (same reason) |
| agent-written feature code end to end, CSV, via `run_checked` | pass on `code-interpreter-v1` |

History: the first live run (default template) failed 3 tests (normal exec used pandas, network
used a bare connect(), parquet end to end); causes below, tests fixed.

**Final full run, exactly once, after the fixes (2026-11-09):**
`JMD_E2B_TEMPLATE=code-interpreter-v1 pytest tests/e2b -q -rs` -> **8 passed, 0 failed, 0 xfailed,
2 skipped** (the two parquet tests, which need `JMD_E2B_PARQUET_TEMPLATE`). All 7 isolation/exec
tests above plus the CSV end-to-end test passed on `code-interpreter-v1` (python 3.13). Counts are
stored in `benchmarks/results/e2b_v1.json` under `live_suite`. The 2 skips are a missing custom
template, not a failure; the parquet path itself is still unproven live.

### Network deny: what the live runs showed

`allow_internet_access=False` (also tried `network={"deny_out": ["0.0.0.0/0"]}`, alone and combined:
identical behaviour) does block traffic, but a bare `socket.create_connection` to 1.1.1.1:53 and
:443 SUCCEEDS (the handshake is accepted at the sandbox boundary). Measured with a real exchange:

- open sandbox (flag not set): HTTP request to 1.1.1.1:80 returns `HTTP/1.1 301`; DNS resolves.
- flag set: connect succeeds, `sendall` works, `recv` returns EOF with no data; DNS raises
  `gaierror`; `urllib` to example.com raises `URLError`.

So the sandbox is NOT CONNECTED in any useful sense, and the original test (connect() only) was the
wrong probe. It now requires `TCP_DATA=0` and `DNS=0`. No xfail was needed. Caveats: the TCP-level
behaviour means "connect succeeded" must never be used as a connectivity signal against E2B;
and the sandbox user has passwordless `sudo` (see below), so enforcement is only trusted to be
outside the VM, which these tests cannot prove.

### Other live facts

- Default template: python 3.11.x, user `user` (uid 1000, member of `sudo`, passwordless sudo),
  `/etc`, `/usr`, `/root` not writable by plain Python. No numpy, pandas, pyarrow, sklearn.
  Agent code is policy-checked (no subprocess/os.system), so `sudo` is not reachable from code that
  passed `run_checked`; the raw backend does not stop it.
- `code-interpreter-v1` (public template, exists): python 3.13.x, numpy 2.3.5, pandas 2.2.3,
  scikit-learn 1.6.1, scipy 1.17.1, NO pyarrow/fastparquet. `FEATURE_CODE` and the runner's feature
  step use parquet, so the parquet tests need a custom template with pyarrow. No custom template
  was built (it is a persistent account resource), so the two parquet tests skip unless
  `JMD_E2B_PARQUET_TEMPLATE` names one.
- Parquet gap, decision: installing pyarrow inside the sandbox is NOT possible without enabling
  internet, which this backend must not do. Measured: `pip install pyarrow` in a sandbox with
  internet disabled fails with "No matching distribution found" after 41 s (so it is neither
  <10 s nor possible). The requirement is therefore a template with pandas+pyarrow+scikit-learn.
  Build (NOT RUN, unverified; needs the E2B CLI and an E2B_ACCESS_TOKEN; the Dockerfile's
  `USER 65534` / `WORKDIR /workspace` may need adjusting because the backend runs as the template's
  default `user` and chowns `/workspace` to it):
  `e2b template build --name jmd-sandbox --dockerfile deploy/sandbox/Dockerfile`, then set
  `JMD_E2B_TEMPLATE=jmd-sandbox` and `JMD_E2B_PARQUET_TEMPLATE=jmd-sandbox`. Alternative with no
  new template: feature code that exchanges CSV instead of parquet (the CSV test passes live).
- Fork bomb: the exec returned within the wall clock and the sandbox was killed; the microVM is
  discarded, so there is no host impact. No per-exec pids/memory cap of our own is set.
- Creation is quick: p50 0.38 s. Most per-exec time is file upload/download round trips (~0.5 s
  each), not compute.

## Known limits

- `python -I` is NOT used (the Docker backend uses it): isolation is VM-level here.
- Interpreter and template are configurable (`python=`, `JMD_E2B_TEMPLATE`).
- `ExecResult.files` after a timeout is empty (as in the Docker backend).
- Cost per creation is E2B's pricing and is not modelled; budget used 48 of the 60-creation cap (39 earlier + 1 pip probe + 8 final suite).

## Re-run

Needs `E2B_API_KEY` in `.env` (never commit it) and `uv pip install --python .venv/Scripts/python.exe 'e2b==2.62.0'`.

```
set -a; . ./.env; set +a; JMD_E2B_TEMPLATE=code-interpreter-v1 PYTHONUTF8=1 .venv/Scripts/python.exe -m pytest tests/e2b -q -rs && PYTHONUTF8=1 .venv/Scripts/python.exe -m harness.sandbox.e2b_live
```

Suite: 8 creations with `JMD_E2B_TEMPLATE=code-interpreter-v1` (+2 with `JMD_E2B_PARQUET_TEMPLATE`);
latency (default template, env var scoped to pytest only): 20.

## Cross-path changes this workstream needs (not made here)

- `pyproject.toml`: optional dependency `e2b = ["e2b==2.62.0"]`, pytest marker
  `"e2b: live E2B sandbox calls; skipped without E2B_API_KEY"` (the tests/e2b conftest registers
  it too), and `-m "not ... and not e2b"` in default CI.
- `tests/unit/test_sandbox_policy.py::test_e2b_is_an_explicit_stub` passes only while no
  `E2B_API_KEY` is set (a set key would attempt a live creation); replace it with the no-key test
  in `tests/sandbox_e2b`.
- Optional: a custom E2B template with pandas, pyarrow and scikit-learn (built from
  `deploy/sandbox/Dockerfile`) to enable the parquet end-to-end test.
