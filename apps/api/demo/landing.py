"""Render the landing page from docs/METRICS.md at image build time.

No number on the page is typed in here: the tables, the tiles and the caveats all come from the
metrics file, which `scripts/render_metrics.py` generates from the committed result JSONs.
The tiny Markdown subset converter handles exactly what that file uses (headings, pipe tables,
bullets, paragraphs, code, links, bold) and escapes everything else.
"""

from __future__ import annotations

import hashlib
import html
import json
import re
from datetime import UTC, datetime
from pathlib import Path

from apps.api.demo.config import REPO_URL, STATIC_SITE_URL
from apps.api.demo.figure import figure_html

_CODE = re.compile(r"`([^`]+)`")
_LINK = re.compile(r"\[([^\]]+)\]\(([^)\s]+)\)")
_BOLD = re.compile(r"\*\*([^*]+)\*\*")
_SAFE_URL = re.compile(r"^https?://[^\s\"'<>]+$")


def _link_target(url: str) -> str | None:
    """Relative repo links (../benchmarks/results/x.json) become GitHub blob links."""
    url = html.unescape(url)
    if _SAFE_URL.match(url):
        return url
    if "://" in url or url.startswith(("javascript:", "data:", "mailto:", "#")):
        return None
    rel = re.sub(r"^(?:\.\./|\./)+", "", url)
    if not rel or rel.startswith("/") or ".." in rel.split("/"):
        return None
    return f"{REPO_URL}/blob/main/{rel}"


def inline(text: str) -> str:
    out = html.escape(text, quote=True)
    out = _CODE.sub(lambda m: f"<code>{m.group(1)}</code>", out)

    def link(m: re.Match[str]) -> str:
        target = _link_target(m.group(2))
        if target is None:
            return m.group(1)
        return f'<a href="{html.escape(target, quote=True)}" rel="noopener">{m.group(1)}</a>'

    out = _LINK.sub(link, out)
    return _BOLD.sub(lambda m: f"<strong>{m.group(1)}</strong>", out)


def _cells(line: str) -> list[str]:
    return [c.strip() for c in line.strip().strip("|").split("|")]


def split_sections(md: str) -> tuple[str, list[tuple[str, list[str]]]]:
    """(title, [(h2 heading, body lines)]). Text before the first H2 is returned in the title."""
    title, sections = "", []
    cur: tuple[str, list[str]] | None = None
    for line in md.splitlines():
        if line.startswith("# ") and not title:
            title = line[2:].strip()
        elif line.startswith("## "):
            cur = (line[3:].strip(), [])
            sections.append(cur)
        elif cur is not None:
            cur[1].append(line)
        elif line.strip():
            title += "\n" + line
    return title, sections


def blocks_to_html(lines: list[str]) -> str:
    out: list[str] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        if not line.strip():
            i += 1
        elif line.lstrip().startswith("|"):
            rows = []
            while i < len(lines) and lines[i].lstrip().startswith("|"):
                rows.append(_cells(lines[i]))
                i += 1
            rows = [r for r in rows if not all(re.fullmatch(r":?-{2,}:?", c) for c in r)]
            head, body = rows[0], rows[1:]
            out.append('<div class="tbl"><table><thead><tr>')
            out.append("".join(f"<th>{inline(c)}</th>" for c in head))
            out.append("</tr></thead><tbody>")
            for r in body:
                out.append("<tr>" + "".join(f"<td>{inline(c)}</td>" for c in r) + "</tr>")
            out.append("</tbody></table></div>")
        elif line.lstrip().startswith("- "):
            out.append("<ul>")
            while i < len(lines) and lines[i].lstrip().startswith("- "):
                out.append(f"<li>{inline(lines[i].lstrip()[2:])}</li>")
                i += 1
            out.append("</ul>")
        else:
            para = []
            while (
                i < len(lines)
                and lines[i].strip()
                and not lines[i].lstrip().startswith(("|", "- "))
            ):
                para.append(lines[i].strip())
                i += 1
            out.append(f"<p>{inline(' '.join(para))}</p>")
    return "\n".join(out)


def _first_table(lines: list[str]) -> list[list[str]]:
    rows: list[list[str]] = []
    for line in lines:
        if line.lstrip().startswith("|"):
            rows.append(_cells(line))
        elif rows:
            break
    return [r for r in rows if not all(re.fullmatch(r":?-{2,}:?", c) for c in r)]


def tiles(lines: list[str]) -> str:
    """One tile per row of the headline table: arm, normalized score, pass count. [] if absent."""
    rows = _first_table(lines)
    if len(rows) < 2:
        return ""
    head = [h.lower() for h in rows[0]]

    def col(prefix: str) -> int | None:
        return next((i for i, h in enumerate(head) if h.startswith(prefix)), None)

    arm, score, passes = col("arm"), col("normalized score"), col("pass")
    if arm is None or score is None:
        return ""
    out = []
    for r in rows[1:]:
        if len(r) <= max(arm, score):
            continue
        sub = r[passes] if passes is not None and len(r) > passes else ""
        out.append(
            '<div class="tile">'
            f'<div class="tile-k">{inline(r[arm])}</div>'
            f'<div class="tile-v">{inline(r[score])}</div>'
            f'<div class="tile-s">pass vs linear: {inline(sub)}</div></div>'
            if sub
            else '<div class="tile">'
            f'<div class="tile-k">{inline(r[arm])}</div>'
            f'<div class="tile-v">{inline(r[score])}</div></div>'
        )
    return "\n".join(out)


