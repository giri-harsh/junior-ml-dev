# Workstream A: E2B sandbox backend

Status: implemented and unit-tested against a MOCKED SDK. NOT run live: `E2B_API_KEY` is not in
`.env` (LIVE_E2B=no). No latency or isolation number exists yet and none is claimed.

## What exists

- `harness/sandbox/backends.py`: `E2BBackend` behind the existing `SandboxBackend` protocol
  (`run_python(code, timeout_s, files) -> ExecResult`), selected with `JMD_SANDBOX=e2b`.
  The old stub test contract is kept: `E2BUnavailable` subclasses both `NotImplementedError` and
  `RuntimeError` and is raised when the key or the SDK is missing (nothing is spent).
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

## Network deny

E2B SDK 2.62.0 supports `allow_internet_access=False` at creation; the backend always sets it.
This is enforced by E2B's sandbox network layer, not by us. It is UNVERIFIED live. The live test
`test_network_is_blocked` checks it with a raw socket to 1.1.1.1:53. If that ever prints CONNECTED,
convert it into an `xfail(reason=...)` and record the limitation here; do not delete the test.
Limits of the mocked tests: they only prove the flag is passed, not that E2B honours it.

## Known limits and assumptions (all unverified live)

- Code runs as the template's default non-root user `user` (the `/workspace` chown assumes it
  exists). The "writes outside the workdir" test relies on that user being unable to write to
  `/etc`, `/usr`, `/root`.
- The default E2B template may not ship pandas/pyarrow/scikit-learn. The end-to-end test needs a
  template that does; set `JMD_E2B_TEMPLATE=<template id/name>` (also read by `E2BBackend`).
- `python -I` is NOT used (the Docker backend uses it): isolation is VM-level here, and `-I` would
  hide user-site packages some templates install. Interpreter is configurable (`python=`).
- There is no per-exec memory/CPU/pids cap of our own; the fork bomb is contained by the microVM
  and by killing it. Cost per creation is E2B's pricing and is not modelled here.
- `ExecResult.files` after a timeout is empty (as in the Docker backend).

## Resume: live suite plus latency (needs a key; costs ~28 of the 60 creations)

Prereqs: put `E2B_API_KEY=` in `.env` (never commit it), `uv pip install --python .venv/Scripts/python.exe 'e2b==2.62.0'`, and optionally `export JMD_E2B_TEMPLATE=<template with pandas+pyarrow+sklearn>`.

```
set -a; . ./.env; set +a; PYTHONUTF8=1 .venv/Scripts/python.exe -m pytest tests/e2b -q -rs && PYTHONUTF8=1 .venv/Scripts/python.exe -m harness.sandbox.e2b_live
```

The second command makes 20 sequential execs of a tiny program (reserves 20 `e2b` creations), then
writes `benchmarks/results/e2b_v1.json` through `benchmarks/results_writer.write_result`
(`total_s` and per-stage p50/p95/max, plus failures; it raises rather than write numbers if every
exec failed). Live suite: 8 tests, 8 creations.

## Cross-path changes this workstream needs (not made here)

- `pyproject.toml`: optional dependency `e2b = ["e2b==2.62.0"]`, pytest marker
  `"e2b: live E2B sandbox calls; skipped without E2B_API_KEY"` (the tests/e2b conftest registers
  it too, so the suite works before this lands), and `-m "not ... and not e2b"` in default CI.
- `tests/unit/test_sandbox_policy.py::test_e2b_is_an_explicit_stub` still passes only while no
  `E2B_API_KEY` is set; it should be replaced by the no-key test in `tests/sandbox_e2b`.
