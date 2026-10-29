"""Locust scenarios: the predict-service container and the API container.

Env: PREDICT_URL (default http://localhost:18000), API_URL (http://localhost:8000),
LOAD_USER/LOAD_PASSWORD (admin credentials for the authenticated endpoint), LOAD_TARGET
= predict | api | both (default both). The example request comes from the bundle.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from locust import HttpUser, between, task

TARGET = os.environ.get("LOAD_TARGET", "both")
EXAMPLE = json.loads(Path(os.environ.get("LOAD_EXAMPLE", "load_example.json")).read_text("utf-8"))


class PredictUser(HttpUser):
    host = os.environ.get("PREDICT_URL", "http://localhost:18000")
    wait_time = between(0.0, 0.05)
    weight = 3 if TARGET in {"predict", "both"} else 0

    @task(9)
    def predict(self) -> None:
        self.client.post("/predict", json=EXAMPLE, name="predict (3 rows)")

    @task(1)
    def health(self) -> None:
        self.client.get("/health", name="predict health")


class ApiUser(HttpUser):
    host = os.environ.get("API_URL", "http://localhost:8000")
    wait_time = between(0.0, 0.1)
    weight = 1 if TARGET in {"api", "both"} else 0

    def on_start(self) -> None:
        self.client.post(
            "/v1/auth/login",
            json={"user": os.environ["LOAD_USER"], "password": os.environ["LOAD_PASSWORD"]},
            name="login",
        )

    @task(5)
    def healthz(self) -> None:
        self.client.get("/healthz", name="api healthz")

    @task(3)
    def metrics(self) -> None:
        self.client.get("/metrics", name="api metrics")

    @task(2)
    def audit(self) -> None:
        self.client.get("/v1/audit", name="api audit (auth)")
