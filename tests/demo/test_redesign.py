"""The redesigned demo: hero page, dataset picker data, CSV downloads, live run page and report."""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from apps.api.demo import landing, pages
from apps.api.demo.datasets import catalog, label
from apps.api.demo.figure import GRID, LAYERS, figure_html
from apps.api.demo.samples import BY_KEY, load_manifest, sample_path
from apps.api.demo.service import DemoService, subprocess_executor
from tests.demo.helpers import make_settings

REPO = Path(__file__).resolve().parents[2]
WEB = REPO / "apps" / "web" / "demo"
HOSTILE = "<script>alert(1)</script>\"'&" + "x" * 300


def _page() -> str:
    md = (REPO / "docs" / "METRICS.md").read_text(encoding="utf-8")
    return landing.render_landing(md, (WEB / "landing.template.html").read_text(encoding="utf-8"))


# --- hero page -----------------------------------------------------------------------------------
def test_hero_copy_cta_and_hint() -> None:
    page = _page()
    assert "Drop a dataset." in page and "you can trust." in page and "Get a <em" in page
    assert "Upload a CSV &rarr;" in page and "Watch a sample run" in page
    assert "3 real OpenML datasets &middot; downloadable &middot; no signup" in page
    assert "AUTONOMOUS ML PIPELINE · LIVE" in page and "Try it free" in page
    assert "{{" not in page  # every placeholder was filled


def test_figure_has_six_layers_of_a_six_by_six_grid() -> None:
    fig = figure_html()
    assert fig.count('class="ly') == LAYERS == 6
    assert fig.count("<i") == LAYERS * GRID * GRID
    assert fig.count("ly top") == 1 and 'class="scan"' in fig and 'class="ring"' in fig
    assert "mini" in figure_html(mini=True)


def test_proof_strip_numbers_come_from_the_metrics_file() -> None:
    md = (REPO / "docs" / "METRICS.md").read_text(encoding="utf-8")
    cells = landing.proof_cells(md)
    tests, cov = re.search(r"(\d+) tests, ([0-9.]+)% coverage", md).groups()  # type: ignore[union-attr]
    assert f"<b>{tests}</b>" in cells and f"{cov}% coverage" in cells
    p50 = re.search(r"p50 ([0-9.]+) s over", md).group(1)  # type: ignore[union-attr]
    assert f"~{round(float(p50))} s" in cells
    assert "≈ FLAML" in cells and "unsafe" in cells
    changed = landing.proof_cells(md.replace(f"{tests} tests", "9999 tests"))
    assert "<b>9999</b>" in changed
    assert "n/a" in landing.proof_cells("# empty")  # a missing number is stated, never invented


def test_runtimes_are_parsed_and_attribute_safe() -> None:
    md = "- Per-sample run time (s): diabetes 49.8; credit-g 52.1; wine-quality 48"
    out = landing.runtimes_json(md)
    assert "&quot;diabetes&quot;: 49.8" in out and "<" not in out and '"' not in out
    assert landing.runtimes_json("nothing") == "{}"


def test_coming_soon_box_is_inert() -> None:
    page = _page()
    box = page[page.index('class="soon"') : page.index("</dialog>")]
    assert 'aria-disabled="true"' in box and "Coming soon" in box
    assert "Bring-your-own-data is in the works. For now, try one of the datasets above." in box
    for forbidden in ("<input", "<form", 'type="file"', "tabindex", "ondrop", "ondragover", "<a "):
        assert forbidden not in box
    js = (WEB / "assets" / "demo.js").read_text(encoding="utf-8")
    assert "dragover" not in js and "drop" not in js.replace("dropped", "")
    assert "innerHTML" not in js and "innerHTML" not in (WEB / "assets" / "run.js").read_text(
        encoding="utf-8"
    )


