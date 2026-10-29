FROM python:3.12-slim
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN pip install --no-cache-dir uv && uv sync --frozen --no-dev --extra infra --no-install-project
COPY . .
RUN useradd --create-home app && mkdir -p /app/data && chown -R app /app/data
USER app
ENV PATH="/app/.venv/bin:$PATH" PYTHONPATH=/app
EXPOSE 8000
