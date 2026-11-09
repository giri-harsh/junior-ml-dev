# ruff: noqa: E501  (HTML templates)
"""Static demo site: pre-computed sample runs, honest benchmark numbers, an architecture page.

Used when no free live host exists (a free Hugging Face account cannot create Docker or Gradio
Spaces). Everything here is generated from files in the repo:

* `precompute_runs` runs the three bundled samples through the real scripted-planner demo runner
  (the same code, budgets and child-process executor as the live demo) and caches the results;
* `build_site` renders `index.html`, `results.html`, `architecture.html`, one page plus the
  agent's own HTML report per sample, a stylesheet and `.nojekyll` from that cache and from
  `docs/METRICS.md`. No number in a template is typed in: headline figures come from the file.

The output directory is the only thing ever published (see scripts/deploy_static.py).
"""

from __future__ import annotations

import hashlib
import html
import json
import re
import time
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from apps.api.demo import landing
from apps.api.demo.config import MAX_FLAML_S, MAX_WALL_S, DemoSettings
from apps.api.demo.config import REPO_URL as REPO_URL_CONFIG
from apps.api.demo.samples import BY_KEY, SAMPLES, public_info

REPO_URL = REPO_URL_CONFIG
BLOB = f"{REPO_URL}/blob/main/"
SITE_BASE = "/junior-ml-dev-demo/"  # GitHub Pages project path (404.html needs absolute URLs)
SRC_LINK = re.compile(r'<a href="' + re.escape(BLOB) + r'[^"]*"[^>]*>(.*?)</a>', re.S)
E = html.escape


@dataclass
class RunRecord:
    key: str
    title: str
    blurb: str
    openml_id: int
    task_type: str
    metric: str
    rows: int
    cols: int
    run_id: str
    status: str
    wall_s: float  # measured by the parent: submit to finish, including process start
    summary: dict[str, Any]
    steps: list[dict[str, Any]]
    budget: dict[str, Any]
    ran_at: str
    machine: str = "a developer laptop (Windows 11), CPU only"
    extra: dict[str, Any] = field(default_factory=dict)


# --- pre-computation -----------------------------------------------------------------------------
def precompute_runs(
    data_dir: Path, cache_dir: Path, keys: list[str] | None = None
) -> list[RunRecord]:
    """Run each sample once with the scripted planner (real child processes, ~40 s each)."""
    from apps.api.demo.service import DemoService, subprocess_executor

    cache_dir.mkdir(parents=True, exist_ok=True)
    state = cache_dir / "_state"
    settings = DemoSettings(
        data_dir=data_dir, state_dir=state, site_dir=cache_dir / "_site", max_wall_s=90.0,
        soft_wall_s=55.0, flaml_s=15.0, queue_max=3, history_cap=50, history_ttl_s=1e9,
        ip_runs_per_window=50, ip_window_s=60.0, global_runs_per_hour=500, read_per_min=1000,
        proxy_hops=0,
    )  # fmt: skip
    service = DemoService(settings, subprocess_executor)
    info = {i["key"]: i for i in public_info(data_dir)}
    out: list[RunRecord] = []
    for s in SAMPLES:
        if s.key not in info or (keys and s.key not in keys):
            continue
        t0 = time.monotonic()
        run_id = service.submit(s.key, "precompute")
        service.work_once()
        wall = time.monotonic() - t0
        st = service.public_status(run_id) or {}
        report = service.report_path(run_id)
        if st.get("status") != "done" or report is None:
            raise RuntimeError(f"{s.key}: run did not finish ({st.get('status')})")
        run_dir = state / "runs" / run_id
        trace = json.loads((run_dir / "out" / run_id / "trace.json").read_text(encoding="utf-8"))
        cfg = json.loads((run_dir / "job.json").read_text(encoding="utf-8"))["config"]["budget"]
        dest = cache_dir / s.key
        dest.mkdir(parents=True, exist_ok=True)
        (dest / "report.html").write_text(report.read_text(encoding="utf-8"), encoding="utf-8")
        out.append(
            RunRecord(
                key=s.key, title=s.title, blurb=s.blurb, openml_id=s.openml_id,
                task_type=s.task_type, metric=s.metric, rows=int(info[s.key]["rows"]),
                cols=int(info[s.key]["cols"]), run_id=run_id, status=str(st["status"]),
                wall_s=round(wall, 1), summary=dict(st["summary"]), steps=list(trace["steps"]),
                budget=cfg, ran_at=datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC"),
            )
        )  # fmt: skip
    (cache_dir / "runs.json").write_text(
        json.dumps([asdict(r) for r in out], indent=1), encoding="utf-8"
    )
    return out


