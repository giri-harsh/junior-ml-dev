# ADR-009: Insights, grounded captions and the claim verifier (PRD S5 + S7)

Status: accepted (S7 of this run)

## Decision
`datastory/insights.py` mines typed insights (target balance, skew, outlier, missingness, id column, correlation, target association, best segment with Wilson CI and minimum support). Each carries `facts`, the only numbers a caption may use. `datastory/verify.py` accepts a caption number only if it equals a fact (or a fact x100, a pairwise ratio / percent-of, or a sum/difference within one unit group) rounded to the writer's own decimals. A caption provider (LLM or mock) receives facts only, gets one regeneration on a failed check, then the deterministic template is used. Provider errors also fall back to the template, so a story always completes.

## Measured (`benchmarks/results/caption_verify_v0.json`, 16 real_dev datasets, template captions)
399 insights, 807 numeric claims, 0 unverified. Perturbing the first number of each caption: 397/399 rejected; 2 accepted because the new number coincided with a derived value (reported, not hidden).

## Limits
- The verifier checks numbers, not wording: "rose" for a fall would pass. Captions stay template-shaped to limit this.
- Derived-value matching is permissive by design (ratios, percent-of); a wrong number can match by coincidence (2/399 here).
- No real LLM was used. The provider seam is exercised with a mock, a flaky provider and a hallucinating provider.
- Charts, SVG/Vega-Lite, and the HTML story export (PRD S6, S7.5) are NOT built; see SKIPPED.md.
