"""Chart models (PRD S6)."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class ChartSpec(BaseModel):
    """Vega-Lite chart specification with metadata.

    Per PRD S6.5: deterministic alt text, spec ≤500 KB, mapped to insights.
    """

    chart_id: str = Field(description="Unique identifier for this chart")
    spec: dict[str, Any] = Field(description="Vega-Lite JSON specification")
    alt_text: str = Field(description="Deterministic alt text describing the chart")
    insight_id: str | None = Field(default=None, description="Related insight ID if any")
    template: str = Field(description="Template type used to generate this chart")
    columns: list[str] = Field(
        default_factory=list, description="Column names used (for novelty penalty)"
    )
    importance_score: float = Field(default=0.0, description="Importance × clarity × novelty")
    rank: int | None = Field(default=None, description="Final rank (1-indexed); top 12 in gallery")

    def size_kb(self) -> float:
        """Size of the spec in KB (PRD acceptance: ≤500 KB)."""
        import json

        return len(json.dumps(self.spec, separators=(",", ":"))) / 1024.0