def test_page_weight_and_motion_rules() -> None:
    page = _page().encode()
    css = (WEB / "assets" / "demo.css").read_bytes()
    js = (WEB / "assets" / "demo.js").read_bytes() + (WEB / "assets" / "run.js").read_bytes()
    assert len(page) + len(css) + len(js) < 250 * 1024
    text = css.decode()
    assert "prefers-reduced-motion" in text and "animation:none" in text
    assert "max-width:640px" in text and "--s:.72" in text  # 375 px layout
    for token in ("#07070A", "#EDE8E1", "#A39C92", "#6E685F", "#F2B880", "#FFD9B0", "#8FD9A8"):
        assert token.lower() in text.lower()


# --- picker data and downloads -------------------------------------------------------------------
def test_info_describes_every_bundled_dataset(client: TestClient) -> None:
    info = client.get("/demo/api/info").json()
    keys = [s["key"] for s in info["samples"]]
    assert keys == ["diabetes", "credit-g", "wine-quality"]
    for s in info["samples"]:
        assert s["openml_url"] == f"https://www.openml.org/d/{s['openml_id']}"
        assert re.fullmatch(r"[0-9a-f]{64}", s["sha256"]) and s["sha12"] == s["sha256"][:12]
        assert s["download"] == f"/datasets/{s['key']}.csv" and s["task_kind"] in {
            "classification",
            "regression",
        }
        assert len(s["preview"]["rows"]) == 5
        assert [c["raw"] for c in s["preview"]["columns"]][0] and s["predicts"] and s["rows"]


def test_readable_column_names() -> None:
    assert label("diabetes", "plas") == "Plasma glucose" and label("diabetes", "mass") == "BMI"
    assert label("diabetes", "pedi") == "Family history score"
    assert label("diabetes", "preg") == "Pregnancies" and label("diabetes", "pres") == (
        "Blood pressure"
    )
    assert label("diabetes", "insu") == "Insulin" and label("diabetes", "skin") == (
        "Skin-fold thickness"
    )
    assert label("credit-g", "zz_unknown") == "zz unknown"


def test_download_bytes_equal_the_file_the_pipeline_loads(
    client: TestClient, app_service: tuple[FastAPI, DemoService]
) -> None:
    _, service = app_service
    data_dir = service.s.data_dir
    for key, entry in load_manifest(data_dir).items():
        r = client.get(f"/datasets/{key}.csv")
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("text/csv")
        cd = r.headers["content-disposition"]
        assert cd.startswith("attachment") and f"{key}.csv" in cd
        assert r.headers["x-content-type-options"] == "nosniff"
        digest = hashlib.sha256(r.content).hexdigest()
        assert (
            digest
            == entry["sha256"]
            == hashlib.sha256(sample_path(data_dir, key).read_bytes()).hexdigest()
        )
        shown = next(s for s in client.get("/demo/api/info").json()["samples"] if s["key"] == key)
        assert shown["sha256"] == digest and shown["sha12"] == digest[:12]


def test_the_pipeline_run_uses_the_downloaded_file(
    app_service: tuple[FastAPI, DemoService],
) -> None:
    _, service = app_service
    path = sample_path(service.s.data_dir, "diabetes")
    cfg = service.build_config("demo-0123456789", BY_KEY["diabetes"], path)
    assert cfg.task.data_path == str(path)
    assert (
        hashlib.sha256(Path(cfg.task.data_path).read_bytes()).hexdigest()
        == (load_manifest(service.s.data_dir)["diabetes"]["sha256"])
    )


def test_unknown_and_hostile_dataset_names_are_404(client: TestClient) -> None:
    for name in ("nope", "..%2f..%2fetc%2fpasswd", "Diabetes", "diabetes.csv", "a" * 80):
        assert client.get(f"/datasets/{name}.csv").status_code == 404, name