def load_runs(cache_dir: Path) -> list[RunRecord]:
    raw = json.loads((cache_dir / "runs.json").read_text(encoding="utf-8"))
    return [RunRecord(**r) for r in raw]


# --- layout --------------------------------------------------------------------------------------
CSS = """\
:root{--bg:#fff;--surface:#f6f8fa;--fg:#1b1f24;--muted:#59636e;--line:#d0d7de;--accent:#0b5fff;--warn:#9a6700;--warnbg:#fff8c5}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){--bg:#0e1116;--surface:#161b22;--fg:#e6edf3;--muted:#9198a1;--line:#30363d;--accent:#6ea8ff;--warn:#e3b341;--warnbg:#2d2400}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--fg);font:16px/1.55 system-ui,-apple-system,"Segoe UI",sans-serif}
.wrap{max-width:900px;margin:0 auto;padding:0 16px}
header.top{border-bottom:1px solid var(--line);background:var(--surface)}
header.top .wrap{display:flex;flex-wrap:wrap;gap:6px 22px;align-items:center;min-height:52px}
.brand{font-weight:650;margin-right:auto}
nav a{color:var(--fg);text-decoration:none;font-size:.95rem;padding:4px 0;border-bottom:2px solid transparent}
nav a:hover,nav a[aria-current]{border-bottom-color:var(--accent)}
h1{font-size:clamp(1.5rem,4.2vw,2.1rem);line-height:1.2;margin:34px 0 12px;text-wrap:balance}
h2{font-size:1.2rem;margin:38px 0 10px}h3{font-size:1rem;margin:22px 0 6px}
.lede{color:var(--muted);font-size:1.05rem;max-width:64ch}
.fine{color:var(--muted);font-size:.88rem}
a{color:var(--accent)}
code{font:.88em ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;background:var(--surface);padding:1px 5px;border-radius:4px}
.notice{border:1px solid var(--warn);background:var(--warnbg);border-radius:10px;padding:10px 14px;margin:18px 0;font-size:.95rem}
.tiles,.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));gap:12px;margin:18px 0}
.tile,.card{border:1px solid var(--line);background:var(--surface);border-radius:10px;padding:14px 16px}
.tile-k{color:var(--muted);font-size:.85rem}.tile-v{font-size:1.15rem;font-weight:650;margin:4px 0;font-variant-numeric:tabular-nums}.tile-s{color:var(--muted);font-size:.85rem}
.card b{display:block;margin-bottom:4px}.card .fine{margin:4px 0}
.tbl{overflow-x:auto;margin:10px 0;border:1px solid var(--line);border-radius:10px}
table{border-collapse:collapse;width:100%;font-size:.88rem;min-width:520px}
th,td{text-align:left;padding:7px 10px;border-bottom:1px solid var(--line);vertical-align:top}
th{background:var(--surface);font-weight:600}tr:last-child td{border-bottom:0}
dl.kv{display:grid;grid-template-columns:max-content 1fr;gap:4px 18px;margin:12px 0}dl.kv dt{color:var(--muted)}dl.kv dd{margin:0}
iframe.report{width:100%;height:680px;border:1px solid var(--line);border-radius:10px;background:#fff}
.srcref{border-bottom:1px dotted var(--muted);cursor:help}
svg.diagram{width:100%;height:auto;margin:14px 0}
svg.diagram text{fill:var(--fg);font:13px system-ui,sans-serif}
svg.diagram .box{fill:var(--surface);stroke:var(--line);stroke-width:1.5}
svg.diagram .acc{fill:var(--surface);stroke:var(--accent);stroke-width:1.5}
svg.diagram .sub{fill:var(--muted);font-size:11px}
svg.diagram .arrow{stroke:var(--muted);stroke-width:1.5;fill:none}
footer{padding:36px 16px 56px}
"""

NAV = (
    ("index.html", "Home"),
    ("results.html", "Benchmark results"),
    ("architecture.html", "Architecture"),
)


