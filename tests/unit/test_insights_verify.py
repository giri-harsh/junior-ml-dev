from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
from hypothesis import assume, given, settings
from hypothesis import strategies as st

from datastory.captions import CaptionStats, build_caption, mock_provider, template_caption
from datastory.insights import Insight, mine_insights
from datastory.verify import candidate_values, extract_claims, matches, verify_claims

FACTS = {"majority_pct": 91.3, "minority_pct": 8.7, "count": 1500.0}


def test_rounding_semantics() -> None:
    assert verify_claims("about 91% of rows", FACTS).ok  # 91.3 rounds to 91
    assert verify_claims("91.3% of rows", FACTS).ok
    assert not verify_claims("92% of rows", FACTS).ok
    assert not verify_claims("91.4% of rows", FACTS).ok
    assert verify_claims("1,500 rows", FACTS).ok
    assert verify_claims("1.5k rows", FACTS).ok
    assert not verify_claims("1.9k rows", FACTS).ok


def test_derived_values_are_accepted_but_unrelated_numbers_are_not() -> None:
    assert verify_claims("a ratio of 10.5", FACTS).ok  # 91.3 / 8.7
    assert verify_claims("the gap is 82.6 points", FACTS).ok  # 91.3 - 8.7
    assert not verify_claims("a ratio of 12.5", FACTS).ok


def test_code_spans_and_identifiers_are_not_claims() -> None:
    claims = extract_claims("Column `col_017` and f2 hold 91.3%")
    assert [c.text for c in claims] == ["91.3%"]


def test_text_without_numbers_passes() -> None:
    r = verify_claims("Nothing numeric here.", FACTS)
    assert r.ok and r.checked == 0


@given(
    a=st.floats(10, 9000).map(lambda x: round(x, 2)),
    b=st.floats(10, 9000).map(lambda x: round(x, 2)),
    bump=st.floats(1.5, 40),
)
@settings(max_examples=200, deadline=None)
def test_property_perturbing_a_number_is_rejected(a: float, b: float, bump: float) -> None:
    facts = {"alpha": a, "beta": b}
    assert verify_claims(f"alpha is {a:.2f} and beta is {b:.2f}", facts).ok
    wrong = round(a + bump, 2)
    cands = candidate_values(facts)
    claim = extract_claims(f"alpha is {wrong:.2f}")[0]
    assume(not matches(claim, cands))  # skip coincidental matches to another fact or derivation
    assert not verify_claims(f"alpha is {wrong:.2f} and beta is {b:.2f}", facts).ok


def _frame(n: int = 1500, seed: int = 0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    x = rng.normal(size=n)
    df = pd.DataFrame(
        {
            "x": x,
            "x_copy": x * 2 + rng.normal(scale=0.1, size=n),
            "skewed": rng.lognormal(0, 1.2, n),
            "plan": rng.choice(["free", "pro", "team"], n, p=[0.6, 0.3, 0.1]),
            "id": np.arange(n),
        }
    )
    p = np.where(df["plan"] == "team", 0.5, 0.1)
    df["churn"] = (rng.random(n) < p).astype(int)
    df.loc[rng.random(n) < 0.2, "x"] = np.nan
    return df


def test_insights_find_planted_properties_and_facts_recompute() -> None:
    df = _frame()
    ins = {i.id: i for i in mine_insights(df, "churn")}
    assert "skew:skewed" in ins and "missing_pattern:x" in ins and "id_column:id" in ins
    assert any(k.startswith("correlation:") for k in ins) and "segment:plan" in ins
    bal = ins["target_balance:churn"].facts
    assert bal["majority_pct"] == pytest.approx(100 * (1 - df["churn"].mean()), abs=1e-3)
    assert ins["missing_pattern:x"].facts["missing_pct"] == pytest.approx(
        100 * df["x"].isna().mean(), abs=1e-3
    )
    seg = ins["segment:plan"].facts
    assert seg["n"] >= 30 and seg["ci_low_pct"] < seg["rate_pct"] < seg["ci_high_pct"]
    assert ins["segment:plan"].sample["n_full"] == len(df)


def test_insights_are_sorted_and_bounded() -> None:
    out = mine_insights(_frame(), "churn")
    assert [i.importance for i in out] == sorted((i.importance for i in out), reverse=True)
    assert all(0 <= i.importance <= 1 for i in out)


def test_every_template_caption_verifies() -> None:
    for i in mine_insights(_frame(), "churn"):
        assert verify_claims(template_caption(i), i.facts).ok, i.id


def _one() -> Insight:
    return next(i for i in mine_insights(_frame(), "churn") if i.type == "target_balance")


def test_mock_provider_caption_is_accepted() -> None:
    stats = CaptionStats()
    c = build_caption(_one(), mock_provider, stats)
    assert c.source == "llm" and stats.reject_rate == 0


def test_hallucinated_number_is_rejected_then_regenerated() -> None:
    ins = _one()

    def flaky(i: Insight, attempt: int) -> str:
        return "The majority class is 99.9% of rows." if attempt == 0 else template_caption(i)

    stats = CaptionStats()
    c = build_caption(ins, flaky, stats)
    assert c.source == "regenerated" and "99.9" in stats.rejected_texts[0]


def test_persistent_hallucination_falls_back_to_template() -> None:
    ins = _one()
    stats = CaptionStats()
    c = build_caption(ins, lambda i, a: "It is 12345.6 percent.", stats)
    assert c.source == "template" and c.text == template_caption(ins) and stats.reject_rate == 1.0


def test_provider_down_still_completes() -> None:
    def down(i: Insight, attempt: int) -> str:
        raise ConnectionError("provider unavailable")

    c = build_caption(_one(), down)
    assert c.source == "template"


def test_no_provider_uses_template() -> None:
    assert build_caption(_one()).source == "template"


def test_negative_numbers_keep_their_sign() -> None:
    facts = {"spearman_rho": -0.7356}
    assert verify_claims("rho -0.74", facts).ok
    assert verify_claims("a correlation of 0.74 in magnitude", facts).ok
    assert not verify_claims("rho -0.75", facts).ok
    assert not verify_claims("rho 0.9", facts).ok
    assert extract_claims("ranges 5-10")[1].value == 10.0  # hyphen in a range is not a sign
