"""Measure caption grounding on the real_dev datasets (PRD S7: 0 unverified numeric claims).

For every insight: template caption -> verifier (must pass). Then every numeric claim in every
caption is perturbed once; the verifier should reject the perturbed text unless the new number
coincides with another fact/derivation (counted separately, not hidden).

Usage: python -m benchmarks.caption_verify
"""

from __future__ import annotations

import re
import sys

from benchmarks.real_dev import load_all
from benchmarks.results_writer import Conditions, write_result
from datastory.captions import template_caption
from datastory.insights import mine_insights
from datastory.verify import candidate_values, extract_claims, matches, verify_claims

NUMBER = re.compile(r"(?<![\w.`])\d+(?:\.\d+)?(?![\w`])")


def perturb_first_number(text: str) -> str | None:
    m = NUMBER.search(text)
    if not m:
        return None
    raw = m.group(0)
    dec = len(raw.split(".")[1]) if "." in raw else 0
    new = f"{(float(raw) + 7.31) * 1.37:.{dec}f}"
    return text[: m.start()] + new + text[m.end() :]


def main() -> int:
    per_dataset = {}
    insights_n = claims_n = unverified = 0
    perturbed = rejected = coincidental = 0
    for name, (df, target) in load_all().items():
        ins = mine_insights(df, target)
        d_claims = d_unverified = 0
        for i in ins:
            text = template_caption(i)
            r = verify_claims(text, i.facts)
            d_claims += r.checked
            d_unverified += len(r.unmatched)
            bad = perturb_first_number(text)
            if bad is not None:
                perturbed += 1
                if not verify_claims(bad, i.facts).ok:
                    rejected += 1
                else:
                    cands = candidate_values(i.facts)
                    if all(matches(c, cands) for c in extract_claims(bad)):
                        coincidental += 1
        per_dataset[name] = {"insights": len(ins), "claims": d_claims, "unverified": d_unverified}
        insights_n += len(ins)
        claims_n += d_claims
        unverified += d_unverified
    res = {
        "datasets": len(per_dataset),
        "insights": insights_n,
        "numeric_claims_checked": claims_n,
        "unverified_claims": unverified,
        "perturbed_captions": perturbed,
        "perturbed_rejected": rejected,
        "perturbed_accepted_as_coincidence": coincidental,
        "per_dataset": per_dataset,
    }
    write_result(
        "caption_verify_v0",
        res,
        Conditions(llm="none", sandbox="none", n=len(per_dataset), notes="template captions only"),
        command="python -m benchmarks.caption_verify",
    )
    print({k: v for k, v in res.items() if k != "per_dataset"})
    return 0 if unverified == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