CAPTIONS = (
    '<div class="cap c1"><b>01 · PROFILE</b><span id="cap-profile">rows · columns</span></div>'
    '<div class="cap c2"><b>02 · LEAKAGE HUNT</b><span>skipped on the free CPU</span></div>'
    '<div class="cap c3"><b>03 · MODEL RACE</b>'
    "<span>baseline · linear · boosting · forest</span></div>"
    '<div class="cap c4 am"><b>04 · REVIEW</b><span>rule-based sign-off</span></div>'
)


def _find(pattern: str, md: str) -> tuple[str, ...] | None:
    m = re.search(pattern, md)
    return m.groups() if m else None


def proof_cells(md: str) -> str:
    """The four proof cells. Every number is parsed from the metrics file; a missing one says so."""
    arm = _find(r"SCRIPTED planner \(no LLM\) \| ([0-9.]+) \[([0-9.]+), ([0-9.]+)\]", md)
    n = _find(r"\(n=(\d+)\)", md)
    inj = _find(r"unsafe actions executed (\d+)/(\d+)", md)
    gate = _find(r"(\d+) tests, ([0-9.]+)% coverage", md)
    p50 = _find(r"p50 ([0-9.]+) s over", md)
    n_tasks = n[0] if n else "10"
    cells = [
        (
            "≈ FLAML",
            f"matches an AutoML baseline on {n_tasks} unseen benchmarks"
            + (f" ({arm[0]} of FLAML, 95% CI {arm[1]} to {arm[2]})" if arm else ""),
        ),
        (
            f"{inj[0]} unsafe" if inj else "n/a",
            "actions executed in every prompt-injection test"
            + (f" ({inj[0]}/{inj[1]} real-LLM runs)" if inj else ""),
        ),
        (
            f"{gate[0]}" if gate else "n/a",
            f"tests · {gate[1]}% coverage" if gate else "tests and coverage: see METRICS.md",
        ),
        (
            f"~{round(float(p50[0]))} s" if p50 else "n/a",
            "dataset to report, on a free CPU (measured median)",
        ),
    ]
    return "".join(
        f'<div role="listitem"><b>{html.escape(big)}</b><span>{html.escape(small)}</span></div>'
        for big, small in cells
    )


def runtimes_json(md: str) -> str:
    """{"diabetes": 49.8, ...} from the line 'Per-sample run time (s): diabetes 49.8; ...'."""
    m = re.search(
        r"Per-sample run time \(s\): ((?:[a-z][a-z0-9\-]+ [0-9]+(?:\.[0-9]+)?(?:; )?)+)",
        md,
    )
    out: dict[str, float] = {}
    if m:
        for key, val in re.findall(r"([a-z][a-z0-9\-]+) ([0-9]+(?:\.[0-9]+)?)", m.group(1)):
            out[key] = float(val)
    return html.escape(json.dumps(out), quote=True)


def render_landing(metrics_md: str, template: str, *, now: datetime | None = None) -> str:
    title, sections = split_sections(metrics_md)
    head_name, head_body = sections[0] if sections else ("", [])
    rest = sections[1:]
    stamp = (now or datetime.now(UTC)).strftime("%Y-%m-%d %H:%M UTC")
    digest = hashlib.sha256(metrics_md.encode("utf-8")).hexdigest()[:12]
    more = "\n".join(
        f"<section><h3>{inline(name)}</h3>{blocks_to_html(body)}</section>" for name, body in rest
    )
    subs = {
        "REPO_URL": REPO_URL,
        "STATIC_URL": STATIC_SITE_URL,
        "METRICS_TITLE": inline(title.splitlines()[0] if title else "Verified metrics"),
        "METRICS_INTRO": blocks_to_html(title.splitlines()[1:]) if "\n" in title else "",
        "HEADLINE_NAME": inline(head_name),
        "TILES": tiles(head_body),
        "HEADLINE": blocks_to_html(head_body),
        "MORE": more,
        "GENERATED": stamp,
        "METRICS_SHA": digest,
        "FIGURE": figure_html(CAPTIONS),
        "PROOF": proof_cells(metrics_md),
        "RUNTIMES_JSON": runtimes_json(metrics_md),
    }
    page = template
    for k, v in subs.items():
        page = page.replace("{{" + k + "}}", v)
    return page


def build_landing(metrics_path: Path, template_path: Path, out_dir: Path) -> Path:
    page = render_landing(
        metrics_path.read_text(encoding="utf-8"), template_path.read_text(encoding="utf-8")
    )
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / "index.html"
    out.write_text(page, encoding="utf-8")
    return out
