"""Render docs/RESULTS.md from benchmarks/results/*.json. Numbers are copied, never computed here.

uv run python scripts/render_results.py
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
RES = ROOT / "benchmarks" / "results"


def load(name: str) -> dict[str, Any] | None:
    p = RES / f"{name}.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None


def ci(v: list[float] | None) -> str:
    return "n/a" if not v else f"{v[0]:.3f} [{v[1]:.3f}, {v[2]:.3f}]"


def section_agent(lines: list[str], name: str = "agent_v1", heading: str = "") -> None:
    d = load(name)
    lines += [
        heading or "## Agent benchmark v1 (headline; 10 tasks, scorer-service test scores)",
        "",
    ]
    if d is None:
        lines += [f"**NOT RUN** (`benchmarks/results/{name}.json` does not exist).", ""]
        return
    r, c = d["results"], d["conditions"]
    lines += [
        f"**Planner: {r['planner'].upper()} (no LLM). LLM: {c['llm']}. This is NOT an LLM-agent "
        f"result.** Freeze hash `{r['freeze_hash'][:12]}`, git `{d['git_sha'][:10]}`.", "",
        "| Task | metric | dummy | linear | FLAML | agent | agent norm. | family |",
        "|---|---|---|---|---|---|---|---|",
    ]  # fmt: skip
    metrics: dict[str, str] = {}
    for bname in ("baselines_v0", "baselines_v3"):
        b = load(bname)
        if b:
            metrics.update({k: v["metric"] for k, v in b["results"]["per_task"].items()})
    for name, t in r["per_task"].items():
        n = t["agent_normalized"]
        lines.append(
            f"| {name} | {metrics.get(name, '')} | {t['dummy']:.4f} | {t['linear']:.4f} | "
            f"{t['flaml']:.4f} | {t['agent']:.4f} | {'n/a' if n is None else f'{n:.3f}'} | "
            f"{t['family']} |"
        )
    a = r["aggregate"]
    lines += [
        "",
        f"- Agent normalized mean [95% CI]: {ci(a.get('agent_normalized_mean_ci95'))}",
        f"- Linear normalized mean [95% CI]: {ci(a.get('linear_normalized_mean_ci95'))}",
        f"- Agent minus linear, paired bootstrap: {ci(a.get('agent_minus_linear_paired_ci95'))}",
        f"- Agent minus FLAML, paired bootstrap: {ci(a.get('agent_minus_flaml_paired_ci95'))}",
        f"- Pass vs linear (ADR-005 rule): {a['pass_vs_linear']['k']}/{a['pass_vs_linear']['n']} "
        f"(Wilson 95% [{a['pass_vs_linear']['wilson95'][0]:.2f}, "
        f"{a['pass_vs_linear']['wilson95'][1]:.2f}])",
        f"- Conditions: {c['notes']}", "",
    ]  # fmt: skip
    if "paired_vs_prior_ci95" in a:
        lines.insert(
            -2,
            f"- Paired v2 minus v1 (n={a['paired_vs_prior_n']} tasks): {ci(a['paired_vs_prior_ci95'])}",
        )


def section_llm_stats(lines: list[str]) -> None:
    d = load("agent_v3_llm")
    if d is None:
        return
    pt = d["results"]["per_task"]

    def total(key: str) -> int:
        return int(sum(t.get(key, 0) for t in pt.values()))

    walls = ", ".join(f"{k}={t['wall_s']:.0f}" for k, t in pt.items())
    lines += [
        "### LLM planner statistics (v3, sums over tasks from `agent_v3_llm.json`)", "",
        f"- Provider requests (cache misses): {total('llm_requests')}; cached: {total('llm_cached')}; "
        f"tokens: {total('llm_tokens')}; cost: $0 (free tiers).",
        f"- Structured proposals: {total('llm_structured')}; schema-valid on first try: "
        f"{total('llm_first_try_valid')}; repair round trips: {total('llm_repairs')}.",
        f"- Step-level fallbacks to the scripted planner (proposal repeated/unusable): "
        f"{total('llm_fallbacks')}.",
        f"- Wall seconds per task: {walls}.", "",
    ]  # fmt: skip


def section_leakage_v2(lines: list[str]) -> None:
    d = load("leakage_v2")
    lines += ["## Leakage detector v2 (unseen data; supersedes leakage_v1 for current code)", ""]
    if d is None:
        lines += ["NOT RUN.", ""]
        return
    r = d["results"]
    s = r["eval3"]["summary"]
    rv = r["real_v3"]["tasks"]
    mh = {k: v["n_medium_or_high"] for k, v in rv.items() if v["n_medium_or_high"]}
    lines += [
        f"- eval3 planted ({s['n_variants']} variants): recall {s['overall_recall']:.3f} "
        f"(bootstrap 95% {s['overall_recall_bootstrap95']}); clean-twin false alarms "
        f"{s['twin_fpr']:.3f} (Wilson 95% {s['twin_fpr_wilson95']}).",
        f"- real v3 ({len(rv)} unseen datasets): medium/high findings on {mh}. Adjudication "
        "(`benchmarks/adjudication_real_v3.json`): pc1 duplicate rows = true positive (verified "
        "by direct count); cmc label_noise = false positive (weak-signal target).",
        f"- `{r['supersedes']}` remains the record for the older detector code on eval2 and the "
        "10 original tasks; it was not rerun (eval-once).", "",
    ]  # fmt: skip


def section_dev(lines: list[str]) -> None:
    lines += ["## Agent dev partition (design allowed to use these)", ""]
    for name, label in (("agent_dev_v0", "v1 agent"), ("agent_dev_v1", "v2 agent")):
        d = load(name)
        if d is None:
            lines += [f"- {label}: NOT RUN.", ""]
            continue
        a = d["results"]["aggregate"]
        lines += [
            f"- {label}: 5 real_dev datasets, scripted planner, no LLM. Agent normalized "
            f"{ci(a.get('agent_normalized_mean_ci95'))}; agent minus linear "
            f"{ci(a.get('agent_minus_linear_paired_ci95'))}.",
        ]  # fmt: skip
    lines.append("")


def section_leakage_injection(lines: list[str]) -> None:
    lk, inj, ev = load("leakage_v1"), load("injection_v0"), load("injection_v1")
    lines += ["## Leakage detective and injection defence", ""]
    if lk:
        lines.append(
            f"- Leakage: see `leakage_v1.json` (hash {lk['results'].get('thresholds_sha256', '')[:12]})."
        )
    if inj:
        i = inj["results"]
        lines.append(
            f"- Injection suite: {i['n_cases']} cases; template payloads flagged "
            f"{i['flagged_non_evasion']}/{i['n_cases'] - i['n_evasion']}; evasion flagged "
            f"{i['flagged_evasion']}/{i['n_evasion']}; unsafe actions executed "
            f"{i['unsafe_actions_executed']} (simulated compliant agent vs structural guard; no LLM)."
        )
    il = load("injection_llm_v1")
    if il:
        e2 = il["results"]
        w = e2["suite"]["behaviour_change_wilson95"]
        lines.append(
            f"- **Injection, REAL LLM in the loop** (`injection_llm_v1.json`; wider action space than "
            f"production; structural guard decides): suite n={e2['suite']['n']}, attacker action "
            f"proposed {e2['suite']['behaviour_change']} (Wilson 95% [{w[0]:.2f}, {w[1]:.2f}]); "
            f"held-out n={e2['heldout']['n']}, proposed {e2['heldout']['behaviour_change']}; "
            f"**unsafe actions executed: {e2['all']['unsafe_executed']}/{e2['all']['n']}**. "
            f"Other risky-but-not-attacker proposals ({e2['all']['proposed_risky_non_aligned']}) "
            "are mostly ordinary reads/code on the dataset, which the guard may permit."
        )
    if ev:
        e = ev["results"]
        lines.append(
            f"- Scanner v1 evasion: dev {e['dev']['flagged_before']}/{e['dev']['n']} -> "
            f"{e['dev']['flagged_after']}/{e['dev']['n']}; held-out {e['heldout']['flagged_before']}/"
            f"{e['heldout']['n']} -> {e['heldout']['flagged_after']}/{e['heldout']['n']}; "
            f"false positives on {e['benign']['n']} benign strings: {e['benign']['false_positives_after']}."
        )
    lines.append("")


def main() -> int:
    lines = [
        "# Results",
        "",
        "Generated by `scripts/render_results.py` from `benchmarks/results/*.json`.",
        "",
    ]
    section_agent(lines)
    section_agent(
        lines,
        "agent_v2",
        "## Agent benchmark v2 (post-hoc, fixes informed by v1 failures; second and last held-out evaluation)",
    )
    section_agent(
        lines,
        "agent_v3_scripted",
        "## Agent benchmark v3, SCRIPTED planner (unseen partition; small test sets, wide CIs)",
    )
    section_agent(
        lines,
        "agent_v3_llm",
        "## Agent benchmark v3, REAL-LLM planner (Groq gpt-oss primary, Gemini fallback)",
    )
    section_llm_stats(lines)
    section_leakage_v2(lines)
    section_dev(lines)
    section_leakage_injection(lines)
    base = load("baselines_v0")
    if base:
        ag = base["results"]["aggregate"]
        lines += [
            "## Baselines (no LLM)", "",
            f"Normalized linear mean {ag['normalized_linear_mean']:.3f} "
            f"[{ag['normalized_linear_ci95'][0]:.3f}, {ag['normalized_linear_ci95'][1]:.3f}], "
            f"n={ag['normalized_linear_defined_n']}.", "",
        ]  # fmt: skip
    (ROOT / "docs" / "RESULTS.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("wrote docs/RESULTS.md")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
