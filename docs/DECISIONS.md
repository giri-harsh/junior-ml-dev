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
