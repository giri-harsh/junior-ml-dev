# ADR-011: Sandbox backends and the AST code policy (PRD S10)

Status: accepted (S9 of this run)

## Decision
Agent code passes `harness/policies/code_policy.check_code` and then runs through a `SandboxBackend` (fresh workspace per run, hard timeout, capped output) via `run_checked`, which is the only entry point. The policy bans network/process/ctypes modules (including aliases and `from` imports), `eval/exec/compile/__import__`, `os.system/popen`, sandbox-escape attributes (`__subclasses__`, `__globals__`, ...), `getattr(os, "system")`-style indirection, `open()` outside `/workspace` or on hidden names (scorer, test_labels, `.env`, `..`), and `open()` with a non-literal path. A refusal returns every violated rule; nothing is executed.

## Backends
| Backend | Status |
|---|---|
| SubprocessSandbox | works; scrubbed environment; **not an isolation boundary**; dev/test only; MCP server needs `JMD_SANDBOX=local-unsafe` |
| LocalDockerBackend | command builder tested (`--network none --read-only --user 65534 --cap-drop ALL --pids-limit`); execution NOT RUN (no Docker) |
| E2BBackend | STUB |

## Why the policy is not enough
Static checks miss reflection, string-built attribute names and library-internal I/O. They exist to give clear refusals and to block the obvious; the container (network none, read-only root, non-root, caps dropped) is the boundary.

## Not delivered
Egress, filesystem-escape and fork-bomb tests need a real isolated backend (NOT RUN). `list_files`, `read_file`, `upload_workspace` are not offered: workspaces are discarded after each run and files travel in the request. The E2B template with `jmd_runtime` (S10.3) is not built.

## Tested (46 tests)
31 banned-code fixtures each blocked with the expected rule; good training snippet allowed; refusal precedes execution (marker file not created); env scrubbed (a parent secret is invisible); fresh workspace per run; timeout kills; path-traversal guard (found and fixed a Windows bug: `/abs` was not rejected); MCP smoke over stdio incl. refusal without a backend.
