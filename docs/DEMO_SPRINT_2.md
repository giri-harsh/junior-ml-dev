# Demo S2

```bash
uv run python -m benchmarks.fetch --all
uv run pytest tests/unit/test_scorer_core.py -q
```
`test_perfect_and_dummy_scores` scores a perfect file (RMSE 0.0) and a mean-dummy file through the scorer API.
