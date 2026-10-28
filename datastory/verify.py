"""Claim verifier: every number in a caption must trace to `facts`, directly or derived.

Deterministic. A number is accepted when it equals some candidate value rounded to the number of
decimals the writer used ("about 4%" vs 4.2 passes; 5% fails). Candidates: each fact, each fact
x100 (a fraction written as a percent), and pairwise ratio, percent-of, difference and sum.
"""

from __future__ import annotations

import itertools
import math
import re
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

NUM = re.compile(
    r"(?<![\w.])(?P<sign>-?)(?P<num>\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?)\s*(?P<unit>%|×|x(?![a-z])|k|K|M)?(?![\w])"
)
CODE_SPAN = re.compile(r"`[^`]*`")
SCALE = {"k": 1e3, "K": 1e3, "M": 1e6}


@dataclass(frozen=True)
class Claim:
    text: str
    value: float
    decimals: int
    unit: str


@dataclass(frozen=True)
class VerifyResult:
    ok: bool
    unmatched: list[str]
    checked: int


def extract_claims(text: str) -> list[Claim]:
    """Numbers in prose. Code spans (column names) and identifiers like col2 are ignored."""
    text = CODE_SPAN.sub(" ", text)
    claims = []
    for m in NUM.finditer(text):
        raw = m.group("num").replace(",", "")
        unit = m.group("unit") or ""
        dec = len(raw.split(".")[1]) if "." in raw else 0
        value = float(raw) * SCALE.get(unit, 1.0) * (-1.0 if m.group("sign") else 1.0)
        claims.append(Claim(m.group(0).strip(), value, dec, unit))
    return claims


def _unit_group(key: str) -> str:
    return key.rsplit("_", 1)[-1] if "_" in key else key


def candidate_values(facts: dict[str, float]) -> set[float]:
    """Facts, facts x100, pairwise ratios/percent-of, and sums/differences within one unit group."""
    items = [
        (k, float(v)) for k, v in facts.items() if isinstance(v, (int, float)) and math.isfinite(v)
    ]
    out: set[float] = set()
    for _, v in items:
        out.update({v, abs(v), v * 100, abs(v) * 100})
    for (_, a), (_, b) in itertools.permutations(items, 2):
        if b != 0:
            out.update({a / b, 100 * a / b})
    for (ka, a), (kb, b) in itertools.combinations(items, 2):
        if _unit_group(ka) == _unit_group(kb):
            out.update({a - b, b - a, a + b})
    return out


def _round_half_up(x: float, decimals: int) -> float:
    q = Decimal(1).scaleb(-decimals)
    return float(Decimal(repr(x)).quantize(q, rounding=ROUND_HALF_UP))


def _roundings(x: float, decimals: int) -> set[float]:
    """Half-up rounding plus Python's float formatting (they differ at exact binary ties)."""
    return {_round_half_up(x, decimals), float(f"{x:.{decimals}f}")}


def matches(claim: Claim, candidates: set[float]) -> bool:
    scale = SCALE.get(claim.unit, 1.0)
    want = _round_half_up(claim.value / scale, claim.decimals)
    return any(want in _roundings(c / scale, claim.decimals) for c in candidates)


def verify_claims(text: str, facts: dict[str, float]) -> VerifyResult:
    claims = extract_claims(text)
    cands = candidate_values(facts)
    bad = [c.text for c in claims if not matches(c, cands)]
    return VerifyResult(ok=not bad, unmatched=bad, checked=len(claims))
