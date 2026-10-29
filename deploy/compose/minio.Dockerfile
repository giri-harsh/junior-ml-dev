# MinIO's public images are not reliably pullable; build from the official release binary.
FROM debian:12-slim
RUN apt-get update && apt-get install -y --no-install-recommends curl ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && curl -sSfL -o /usr/local/bin/minio https://dl.min.io/server/minio/release/linux-amd64/minio \
    && chmod +x /usr/local/bin/minio
EXPOSE 9000 9001
ENTRYPOINT ["minio"]
