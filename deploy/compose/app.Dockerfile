FROM python:3.12-slim
WORKDIR /app
# lightgbm/xgboost need the OpenMP runtime, which python:slim lacks
RUN apt-get update && apt-get install -y --no-install-recommends libgomp1 && rm -rf /var/lib/apt/lists/*
COPY pyproject.toml uv.lock ./
RUN pip install --no-cache-dir uv && uv sync --frozen --no-dev --extra infra --no-install-project
COPY . .
RUN useradd --create-home app && mkdir -p /app/data && chown -R app /app/data
USER app
ENV PATH="/app/.venv/bin:$PATH" PYTHONPATH=/app
EXPOSE 8000