def page(title: str, body: str, *, active: str, depth: int = 0) -> str:
    up = "../" * depth
    cur = ' aria-current="page"'
    links = "".join(
        f'<a href="{up}{href}"{cur if href == active else ""}>{label}</a>' for href, label in NAV
    )
    return (
        '<!doctype html>\n<html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        f"<title>{E(title)}</title>"
        '<meta name="description" content="junior-ml-dev: an agent that shows its work and catches '
        'its own mistakes. Static demo with pre-computed runs and verified benchmark numbers.">'
        f'<link rel="stylesheet" href="{up}style.css"></head><body>'
        '<header class="top"><div class="wrap"><span class="brand">junior-ml-dev</span>'
        f'<nav>{links}</nav></div></header><main class="wrap">{body}</main>'
        '<footer class="wrap fine">Static site generated from the project repository. '
        "No code runs on this page.</footer></body></html>\n"
    )


def source_note(repo_private: bool | None) -> str:
    if repo_private is True:
        return (
            "The source repository is currently <strong>private</strong>, so file references "
            "below (result JSONs, code) are names only, not links."
        )
    return f'Source code and the full evaluation write-up: <a href="{REPO_URL}">{E(REPO_URL)}</a>.'


def delink(page_html: str, repo_private: bool | None) -> str:
    """Links to files in a private repo would 404 for every visitor: keep the file name as text."""
    if repo_private is False:
        return page_html
    return SRC_LINK.sub(
        r'<span class="srcref" title="a file in the source repository">\1</span>', page_html
    )


# --- metrics text: what is published ---------------------------------------------------------------
RESUME_REF = re.compile(r";?\s*resume commands in `?docs/[A-Za-z0-9_./-]+\.md`?")
CI_LINE = re.compile(r" - run \d{8,} \((\d+ s)\) on `[0-9a-f]{7,40}` \([^)]*\)")
CI_RUN = re.compile(r"\(CI run \d{8,}\)")


def sanitize_metrics(md: str) -> str:
    """Drop what only makes sense inside the private repo: pointers to internal docs (resume
    commands), CI run ids and commit hashes/messages. Every figure and caveat stays."""
    md = RESUME_REF.sub("", md)
    md = CI_LINE.sub(r" (\1)", md)
    return CI_RUN.sub("(CI run)", md)


PAIRED = re.compile(
    r"(?:vs FLAML|Paired LLM minus scripted:)\s*(-?\d+\.\d+) \[(-?\d+\.\d+), (-?\d+\.\d+)\]"
)


def evidence_note(md: str) -> str:
    """One sentence computed from the paired-difference intervals in the metrics file: whether
    they include 0. Nothing is typed in: the counts and n come from the file."""
    ivals = PAIRED.findall(md)
    if not ivals:
        return ""
    including = sum(float(lo) <= 0.0 <= float(hi) for _, lo, hi in ivals)
    n = re.search(r"\(n=(\d+)\)", md)
    once = "each arm run once" in md
    scope = (f" ({n.group(1)} tasks" + (", each arm run once" if once else "") + ")") if n else ""
    if including == len(ivals):
        return (
            f"All {len(ivals)} paired-difference intervals against FLAML and between the LLM and "
            f"scripted planners include 0{scope}: no difference between these arms is demonstrated."
        )
    return (
        f"{including} of {len(ivals)} paired-difference intervals against FLAML and between the LLM "
        f"and scripted planners include 0{scope}; read each interval below."
    )


def limits_sentence(soft_s: object) -> str:
    """The two different time limits, so 55 s and 90 s are not read as a contradiction."""
    return (
        f"A demo run has two limits: a {soft_s} s soft wall after which the agent stops searching and "
        f"wraps up (review, report), and a {MAX_WALL_S:.0f} s hard limit at which the whole process is "
        f"killed (the AutoML ceiling is {MAX_FLAML_S:.0f} s). Wrap-up and process start come on top of "
        "the soft wall, so a finished run can take longer than it."
    )


# --- pages ---------------------------------------------------------------------------------------
def fmt_score(v: Any) -> str:
    return "n/a" if v is None else f"{float(v):.4f}"


def run_card(r: RunRecord) -> str:
    s = r.summary
    return (
        '<div class="card">'
        f'<b><a href="runs/{E(r.key)}/index.html">{E(r.title)}</a></b>'
        f'<div class="fine">{r.rows} rows, {E(r.task_type)}, metric {E(r.metric)}</div>'
        f'<div class="fine">chosen model <code>{E(str(s.get("chosen_family")))}</code>, '
        f"validation {E(r.metric)} {fmt_score(s.get('val_score'))}, "
        f"reviewer {E(str(s.get('review')))}</div>"
        f'<div class="fine">{r.wall_s:.0f} s wall, {int(s.get("n_steps") or 0)} steps</div>'
        "</div>"
    )


