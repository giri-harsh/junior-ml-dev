# Demo S3

```bash
uv run python -m benchmarks.run_benchmark --baselines --time-budget 30   # -> benchmarks/results/baselines_v0.json
uv run python -m benchmarks.planted_bugs.generate --out data/planted_bugs --verify --result-name planted_bugs_v0
uv run pytest tests/unit/test_benchmark_metrics.py tests/unit/test_planted_bugs.py -q
```
Bugged-vs-twin pair: see `naive_cv_bugged` / `naive_cv_twin` per variant in `benchmarks/results/planted_bugs_v0.json`.
