# S3-compatible endpoint for dev/CI. MinIO stopped publishing pullable images and binaries, so the
# service named `minio` is a moto S3 server (same S3 API; real MinIO is NOT verified here).
FROM python:3.12-slim
RUN pip install --no-cache-dir "moto[server]>=5,<6"
EXPOSE 9000
CMD ["moto_server", "-H", "0.0.0.0", "-p", "9000"]
