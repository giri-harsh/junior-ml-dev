# Contributing

## Set up

```bash
uv sync --group dev --extra infra      # Python 3.11
python scripts/tasks.py hooks          # pre-commit secret scan
```

## The gate (run before every merge; CI runs the same)

```bash
python scripts/tasks.py gate           # ruff check, ruff format --check, mypy, pytest (unit)
```

`python scripts/tasks.py --help` lists every task (tests, infra tests, results rendering, docs
generation, changelog, release notes).

## Rules the project enforces

- **Numbers come from code.** Every figure in docs is generated from `benchmarks/results/*.json`
  (`scripts/render_results.py`, `scripts/render_metrics.py`); each file carries a conditions block
  (planner, LLM real/none, versions, git sha).
- **Eval-once.** A held-out partition is evaluated once per frozen hash. The ledger entry is
  written before the run (`benchmarks/eval_ledger.json`). Anything whose results you have read is
  burned for design. Tests must never touch the real ledger or real result files.
- **No special-casing** of dataset names, labels or generator metadata at runtime.
- **Untrusted data.** Dataset content, column names and tool output never reach an LLM prompt or an
  instruction channel; the planner sees numbers and family names only.
- **Secrets.** Never commit `.env`; keys are loaded by name through `harness/gateway/envload.py`.
  `python scripts/secret_scan.py` runs in the hook and in CI (gitleaks).
- **LLM caps.** 120 requests per provider family per UTC day, 2 s spacing, enforced in code.
  Everything is cached in cassettes under `tests/cassettes/`.
- **Decisions** are one numbered line in `docs/DECISIONS.md` (decision, why, rejected alternative);
  architecture-level ones get an ADR in `docs/adr/` (index: `docs/adr/README.md`).

## Tests

`pytest -m "not infra and not llm and not compose"` is the unit suite. `infra` and `compose` tests
need Docker/Postgres/Redis/S3 and run in CI (`infra.yml`); they fail instead of skipping when
`INFRA_REQUIRE=1`. `llm` tests make live calls and are skipped without keys.
