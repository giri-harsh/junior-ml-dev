"""arq + Redis job queue (producer side) and the worker entrypoint.

The agent's own checkpoints (Postgres run store) make a job safe to re-deliver: a worker killed
mid-run leaves the arq job in the queue; arq re-delivers it once the dead worker's in-progress
key expires (job timeout + 10 s, set via ARQ_JOB_TIMEOUT), and the runner resumes from the last
checkpoint. NOT RUN on this machine (no Redis): verify with
`pytest -m infra tests/infra` after `python scripts/tasks.py up app`.

Worker: `arq harness.queue_arq.WorkerSettings`
"""

from __future__ import annotations

import asyncio
import os
from typing import Any


class QueueUnavailable(RuntimeError):
    pass


def _redis_settings() -> Any:
    from arq.connections import RedisSettings

    return RedisSettings.from_dsn(os.environ.get("REDIS_URL", "redis://localhost:6379/0"))


class ArqJobQueue:
    """Implements the enqueue side of `harness.queue.JobQueue` (arq owns claim/complete)."""

    def __init__(self, redis_dsn: str | None = None) -> None:
        if redis_dsn:
            os.environ["REDIS_URL"] = redis_dsn
        try:
            import arq  # noqa: F401
        except ImportError:
            raise RuntimeError("arq is not installed; use `uv sync --extra infra`") from None

    def enqueue(self, run_id: str, payload: dict[str, Any]) -> str:
        async def go() -> str:
            from arq import create_pool

            settings = _redis_settings()
            settings.conn_retries, settings.conn_retry_delay, settings.conn_timeout = 1, 0, 2
            pool = await create_pool(settings)
            try:
                job = await pool.enqueue_job(
                    "run_agent", payload, _job_id=f"{run_id}-{os.urandom(3).hex()}"
                )
                return job.job_id if job else ""
            finally:
                await pool.aclose()

        from redis.exceptions import RedisError

        try:
            return asyncio.run(go())
        except (OSError, ConnectionError, RedisError) as exc:
            raise QueueUnavailable(f"redis unreachable: {type(exc).__name__}") from None

    def claim(self, worker_id: str, lease_s: float = 300.0) -> None:
        raise NotImplementedError("arq workers pull jobs themselves")

    def complete(self, job_id: str) -> None:
        raise NotImplementedError("arq records completion itself")

    def fail(self, job_id: str, error: str, retry: bool = True) -> None:
        raise NotImplementedError("arq records failures itself")


RETRY_DELAY_S = int(os.environ.get("ARQ_RETRY_DELAY_S", "5"))


async def run_agent(ctx: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
    """Run (or resume) one agent run. Unexpected errors are retried with a delay, up to max_tries.

    The runner checkpoints every step, so a retry or a re-delivery after a killed worker continues
    from the last completed step instead of starting over.
    """
    from arq import Retry

    from apps.api.routes.runs import execute_job

    try:
        return await asyncio.to_thread(execute_job, payload)
    except Exception as exc:
        if ctx.get("job_try", 1) < WorkerSettings.max_tries:
            raise Retry(defer=RETRY_DELAY_S) from exc
        raise


class WorkerSettings:
    functions = [run_agent]
    # Explicit timeout/retry policy (all overridable through the environment).
    max_tries = int(os.environ.get("ARQ_MAX_TRIES", "3"))
    job_timeout = int(os.environ.get("ARQ_JOB_TIMEOUT", "3600"))  # also sets the re-delivery delay
    retry_jobs = True  # jobs interrupted by a worker shutdown are retried
    max_jobs = int(os.environ.get("ARQ_MAX_JOBS", "2"))
    keep_result = 3600
    health_check_interval = 15

    try:
        redis_settings = _redis_settings()
    except ImportError:  # arq missing: importing the module for tests must still work
        redis_settings = None