def index_page(
    metrics_md: str,
    runs: list[RunRecord],
    repo_private: bool | None,
    now: datetime,
    digest_of: str | None = None,
) -> str:
    _, sections = landing.split_sections(metrics_md)
    head_name, head_body = sections[0] if sections else ("", [])
    digest = hashlib.sha256((digest_of or metrics_md).encode("utf-8")).hexdigest()[:12]
    cards = "".join(run_card(r) for r in runs)
    body = f"""
<h1>A junior ML engineer that shows its work and catches its own mistakes.</h1>
<p class="lede">It profiles a tabular dataset, checks for leakage before modelling, trains and compares
models against baselines, has a deterministic reviewer sign off, and writes a report. Deployment is
gated by a single-use approval.</p>
<div class="notice"><strong>This is a static site, not a live demo.</strong> The example runs below
were computed once with the project's scripted planner (no LLM) on {E(runs[0].machine if runs else "a laptop")},
and are shown as recorded. A live, interactive version needs a host that runs Python; a free
Hugging Face account cannot create Docker or Gradio Spaces. {source_note(repo_private)}</div>
<h2>Headline: {landing.inline(head_name)}</h2>
<div class="tiles">{landing.tiles(head_body)}</div>
<p class="fine">Read from <code>docs/METRICS.md</code> when this site was built (file hash
<code>{digest}</code>, built {now.strftime("%Y-%m-%d %H:%M UTC")}). Full tables, intervals and caveats:
<a href="results.html">benchmark results</a>.</p>
<h2>Example runs</h2>
<p class="fine">Three small public OpenML tables, each run once with the same code and limits the repository's demo mode
uses (scripted planner, FLAML {int(runs[0].budget.get("flaml_budget_s", 0)) if runs else 0} s).
{limits_sentence(int(runs[0].budget.get("max_wall_s", 0)) if runs else 0)} Wall times are from one machine
and will differ elsewhere. These are demo-scale tasks, not the benchmark.</p>
<div class="cards">{cards}</div>
<h2>How it works</h2>
<p>The <a href="architecture.html">architecture page</a> shows the planner, the guarded runner, the tool
servers, the reviewer and the approval gate, and which properties are enforced where.</p>
"""
    return page("junior-ml-dev: demo", delink(body, repo_private), active="index.html")


def results_page(
    metrics_md: str, repo_private: bool | None, now: datetime, soft_wall_s: object = ""
) -> str:
    title, sections = landing.split_sections(metrics_md)
    note = evidence_note(metrics_md)
    evidence = f"<p><strong>{E(note)}</strong></p>" if note else ""
    limits = E(limits_sentence(soft_wall_s))
    intro = landing.blocks_to_html(title.splitlines()[1:]) if "\n" in title else ""
    parts = "\n".join(
        f"<section><h2>{landing.inline(name)}</h2>{landing.blocks_to_html(body)}</section>"
        for name, body in sections
    )
    body = f"""
<h1>{landing.inline(title.splitlines()[0] if title else "Verified metrics")}</h1>
{intro}
<div class="notice">Rendered from <code>docs/METRICS.md</code> ({now.strftime("%Y-%m-%d")}); references that
only make sense inside the private repository (pointers to internal docs, CI run ids, commit hashes)
are removed, every figure and caveat is kept. A demo run on the <a href="index.html">home page</a> uses a
small public dataset under the time limits described below; it does not reproduce these benchmark numbers,
which come from larger tasks and longer budgets. {source_note(repo_private)}</div>
{evidence}
<p class="fine">{limits}</p>
{parts}
"""
    return page(
        "Benchmark results: junior-ml-dev", delink(body, repo_private), active="results.html"
    )


