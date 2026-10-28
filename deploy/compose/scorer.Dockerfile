FROM python:3.12-slim
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN pip install --no-cache-dir uv && uv sync --frozen --no-dev --no-install-project
COPY apps ./apps
COPY benchmarks ./benchmarks
COPY trajectory ./trajectory
ENV PATH="/app/.venv/bin:$PATH" SCORER_DATA=/scorer_data
CMD ["uvicorn", "apps.scorer.service:app", "--host", "0.0.0.0", "--port", "8001"]
