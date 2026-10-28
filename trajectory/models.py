"""Typed trajectory events: the only logging path for agent and pipeline activity (P3 data)."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class EventKind(StrEnum):
    STATE = "state"
    PROMPT = "prompt"
    LLM_OUTPUT = "llm_output"
    TOOL_CALL = "tool_call"
    OBSERVATION = "observation"
    DECISION = "decision"
    BUDGET = "budget"
    PIPELINE_STEP = "pipeline_step"


def _utcnow() -> datetime:
    return datetime.now(UTC)


class TrajectoryEvent(BaseModel):
    """One immutable fact about a run. `seq` is assigned by the writer, monotonic per run."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    run_id: str = Field(min_length=1)
    seq: int = Field(ge=0)
    ts: datetime = Field(default_factory=_utcnow)
    kind: EventKind
    agent_version: str = Field(min_length=1)
    prompt_hash: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)
    outcome_labels: dict[str, Any] | None = None

    def to_jsonl(self) -> str:
        return self.model_dump_json()

    @classmethod
    def from_jsonl(cls, line: str) -> TrajectoryEvent:
        return cls.model_validate_json(line)