def run_page(r: RunRecord) -> str:
    s = r.summary
    rows = "".join(
        f"<tr><td>{int(x['idx'])}</td><td><code>{E(str(x['tool']))}</code></td>"
        f"<td>{E(str(x['server']))}</td><td>{'yes' if x['ok'] else 'no'}</td>"
        f"<td>{float(x['latency_s']):.2f}</td></tr>"
        for x in r.steps
    )
    dropped = ", ".join(map(str, s.get("dropped") or [])) or "none"
    body = f"""
<p class="fine"><a href="../../index.html">Home</a> / example runs</p>
<h1>{E(r.title)}</h1>
<p class="lede">{E(r.blurb)}</p>
<div class="notice">Pre-computed on {E(r.ran_at)} on {E(r.machine)}. Scripted planner, no LLM, no network
calls during the run. Dataset: <a href="https://www.openml.org/d/{r.openml_id}" rel="noopener">OpenML {r.openml_id}</a>.</div>
<dl class="kv">
<dt>Task</dt><dd>{E(r.task_type)}, target <code>{E(str(BY_KEY[r.key].target))}</code>, metric <code>{E(r.metric)}</code>, {r.rows} rows x {r.cols} columns</dd>
<dt>Status</dt><dd>{E(str(s.get("status")))}</dd>
<dt>Chosen model</dt><dd><code>{E(str(s.get("chosen_family")))}</code></dd>
<dt>Validation {E(r.metric)}</dt><dd>{fmt_score(s.get("val_score"))}</dd>
<dt>Reviewer verdict</dt><dd>{E(str(s.get("review")))}</dd>
<dt>Columns dropped for leakage</dt><dd>{E(dropped)}</dd>
<dt>Steps</dt><dd>{int(s.get("n_steps") or 0)}</dd>
<dt>Wall time</dt><dd>{r.wall_s:.1f} s (process start to report); agent clock {float(s.get("latency_s") or 0):.1f} s. One run on a shared machine that was busy with other jobs: a timing sample, not a benchmark.</dd>
<dt>Budgets</dt><dd>soft wall {int(r.budget.get("max_wall_s", 0))} s (agent stops searching), hard limit {MAX_WALL_S:.0f} s (process killed), FLAML {int(r.budget.get("flaml_budget_s", 0))} s, {int(r.budget.get("tune_trials", 0))} tuning trials</dd>
</dl>
<h2>Agent steps</h2>
<div class="tbl"><table><thead><tr><th>#</th><th>tool</th><th>server</th><th>ok</th><th>latency (s)</th></tr></thead><tbody>{rows}</tbody></table></div>
<h2>The agent's own report</h2>
<p><a href="report.html">Open the report on its own page</a>.</p>
<iframe class="report" src="report.html" title="Agent report for {E(r.title)}" sandbox></iframe>
"""
    return page(f"{r.title}: example run", body, active="", depth=2)


def architecture_svg() -> str:
    def box(x: int, y: int, w: int, h: int, title: str, sub: str, acc: bool = False) -> str:
        cls = "acc" if acc else "box"
        return (
            f'<rect class="{cls}" x="{x}" y="{y}" width="{w}" height="{h}" rx="8"/>'
            f'<text x="{x + w // 2}" y="{y + 22}" text-anchor="middle" font-weight="600">{E(title)}</text>'
            f'<text class="sub" x="{x + w // 2}" y="{y + 40}" text-anchor="middle">{E(sub)}</text>'
        )

    def arrow(x1: int, y1: int, x2: int, y2: int) -> str:
        return f'<path class="arrow" d="M{x1} {y1} L{x2} {y2}" marker-end="url(#ah)"/>'

    return (
        '<svg class="diagram" viewBox="0 0 760 470" role="img" aria-labelledby="dt dd">'
        '<title id="dt">Architecture of junior-ml-dev</title>'
        '<desc id="dd">A planner proposes steps; a guarded runner executes them through four tool '
        "servers; a reviewer and a report close the run; deployment needs an approval.</desc>"
        '<defs><marker id="ah" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" '
        'orient="auto"><path d="M0 0 L10 5 L0 10 z" fill="#8b949e"/></marker></defs>'
        + box(20, 20, 200, 56, "Planner", "scripted, or LLM via gateway")
        + box(280, 20, 260, 56, "Job queue", "SQLite (arq is a stub)")
        + box(
            20,
            130,
            520,
            70,
            "Agent runner",
            "policy guard, budgets, checkpoints, hash-chained audit",
            True,
        )
        + box(560, 130, 180, 70, "Run store", "one checkpoint per step")
        + box(20, 270, 120, 70, "data-tools", "profile, leakage")
        + box(160, 270, 140, 70, "experiments", "train, tune, compare")
        + box(320, 270, 140, 70, "sandbox-exec", "code policy, Docker")
        + box(480, 270, 140, 70, "deploy", "package, local deploy")
        + box(640, 270, 100, 70, "Approvals", "single-use token")
        + box(20, 390, 240, 56, "Reviewer", "deterministic checks; advisory LLM critic")
        + box(290, 390, 240, 56, "Report", "HTML, markdown, model card")
        + arrow(120, 76, 120, 130)
        + arrow(410, 76, 410, 130)
        + arrow(540, 165, 560, 165)
        + arrow(80, 200, 80, 270)
        + arrow(230, 200, 230, 270)
        + arrow(390, 200, 390, 270)
        + arrow(550, 200, 550, 270)
        + arrow(640, 305, 620, 305)
        + arrow(150, 200, 140, 390)
        + arrow(260, 418, 290, 418)
        + "</svg>"
    )


