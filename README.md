# junior-ml-dev

The junior ML engineer that shows its work and catches its own mistakes.

Status: Sprints 1-4 done (foundations, scorer, baselines + planted bugs, data-tools MCP with leakage detective). Leakage results: `benchmarks/results/leakage_v0.json`.

## Results

Every number here must come from a file in `benchmarks/results/`. Until then:

| Metric | Value |
|---|---|
| Pass rate vs linear baseline | pending |
| Normalized score vs FLAML | pending |
| Leakage catch rate | pending |
| False-alarm rate | pending |

Baselines (source: `benchmarks/results/baselines_v0.json`; 10 tasks, FLAML 30 s/task, no LLM): per-task dummy/linear/FLAML scores and the mean normalized linear score with a bootstrap CI are in that file.

## Quick start

```bash
uv sync --group dev
python scripts/tasks.py test      # unit tests
python scripts/tasks.py lint      # ruff + mypy
python scripts/tasks.py up        # docker compose micro profile (needs Docker)
```

## Configuration

Copy `.env.example` to `.env`. Optional keys: `GROQ_API_KEY`, `GEMINI_API_KEY`, `E2B_API_KEY`. Without them the project uses mock and local fallbacks.

Plan: `PRD.md`. Progress: `docs/STATE.md`. Decisions: `docs/DECISIONS.md`, `docs/adr/`.