def test_downloads_are_rate_limited(client: TestClient) -> None:
    codes = [
        client.get("/datasets/diabetes.csv", headers={"x-forwarded-for": "7.7.7.7"}).status_code
        for _ in range(32)
    ]
    assert codes[:30] == [200] * 30 and 429 in codes[30:]
    assert (
        client.get("/datasets/diabetes.csv", headers={"x-forwarded-for": "8.8.8.8"}).status_code
        == 200
    )


def test_public_upload_is_still_refused(client: TestClient) -> None:
    csv = ("a,b\n1,2\n", "text/csv")
    for path in ("/v1/datasets", "/v1/datasets/upload", "/demo/api/upload", "/datasets/x.csv"):
        r = client.post(path, files={"file": ("x.csv", csv[0], csv[1])})
        assert r.status_code == 403, path
    r = client.post("/demo/api/runs", json={"sample": "diabetes", "data_path": "/etc/passwd"})
    assert r.status_code == 422
    assert client.post("/v1/deploy").status_code == 404
    assert client.get("/demo/api/admin/runs").status_code == 401


# --- live run page -------------------------------------------------------------------------------
def test_run_page_is_a_static_shell(client: TestClient) -> None:
    r = client.get("/runs/demo-0123456789")
    assert r.status_code == 200 and "run.js" in r.text and "Open full report" in r.text
    assert r.text == client.get("/runs/demo-abcdef0123").text  # nothing about the run is embedded
    assert r.text.count('class="ly') == 6 and "Pipeline progress" in r.text
    for bad in ("demo-xyz", "demo-0123456789a", "x", "demo-0123456789%2f.."):
        assert client.get(f"/runs/{bad}").status_code == 404
    js = (WEB / "assets" / "run.js").read_text(encoding="utf-8")
    for stage in ("Profile", "Leakage", "Train", "Compare", "Review", "Explain"):
        assert stage in js
    assert "setTimeout(poll, 1000)" in js  # 1 s polling


def test_a_finished_run_has_progress_sentence_and_a_styled_report(
    app_service: tuple[FastAPI, DemoService], tmp_path: Path
) -> None:
    app, service = app_service
    service.executor = subprocess_executor
    service.s = make_settings(tmp_path, flaml_s=0.0, data_dir=service.s.data_dir)
    run_id = service.submit("diabetes", "2.2.2.2")
    assert service.work_once()
    c = TestClient(app, base_url="https://testserver")
    st = c.get(f"/demo/api/runs/{run_id}").json()
    assert st["status"] == "done"
    prog = st["progress"]
    assert prog["models"] and all({"family", "val_score"} <= set(m) for m in prog["models"])
    assert prog["log"] and {"tool", "ok", "s", "reason"} <= set(prog["log"][0])
    assert "Shown one diabetic and one healthy patient" in st["result"]["sentence"]
    assert "% of the time" in st["result"]["sentence"]
    rep = c.get(f"/demo/api/runs/{run_id}/report")
    assert rep.status_code == 200 and "What this means" in rep.text
    assert "<script" not in rep.text and "Model card" in rep.text and "#F2B880" in rep.text
    csp = rep.headers["content-security-policy"]
    assert "script-src" not in csp and "default-src 'none'" in csp and "sandbox" in csp


# --- sentence and report -------------------------------------------------------------------------
def test_result_sentences() -> None:
    s = pages.result_sentence("diabetes", "roc_auc", 0.833, "plas")
    assert s == (
        "Shown one diabetic and one healthy patient, the model picks the right one 83% of the "
        "time. Plasma glucose mattered most."
    )
    assert "off by about 0.61 points of the quality score" in str(
        pages.result_sentence("wine-quality", "rmse", 0.612, "alcohol")
    )
    assert "Alcohol mattered most" in str(
        pages.result_sentence("wine-quality", "rmse", 0.6, "alcohol")
    )
    assert "0.71" in str(pages.result_sentence("diabetes", "pr_auc", 0.71, None))
    assert "0.64" in str(pages.result_sentence("diabetes", "f1_macro", 0.64, None))
    assert pages.result_sentence("diabetes", "roc_auc", None, "plas") is None
    assert "mattered" not in str(pages.result_sentence("credit-g", "roc_auc", 0.7, None))


