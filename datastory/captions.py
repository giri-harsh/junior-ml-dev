"""Grounded captions: provider text -> verify -> one regeneration -> templated fallback.

The provider only ever receives the insight's `facts` (never raw rows). With no provider, or when
verification keeps failing, the deterministic template is used, so a story always completes.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

from pydantic import BaseModel, ConfigDict

from datastory.insights import Insight
from datastory.verify import verify_claims

Provider = Callable[[Insight, int], str]  # (insight, attempt) -> caption text


class Caption(BaseModel):
    model_config = ConfigDict(extra="forbid")

    insight_id: str
    text: str
    source: str  # llm | regenerated | template
    attempts: int


@dataclass
class CaptionStats:
    llm_ok: int = 0
    regenerated: int = 0
    fell_back: int = 0
    rejected_texts: list[str] = field(default_factory=list)

    @property
    def reject_rate(self) -> float:
        total = self.llm_ok + self.regenerated + self.fell_back
        return 0.0 if total == 0 else (self.regenerated + self.fell_back) / total


def template_caption(ins: Insight) -> str:
    f, cols = ins.facts, ins.columns
    if ins.type == "target_balance":
        return (
            f"The majority class makes up {f['majority_pct']:.1f}% of rows and the minority "
            f"{f['minority_pct']:.1f}%, an imbalance ratio of {f['imbalance_ratio']:.1f}."
        )
    if ins.type == "skew":
        return (
            f"`{cols[0]}` is skewed (skew {f['skew']:.2f}); "
            f"mean {f['mean']:.2f}, median {f['median']:.2f}."
        )
    if ins.type == "outlier":
        return f"{f['outlier_pct']:.1f}% of `{cols[0]}` values fall outside the IQR fences."
    if ins.type == "missing_pattern":
        return f"`{cols[0]}` is missing in {f['missing_pct']:.1f}% of rows."
    if ins.type == "id_column":
        return f"`{cols[0]}` is {f['unique_pct']:.1f}% unique and looks like an identifier."
    if ins.type == "correlation":
        rho = f["spearman_rho"]
        return f"`{cols[0]}` and `{cols[1]}` move together (Spearman rho {rho:.2f})."
    if ins.type == "target_association":
        return f"`{cols[0]}` is associated with the target (Spearman rho {f['spearman_rho']:.2f})."
    if ins.type == "segment":
        return (
            f"In segment `{cols[0]}` the rate is {f['rate_pct']:.1f}% "
            f"against {f['overall_pct']:.1f}% "
            f"overall (95% CI {f['ci_low_pct']:.1f}% to {f['ci_high_pct']:.1f}%)."
        )
    return f"Insight {ins.id}."


def mock_provider(ins: Insight, attempt: int) -> str:
    """Offline stand-in for an LLM: paraphrases the template, always grounded."""
    return "Finding: " + template_caption(ins)


def build_caption(
    ins: Insight, provider: Provider | None = None, stats: CaptionStats | None = None
) -> Caption:
    stats = stats if stats is not None else CaptionStats()
    if provider is None:
        return Caption(insight_id=ins.id, text=template_caption(ins), source="template", attempts=0)
    for attempt in (0, 1):
        try:
            text = provider(ins, attempt)
        except Exception:  # provider down: deterministic fallback, never an error
            break
        if verify_claims(text, ins.facts).ok:
            if attempt == 0:
                stats.llm_ok += 1
                return Caption(insight_id=ins.id, text=text, source="llm", attempts=1)
            stats.regenerated += 1
            return Caption(insight_id=ins.id, text=text, source="regenerated", attempts=2)
        stats.rejected_texts.append(text)
    stats.fell_back += 1
    return Caption(insight_id=ins.id, text=template_caption(ins), source="template", attempts=2)
