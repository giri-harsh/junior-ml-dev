"""Landing page rendering, sample preparation and the sample manifest."""

from __future__ import annotations

import re
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd
import pytest

from apps.api.demo import landing
from apps.api.demo.prepare import TEMPLATE, prepare_samples, shape_frame
from apps.api.demo.samples import BY_KEY, SAMPLES, load_manifest, sample_path
from tests.demo.helpers import make_raw_samples

REPO = Path(__file__).resolve().parents[2]
MD = """# Verified metrics

Intro line with `code`.

## Headline arm (unseen)

| Arm | Normalized score [95% CI] | Pass vs linear | Source |
|---|---|---|---|
| SCRIPTED | 0.4242 [0.1, 0.9] | 3/10 | [`a.json`](../benchmarks/results/a.json) |
| OTHER <b>x</b> | 0.5151 [0.2, 0.8] | 4/10 | [x](javascript:alert(1)) |

## Second

- bullet **bold** [rel](docs/X.md) and [ext](https://example.org/p?q=1&r=2)
"""


def test_numbers_come_from_the_file_not_from_the_renderer() -> None:
    tpl = "<h1>{{HEADLINE_NAME}}</h1>{{TILES}}{{HEADLINE}}{{MORE}}{{METRICS_SHA}}{{GENERATED}}{{REPO_URL}}"
    page = landing.render_landing(MD, tpl, now=datetime(2026, 1, 2, tzinfo=UTC))
    assert "0.4242" in page and "0.5151" in page and "3/10" in page
    changed = landing.render_landing(MD.replace("0.4242", "0.9999"), tpl)
    assert "0.9999" in changed and "0.4242" not in changed
    assert page != changed  # the file hash changes too
    assert "2026-01-02" in page and "github.com/giri-harsh/junior-ml-dev" in page
    assert 'class="tile"' in page  # one tile per headline row


def test_markdown_subset_escapes_html_and_rewrites_links() -> None:
    page = landing.render_landing(MD, "{{HEADLINE}}{{MORE}}")
    assert "<b>x</b>" not in page and "&lt;b&gt;x&lt;/b&gt;" in page
    assert "javascript:" not in page  # unsafe link target dropped, text kept
    assert (
        'href="https://github.com/giri-harsh/junior-ml-dev/blob/main/benchmarks/results/a.json"'
        in page
    )
    assert 'href="https://github.com/giri-harsh/junior-ml-dev/blob/main/docs/X.md"' in page
    assert 'href="https://example.org/p?q=1&amp;r=2"' in page
    assert "<strong>bold</strong>" in page and "<code>a.json</code>" in page


def test_real_metrics_file_renders_with_every_headline_number(tmp_path: Path) -> None:
    md = (REPO / "docs" / "METRICS.md").read_text(encoding="utf-8")
    out = landing.build_landing(REPO / "docs" / "METRICS.md", TEMPLATE, tmp_path / "site")
    page = out.read_text(encoding="utf-8")
    assert "{{" not in page
    first_table = [ln for ln in md.splitlines() if ln.startswith("|")][2]
    scores = re.findall(r"\d\.\d{3} \[[^\]]+\]", first_table)
    assert scores and all(s in page for s in scores)
    assert "https://github.com/giri-harsh/junior-ml-dev" in page
    assert "<script>" not in page.replace('<script src="/demo-assets/demo.js" defer></script>', "")


def test_prepare_builds_samples_with_a_hash_manifest(tmp_path: Path) -> None:
    raw = tmp_path / "raw"
    make_raw_samples(raw)
    entries = prepare_samples(tmp_path / "out", from_dir=raw)
    assert {e["key"] for e in entries} == {s.key for s in SAMPLES}
    assert all(e["bytes"] < 5 * 1024 * 1024 for e in entries)
    out = tmp_path / "out"
    assert set(load_manifest(out)) == {s.key for s in SAMPLES}
    diab = pd.read_csv(sample_path(out, "diabetes"))
    assert set(diab["diabetes"].unique()) <= {0, 1} and BY_KEY["diabetes"].target in diab.columns
    (out / "diabetes.csv").write_text("a\n1\n", encoding="utf-8")
    with pytest.raises(ValueError, match="manifest hash"):
        sample_path(out, "diabetes")
    with pytest.raises(KeyError):
        sample_path(out, "not-a-sample")
    with pytest.raises(KeyError):
        sample_path(out, "../diabetes")


def test_shape_frame_maps_the_positive_class_and_renames_the_target() -> None:
    df = pd.DataFrame({"x": [1, 2, 3], "class": pd.Categorical(["bad", "good", "bad"])})
    out = shape_frame(df, BY_KEY["credit-g"])
    assert list(out["bad_credit"]) == [1, 0, 1] and "class" not in out.columns
    with pytest.raises(ValueError, match="missing"):
        shape_frame(pd.DataFrame({"x": [1]}), BY_KEY["credit-g"])


def test_the_demo_static_page_has_no_inline_script_and_no_innerhtml() -> None:
    web = REPO / "apps" / "web" / "demo"
    js = (web / "assets" / "demo.js").read_text(encoding="utf-8")
    assert "innerHTML" not in js and "eval(" not in js
    tpl = (web / "landing.template.html").read_text(encoding="utf-8")
    assert re.findall(r"<script(?![^>]*\bsrc=)", tpl) == []