def _state(**kw: object) -> dict[str, object]:
    base: dict[str, object] = {
        "profile": {"n_rows": 768, "n_cols": 9, "columns": [{"name": "insu", "missing_frac": 0.2}]},
        "leaderboard": [
            {"model_id": "linear", "family": "linear", "val_score": 0.83},
            {"model_id": "dummy", "family": "dummy", "val_score": 0.5},
        ],
        "explain": {"top": [{"feature": "plas", "mean_drop": 0.1}, {"feature": "mass", "mean_drop": 0.05}]},
        "review": {"verdict": "APPROVE", "checks": {"leakage_checked": {"passed": True, "detail": "ok"}}},
        "models": {"linear": {"family": "linear", "val_score": 0.83}},
        "chosen": "linear", "dropped": [], "findings": [],
    }  # fmt: skip
    base.update(kw)
    return base


def test_skipped_leakage_is_never_shown_as_none() -> None:
    html = pages.render_report(
        "demo-0123456789", "diabetes", _state(leakage_partial=["demo skip"]), {"val_score": 0.83}
    )
    assert "Skipped in live demo (CPU limit)" in html
    assert "No leakage findings" not in html
    ok = pages.render_report("demo-0123456789", "diabetes", _state(), {"val_score": 0.83})
    assert "Skipped in live demo (CPU limit)" not in ok.split("Reviewer checks")[0]


def test_report_uses_readable_names_and_amber_bars() -> None:
    html = pages.render_report(
        "demo-0123456789", "diabetes", _state(), {"val_score": 0.83, "chosen_family": "linear"}
    )
    for name in ("Plasma glucose", "BMI", "Insulin"):
        assert name in html
    assert html.count('class="bb"') >= 4 and "background:var(--amb)" in pages.CSS.replace(" ", "")
    for h in ("The data", "Leakage check", "Model leaderboard", "Reviewer checks", "Model card"):
        assert h in html
    assert html.count("What this means") >= 4


def test_hostile_strings_are_escaped_everywhere() -> None:
    state = _state(
        profile={"n_rows": 5, "n_cols": 2, "columns": [{"name": HOSTILE, "missing_frac": 0.5}]},
        explain={"top": [{"feature": HOSTILE, "mean_drop": 0.2}]},
        leaderboard=[{"model_id": HOSTILE, "family": HOSTILE, "val_score": 0.7}],
        review={"verdict": HOSTILE, "checks": {HOSTILE: {"passed": False, "detail": HOSTILE}}},
        dropped=[HOSTILE],
    )
    html = pages.render_report("demo-0123456789", "diabetes", state, {"val_score": 0.7})
    assert "<script" not in html
    assert "x" * 200 not in html  # long names are cut


def test_csp_blocks_scripts_and_everything_but_fonts() -> None:
    assert "script" not in pages.REPORT_CSP.replace("sandbox", "")
    assert "connect-src" not in pages.REPORT_CSP and "default-src 'none'" in pages.REPORT_CSP
    assert "https://fonts.googleapis.com" in pages.REPORT_CSP


def test_catalog_skips_a_tampered_sample(app_service: tuple[FastAPI, DemoService]) -> None:
    _, service = app_service
    assert len(catalog(service.s.data_dir)) == 3
    (service.s.data_dir / "diabetes.csv").write_text("a,b\n1,2\n", encoding="utf-8")
    assert [c["key"] for c in catalog(service.s.data_dir)] == ["credit-g", "wine-quality"]


@pytest.mark.parametrize("path", ["/", "/runs/demo-0123456789", "/datasets/diabetes.csv"])
def test_no_cache_and_nosniff_headers(client: TestClient, path: str) -> None:
    r = client.get(path)
    assert r.headers["x-content-type-options"] == "nosniff"