def architecture_page(repo_private: bool | None) -> str:
    body = f"""
<h1>Architecture</h1>
<p class="lede">A planner proposes one step at a time. The runner checks every step against a policy,
runs it through a tool server, checkpoints the result and writes an audit entry. Nothing the
planner says can bypass the runner.</p>
{architecture_svg()}
<h2>What is enforced, and where</h2>
<ul>
<li><strong>Resumable.</strong> Every step is checkpointed; a hard-killed run resumes at the first unfinished step.</li>
<li><strong>Budgets.</strong> Steps, wall time and tokens are limited. When one is exhausted the run jumps to a
bounded wrap-up (compare, review, refit, predict, report) and still returns the best model so far.</li>
<li><strong>Guardrails.</strong> A code policy, deterministic reviewer checks, an untrusted-data sanitiser and a
structural action guard that does not depend on the model behaving.</li>
<li><strong>Approvals.</strong> Deployment needs a single-use token bound to the action, the run and the model;
the run pauses as <code>awaiting_approval</code> until an admin approves it.</li>
<li><strong>Two planners.</strong> A deterministic scripted planner (used for the example runs here) and an LLM
planner that only chooses which model family to try next. The LLM never sees column names or cell values.</li>
<li><strong>Honest evaluation.</strong> Benchmark numbers on the <a href="results.html">results page</a> are
generated from result files, with the planner and LLM mode stated in every row.</li>
</ul>
<h2>What the live demo would disable</h2>
<p>A hosted demo runs the same runner with uploads, deployment and the code sandbox switched off, the scripted
planner only, a {MAX_WALL_S:.0f} s hard wall clock (the agent itself stops searching at a shorter soft
wall and wraps up, which is why the example runs list both), a {MAX_FLAML_S:.0f} s AutoML ceiling, one run at a time and per-address rate limits.
That mode exists in the repository (<code>DEMO_MODE=1</code>) and is covered by tests, but has no free
host today. {source_note(repo_private)}</p>
"""
    return page(
        "Architecture: junior-ml-dev", delink(body, repo_private), active="architecture.html"
    )


def build_site(
    out_dir: Path, cache_dir: Path, metrics_md: str, *, repo_private: bool | None = None,
    now: datetime | None = None,
) -> list[str]:  # fmt: skip
    """Write the whole site under `out_dir`; returns the relative paths written."""
    now = now or datetime.now(UTC)
    runs = load_runs(cache_dir)
    if not runs:
        raise ValueError("no pre-computed runs found")
    clean = sanitize_metrics(metrics_md)
    soft = int(runs[0].budget.get("max_wall_s", 0))
    written: dict[str, str] = {
        "index.html": index_page(clean, runs, repo_private, now, digest_of=metrics_md),
        "results.html": results_page(clean, repo_private, now, soft),
        "architecture.html": architecture_page(repo_private),
        "style.css": CSS,
        ".nojekyll": "",
        "README.md": (
            "# junior-ml-dev demo site\n\n"
            "Static site for the junior-ml-dev project: three pre-computed example runs (scripted "
            "planner, no LLM), the verified benchmark numbers and an architecture page. It is "
            "generated; nothing here executes code. The source repository is private.\n"
        ),
        "404.html": page(
            "Not found",
            '<h1>Page not found</h1><p><a href="index.html">Back to the home page</a></p>',
            active="",
        ).replace('href="style.css"', f'href="{SITE_BASE}style.css"'),
    }
    for r in runs:
        written[f"runs/{r.key}/index.html"] = run_page(r)
        written[f"runs/{r.key}/report.html"] = (cache_dir / r.key / "report.html").read_text(
            encoding="utf-8"
        )
    for rel, text in written.items():
        p = out_dir / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8", newline="\n")
    return sorted(written)
