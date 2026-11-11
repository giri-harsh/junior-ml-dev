"""Demo v2: narration, answer sentences, the visual report, and the junior-dev avatar."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pytest

from apps.api.demo import narration, pages
from apps.api.demo.avatar import avatar_html
from apps.api.demo.datasets import catalog, histogram
from apps.api.demo.report_view import render_report

REPO = Path(__file__).resolve().parents[2]
ASSETS = REPO / "apps" / "web" / "demo" / "assets"
HOSTILE = "<script>alert(1)</script>\"'&" + "y" * 300

STEPS = [
    ("profile_dataset", None, 1.0), ("detect_leakage", None, 0.0), ("decide_leakage", None, 0.0),
    ("train_model", "dummy", 0.2), ("train_model", "linear", 0.5), ("train_model", "hgb", 2.0),
    ("train_model", "rf", 3.0), ("tune_model", "hgb", 1.0), ("compare_models", None, 0.3),
    ("review", None, 0.1), ("explain_model", None, 0.4), ("report", None, 0.1),
]  # fmt: skip


def steps() -> list[dict[str, Any]]:
    return [{"tool": t, "family": f, "secs": s, "ok": True, "reason": ""} for t, f, s in STEPS]


def state(**kw: Any) -> dict[str, Any]:
    models = {
        "dummy-1": {
            "family": "dummy",
            "val_score": 0.5,
            "fit_s": 0.1,
            "selection": "cv",
            "cv_k": 5,
        },
        "linear-1": {
            "family": "linear",
            "val_score": 0.7123,
            "fit_s": 0.2,
            "selection": "cv",
            "cv_k": 5,
        },
        "hgb-1": {"family": "hgb", "val_score": 0.7301, "fit_s": 1.9, "selection": "cv", "cv_k": 5},
        "rf-1": {"family": "rf", "val_score": 0.7412, "fit_s": 2.9, "selection": "cv", "cv_k": 5},
        "hgb-2": {"family": "hgb", "val_score": 0.7388, "fit_s": 0.9, "selection": "cv", "cv_k": 5},
    }
    base: dict[str, Any] = {
        "profile": {
            "n_rows": 4321, "n_cols": 9, "duplicate_rows": 3,
            "columns": [{"name": "insu", "missing_frac": 0.2}],
            "target": {"name": "diabetes", "n_classes": 2, "class_balance": {"0": 0.3, "1": 0.7}},
        },
        "models": models, "chosen": "rf-1", "dropped": [], "findings": [],
        "leaderboard": [
            {"model_id": k, "family": v["family"], "val_score": v["val_score"]}
            for k, v in models.items()
        ],
        "explain": {"n_eval": 1080, "top": [
            {"feature": "plas", "mean_drop": 0.2}, {"feature": "mass", "mean_drop": 0.1},
            {"feature": "age", "mean_drop": 0.05}, {"feature": "pedi", "mean_drop": 0.02},
            {"feature": "pres", "mean_drop": 0.01}, {"feature": "skin", "mean_drop": 0.001},
        ]},
        "review": {"verdict": "APPROVE", "checks": {
            "a": {"passed": True, "detail": "ok"}, "b": {"passed": True, "detail": "ok"},
        }},
        "leakage_partial": [],
    }  # fmt: skip
    base.update(kw)
    return base


def report(st: dict[str, Any] | None = None, key: str = "diabetes", **kw: Any) -> str:
    summary = {"val_score": 0.7412, "latency_s": 8.6, "chosen_family": "rf"}
    return render_report(
        "demo-0123456789", key, st or state(), kw.pop("summary", summary), steps(), kw.get("dist")
    )


# --- narration ------------------------------------------------------------------------------------
def test_every_pipeline_step_has_a_narration_line() -> None:
    assert {t for t, _ in narration.CANON} == narration.PIPELINE_TOOLS
    lines = []
    for i in range(len(narration.CANON)):
        done = list(narration.CANON[:i])
        n = narration.narrate("running", done=done)
        assert n["state"] == "working" and n["line"]
        lines.append(n["line"])
    assert lines[0] == narration.STARTING
    expect = {
        1: "leaks the answer", 2: "leaks the answer", 3: "do-nothing baseline", 4: "linear model",
        5: "gradient boosting", 6: "random forest", 7: "Tuning", 9: "rows the models never saw",
        10: "Double-checking my own work", 11: "what mattered most", 12: "what mattered most",
        13: "Writing it all up",
    }  # fmt: skip
    for i, text in expect.items():
        assert text in lines[i], (i, lines[i])
    assert "Reading every row first" in narration.LINES["profile_dataset"]


def test_leakage_skipped_and_other_states() -> None:
    after_profile = [("profile_dataset", None)]
    assert "leaks the answer" in narration.narrate("running", done=after_profile)["line"]
    skipped = narration.narrate("running", done=after_profile, leakage_skipped=True)
    assert skipped["line"] == "Skipping the leakage hunt to fit the free server."
    q = narration.narrate("queued", queue_position=2)
    assert q["state"] == "idle" and "number 2" in q["line"] and "one dataset at a time" in q["line"]
    done = narration.narrate("done", sentence="It is 83%.")
    assert done == {"state": "done", "line": "It is 83%."}
    assert narration.narrate("done")["state"] == "done"
    for status in ("failed", "interrupted"):
        e = narration.narrate(status)
        assert e["state"] == "error" and "tripped me up" in e["line"]
    assert narration.narrate("timeout")["state"] == "error"
    assert all(
        narration.narrate(s)["state"] in narration.STATES for s in ("queued", "done", "failed")
    )


def test_training_line_follows_the_model_that_just_finished() -> None:
    done = [*narration.CANON[:4]]  # dummy finished -> linear next
    assert "linear model" in narration.narrate("running", done=done)["line"]
    done = [*narration.CANON[:6]]  # hgb finished -> rf next
    assert "random forest" in narration.narrate("running", done=done)["line"]
    # budget exhausted after hgb: the planner jumps to compare, so does the narration
    jumped = [*narration.CANON[:6], ("compare_models", None)]
    assert "never saw" not in narration.narrate("running", done=jumped)["line"]
    assert "Double-checking" in narration.narrate("running", done=jumped)["line"]


def test_page_data_has_four_to_five_tips() -> None:
    blob = json.loads(__import__("html").unescape(narration.page_data()))
    assert 4 <= len(blob["tips"]) <= 5 and "{name}" in blob["listening"]
    assert any("never trained on" in t for t in blob["tips"])


# --- answer sentences -----------------------------------------------------------------------------
def test_answer_parts_for_every_metric() -> None:
    auc = pages.answer_parts("diabetes", "roc_auc", 0.834)
    assert auc is not None and auc[1] == "83%" and "picks the right one" in auc[0]
    assert pages.answer_parts("diabetes", "accuracy", 0.912) == (
        "The model gets ",
        "91%",
        " of cases right.",
    )
    rmse = pages.answer_parts("wine-quality", "rmse", 0.612)
    assert rmse is not None and rmse[1] == "0.61" and "typically off by about" in rmse[0]
    assert "points of the quality score" in rmse[2]
    assert pages.answer_parts("wine-quality", "r2", 0.456) == (
        "The model explains ",
        "46%",
        " of the variation.",
    )
    assert pages.answer_parts("wine-quality", "mae", 0.4) is not None
    assert pages.answer_parts("diabetes", "roc_auc", None) is None
    full = pages.result_sentence("wine-quality", "rmse", 0.612, "alcohol")
    assert full is not None and full.endswith("Alcohol mattered most.")


# --- the report -----------------------------------------------------------------------------------
def test_report_sections_in_order_with_real_numbers() -> None:
    html = report()
    order = [
        "Reviewer approved", "The answer", "What the agent did", "Which model won?",
        "What drove the prediction?", "What was in the data?", "Where the time went",
        "Try another dataset", "Model card",
    ]  # fmt: skip
    pos = [html.index(s) for s in order]
    assert pos == sorted(pos)
    assert "4321" in html and "768" not in html  # rows come from the run, not from a constant
    assert "30%" in html and "70%" in html  # donut legend from class_balance
    assert "0.7412" in html and "0.7123" in html  # leaderboard values from the state
    assert "Plasma glucose" in html and '<code class="raw">plas</code>' in html
    assert html.count('class="ib"') == 5  # top five only
    assert "83%" not in html and ">74%<" in html  # the answer's key number: 0.7412 AUC


def test_changes_requested_pill_and_missing_run_time() -> None:
    st = state(review={"verdict": "REQUEST_CHANGES", "checks": {}})
    html = report(st, summary={"val_score": 0.7})
    assert "Changes requested" in html and "Reviewer approved" not in html
    assert " s run" not in html  # no invented run time


def test_wire_diagram_nodes_winner_tooltips_and_durations() -> None:
    html = report()
    for name in ("Profile", "Leakage hunt", "Compare", "Review", "Explain"):
        assert f"<b>{name}</b>" in html
    assert html.count("wn sm") == 5  # dummy, linear, hgb, rf, hgb (tuned)
    assert html.count("wn sm win") == 1 and re.search(r"wn sm win[^>]*><b>rf</b>", html)
    assert "<b>hgb (tuned)</b>" in html and "5-fold CV" in html
    assert html.count('role="tooltip"') == 10
    assert "3.0 s" in html and "0.2 s" in html  # real durations
    assert "wc off" not in html and "skipped in demo" not in html
    skipped = report(state(leakage_partial=["demo skip"]))
    assert "wn skip" in skipped and "skipped in demo" in skipped and "wc off" in skipped
    holdout = state()
    for m in holdout["models"].values():
        m["selection"] = "holdout"
    assert "holdout" in report(holdout) and "5-fold CV" not in report(holdout)


def test_model_chart_baseline_and_winner_colours() -> None:
    html = report()
    assert html.count('class="col win"') == 1 and 'class="bl"' in html
    assert "baseline 0.50" in html
    css = (ASSETS / "report.css").read_text(encoding="utf-8")
    assert ".col.win i{background:var(--amb)" in css and "--grey:#4A443D" in css


def test_time_bar_title_names_the_biggest_consumer() -> None:
    html = report()
    train = 0.2 + 0.5 + 2.0 + 3.0 + 1.0
    total = sum(s for _, _, s in STEPS)
    assert f"Train took {round(train / total * 100)}% of the time" in html
    assert html.count('class="stack"') == 1 and 'title="Train 6.7 s"' in html


def test_regression_report_uses_a_target_histogram_and_range() -> None:
    values = [3.0, 4.0, 4.0, 5.0, 5.0, 5.0, 6.0, 6.0, 7.0, 8.0]
    st = state(
        profile={"n_rows": 10, "n_cols": 4, "columns": [], "target": {"name": "quality"}},
        models={
            "dummy-1": {"family": "dummy", "val_score": 1.4, "fit_s": 0.1, "selection": "cv"},
            "linear-1": {"family": "linear", "val_score": 0.65, "fit_s": 0.1, "selection": "cv"},
        },
        chosen="linear-1",
        leaderboard=[
            {"model_id": "dummy-1", "family": "dummy", "val_score": 1.4},
            {"model_id": "linear-1", "family": "linear", "val_score": 0.65},
        ],
    )
    html = render_report(
        "demo-0123456789", "wine-quality", st, {"val_score": 0.65, "latency_s": 3.0},
        steps(), histogram(values),
    )  # fmt: skip
    assert html.count('class="hist"') == 1 and "donut" not in html.replace(".donut", "")
    assert (
        len(re.findall(r'<i style="height:', re.search(r'class="hist".*?</div>', html).group(0)))
        >= 12
    )  # type: ignore[union-attr]
    assert "3 to 8" in html and "target range" in html
    assert "typically off by about" in html and "0.65" in html
    assert "always guess the average 1.40" in html and "Lower is better" in html
    assert "explains about" in html  # R2 from rmse and the target's spread
    hist = histogram(values)
    assert sum(hist["counts"]) == 10 and hist["min"] == 3.0 and hist["max"] == 8.0


def test_hostile_strings_are_escaped_in_charts_and_tooltips() -> None:
    st = state(
        profile={"n_rows": 5, "n_cols": 2, "columns": [{"name": HOSTILE, "missing_frac": 0.5}],
                 "target": {"class_balance": {HOSTILE: 1.0}, "n_classes": HOSTILE}},
        explain={"n_eval": HOSTILE, "top": [{"feature": HOSTILE, "mean_drop": 0.2}]},
        models={HOSTILE: {"family": HOSTILE, "val_score": 0.7, "fit_s": 1.0, "cv_k": HOSTILE}},
        chosen=HOSTILE,
        leaderboard=[{"model_id": HOSTILE, "family": HOSTILE, "val_score": 0.7}],
        review={"verdict": HOSTILE, "checks": {HOSTILE: {"passed": False, "detail": HOSTILE}}},
        dropped=[HOSTILE], findings=[HOSTILE],
    )  # fmt: skip
    hostile_steps = [
        {"tool": "train_model", "family": HOSTILE, "secs": 1.0, "ok": True, "reason": HOSTILE},
        *steps(),
    ]
    html = render_report("demo-0123456789", "diabetes", st, {"val_score": 0.7}, hostile_steps, None)
    assert html.count("<script") == 2 and "<script>" not in html
    assert "alert(1)</script>" not in html and "y" * 270 not in html
    assert "onerror" not in html and "javascript:" not in html


def test_report_assets_and_csp_policy() -> None:
    html = report()
    assert "/demo-assets/report.css" in html and "/demo-assets/avatar.js" in html
    assert re.findall(r"<script(?![^>]*\bsrc=)", html) == []  # no inline script
    csp = pages.REPORT_CSP
    assert "script-src 'self'" in csp and "connect-src" not in csp and "default-src 'none'" in csp
    css = (ASSETS / "report.css").read_text(encoding="utf-8")
    assert "prefers-reduced-motion" in css and "animation:none" in css
    assert "max-width:700px" in css and "flex-direction:column" in css  # vertical wire at 375
    assert ":target" in css  # CSS-only model card modal
    js = (ASSETS / "report.js").read_text(encoding="utf-8")
    assert "IntersectionObserver" in js and "innerHTML" not in js


# --- avatar ---------------------------------------------------------------------------------------
def test_avatar_markup_has_no_images_and_is_accessible() -> None:
    a = avatar_html()
    for forbidden in ("<img", "<canvas", "<svg", "url(", "src=", "<video", "<picture"):
        assert forbidden not in a
    assert '<button class="jd-btn" type="button" aria-label="Junior ML dev — click for a tip">' in a
    assert 'aria-live="polite"' in a and 'data-state="idle"' in a
    assert "jd-glass" in a and "jd-hair" in a and "jd-cord" in a and "jd-screen" in a
    assert avatar_html(say="a<b>")  # speech is escaped
    assert "a&lt;b&gt;" in avatar_html(say="a<b>") and "<b>" not in avatar_html(say="a<b>")
    assert "data-greet=1" in avatar_html(greet=True) and "jd small" in avatar_html(small=True)
    assert "jd-bubble" not in avatar_html(bubble=False)


def test_avatar_css_has_every_pose_and_reduced_motion() -> None:
    css = (ASSETS / "avatar.css").read_text(encoding="utf-8")
    for state_name in ("listening", "working", "done", "error"):
        assert f"data-state={state_name}" in css
    assert (
        'data-sweat="1"' in css and "jd-cheer" in css and "jd-scroll" in css and "jd-blink" in css
    )
    assert "jd-breathe" in css and "jd-type" in css
    assert "prefers-reduced-motion:reduce" in css and "animation:none!important" in css
    assert "max-width:640px" in css  # ~220 px avatar on phones
    cheer = re.search(r"jd-cheer 3s ease-in-out 1 forwards", css)
    assert cheer  # one cheer of at most 3 s, then idle-happy


def test_avatar_script_is_event_driven() -> None:
    js = (ASSETS / "avatar.js").read_text(encoding="utf-8")
    assert "setTimeout" not in js and "setInterval" not in js  # no timers drive the poses
    assert "innerHTML" not in js and "textContent" in js
    run = (ASSETS / "run.js").read_text(encoding="utf-8")
    assert "st.narration" in run and "jr.state(n.state)" in run and "jr.sweat(" in run
    assert "train_model" in run  # sweat looks at real training step durations
    landing_js = (ASSETS / "demo.js").read_text(encoding="utf-8")
    assert 'dev.jr.state("listening")' in landing_js and "s.action" in landing_js


def test_picker_buttons_are_instructions() -> None:
    import tempfile

    from tests.demo.helpers import make_samples

    with tempfile.TemporaryDirectory() as d:
        data = make_samples(Path(d))
        actions = {c["key"]: c["action"] for c in catalog(data)}
    assert actions == {
        "diabetes": "Build a model for diabetes",
        "credit-g": "Predict credit risk",
        "wine-quality": "Predict wine quality",
    }


def test_pages_carry_the_avatar_and_stay_light() -> None:
    from apps.api.demo import landing as landing_mod

    md = (REPO / "docs" / "METRICS.md").read_text(encoding="utf-8")
    tpl = (REPO / "apps" / "web" / "demo" / "landing.template.html").read_text(encoding="utf-8")
    page = landing_mod.render_landing(md, tpl)
    assert 'class="jd"' in page and "data-greet=1" in page and 'id="narr"' in page
    assert "/demo-assets/avatar.css" in page and "/demo-assets/avatar.js" in page
    run = (REPO / "apps" / "web" / "demo" / "run.template.html").read_text(encoding="utf-8")
    assert "{{AVATAR}}" in run and "avatar.js" in run and 'id="narr"' in run
    total = (
        sum(
            (ASSETS / n).stat().st_size
            for n in (
                "demo.css",
                "demo.js",
                "run.js",
                "avatar.css",
                "avatar.js",
                "report.css",
                "report.js",
            )
        )
        + len(page)
        + len(report())
    )
    assert total < 300 * 1024
    css = (ASSETS / "demo.css").read_text(encoding="utf-8")
    assert "heroart" in css and "prefers-reduced-motion" in css


@pytest.mark.parametrize(
    "status", ["queued", "running", "done", "failed", "timeout", "interrupted"]
)
def test_every_status_maps_to_a_known_pose(status: str) -> None:
    n = narration.narrate(status, done=[], queue_position=1)
    assert n["state"] in narration.STATES and n["line"]


def test_running_step_drives_the_narration() -> None:
    n = narration.narrate(
        "running", running=("explain_model", None), done=list(narration.CANON[:6])
    )
    assert n["line"] == narration.LINES["explain_model"]
    n = narration.narrate("running", running=("train_model", "rf"), done=[])
    assert "random forest" in n["line"]
    n = narration.narrate("running", running=("detect_leakage", None), leakage_skipped=True)
    assert n["line"] == narration.LINES["leakage_skipped"]
    n = narration.narrate("running", running=("not_a_tool", None), done=[("profile_dataset", None)])
    assert "leaks the answer" in n["line"]  # unknown marker falls back to the step log


def test_in_flight_marker_is_written_and_read(tmp_path: Path) -> None:
    import time as _t

    from apps.api.demo.config import DemoSettings
    from apps.api.demo.service import DemoService
    from tests.demo.helpers import make_samples, make_settings

    make_samples(tmp_path)
    s: DemoSettings = make_settings(tmp_path)
    svc = DemoService(s, lambda job: None)  # type: ignore[arg-type,return-value]
    run_dir = svc.runs_dir / "demo-0123456789"
    run_dir.mkdir(parents=True)
    (run_dir / "current.json").write_text(
        json.dumps({"tool": "explain_model", "family": None, "idx": 7, "started": _t.time() - 5}),
        encoding="utf-8",
    )
    prog = svc.progress("demo-0123456789")
    assert prog is not None and prog["running"]["tool"] == "explain_model"
    assert prog["running"]["idx"] == 7 and prog["running"]["for_s"] >= 4.5
    js = (ASSETS / "run.js").read_text(encoding="utf-8")
    assert "running for" in js and "prog.running" in js
