FROM python:3.12-slim
# Libraries agent-written feature code may use. No network at run time (--network none).
RUN apt-get update && apt-get install -y --no-install-recommends libgomp1 \
    && rm -rf /var/lib/apt/lists/* \
    && pip install --no-cache-dir numpy==2.4.6 pandas==3.1.0 scikit-learn==1.9.1 pyarrow==26.0.0
USER 65534:65534
WORKDIR /workspace
