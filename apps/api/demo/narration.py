"""What the junior dev says, and which pose it takes, for every moment of a run.

One source of truth: the server turns the agent's real step log into `{"state", "line"}` and the
page only displays it (no timers). The scripted planner always runs the same steps in the same
order, so the step that is running now is the one after the last step the checkpoints record.
"""

from __future__ import annotations

import html
import json
from typing import Any

# (tool, family) in the order the scripted planner runs them; family None = any
CANON: tuple[tuple[str, str | None], ...] = (
    ("profile_dataset", None),
    ("detect_leakage", None),
    ("decide_leakage", None),
    ("train_model", "dummy"),
    ("train_model", "linear"),
    ("train_model", "hgb"),
    ("train_model", "rf"),
    ("tune_model", "hgb"),
    ("train_model", "flaml"),
    ("compare_models", None),
    ("review", None),
    ("refit_full", None),
    ("explain_model", None),
    ("report", None),
)
PIPELINE_TOOLS = frozenset(t for t, _ in CANON)

MODEL_NAMES = {
    "dummy": "a do-nothing baseline",
    "linear": "a linear model",
    "hgb": "gradient boosting",
    "rf": "a random forest",
    "flaml": "an AutoML search",
}

QUEUED = "I'm in line: this free server runs one dataset at a time."
STARTING = "Getting set up. This server has a fraction of a CPU, so I'll take it steady."
LINES = {
    "profile_dataset": "Reading every row first. Never trust a CSV blindly.",
    "detect_leakage": "Checking no column secretly leaks the answer…",
    "decide_leakage": "Checking no column secretly leaks the answer…",
    "leakage_skipped": "Skipping the leakage hunt to fit the free server.",
    "tune_model": "Tuning the boosting model…",
    "compare_models": "Testing on rows the models never saw.",
    "review": "Double-checking my own work.",
    "refit_full": "Figuring out what mattered most.",
    "explain_model": "Figuring out what mattered most.",
    "report": "Writing it all up.",
}
TRAIN = "Training {model}…"
DONE_NO_MODEL = "I finished, but no model scored well enough to report."
ERROR = "That one tripped me up. Try another dataset."
TIMEOUT = "I ran out of time on this free server. Try another dataset."
LISTENING = "On it! Opening the {name} data now."
GREETING = "Hi, I'm the junior ML dev. Pick a dataset and watch me work."
CTA = "See my report"

TIPS = (
    "I test on data I never trained on, so the score is not flattered.",
    "A rule-based reviewer checks my work. I can't talk it into approving.",
    "Every number you see comes from the run, not from me.",
    "On this free server I skip the leakage hunt. The full system doesn't.",
    "I never see your files here: you can only pick the three public datasets.",
)

STATES = ("idle", "listening", "working", "done", "error")


def _next_index(done: list[tuple[str, str | None]]) -> int:
    """Index in CANON of the step after the last one finished (0 when none has)."""
    last = -1
    for tool, family in done:
        for i, (t, f) in enumerate(CANON):
            if t == tool and (f is None or f == family):
                last = max(last, i)
                break
    return last + 1


def current_line(done: list[tuple[str, str | None]], leakage_skipped: bool) -> str:
    """What the dev says while the step after `done` is running."""
    i = _next_index(done)
    if i >= len(CANON):
        return LINES["report"]
    tool, family = CANON[i]
    if not done:
        return LINES["profile_dataset"]
    if tool in ("detect_leakage", "decide_leakage"):
        return LINES["leakage_skipped"] if leakage_skipped else LINES[tool]
    if tool == "train_model":
        return TRAIN.format(model=MODEL_NAMES.get(family or "", "a model"))
    return LINES.get(tool, STARTING)


def narrate(
    status: str,
    *,
    done: list[tuple[str, str | None]] | None = None,
    leakage_skipped: bool = False,
    queue_position: int | None = None,
    sentence: str | None = None,
) -> dict[str, str]:
    """The avatar's pose and words for a run in `status` (queued, running, done, ...)."""
    if status == "queued":
        extra = f" (number {queue_position})" if queue_position else ""
        return {"state": "idle", "line": QUEUED[:-1] + extra + "."}
    if status == "running":
        if not done:
            return {"state": "working", "line": STARTING}
        return {"state": "working", "line": current_line(done, leakage_skipped)}
    if status == "done":
        return {"state": "done", "line": sentence or DONE_NO_MODEL}
    if status == "timeout":
        return {"state": "error", "line": TIMEOUT}
    return {"state": "error", "line": ERROR}


def page_data() -> str:
    """Strings the pages need, as an HTML-attribute-safe JSON blob (no inline script anywhere)."""
    blob: dict[str, Any] = {
        "tips": list(TIPS), "listening": LISTENING, "greeting": GREETING, "cta": CTA,
    }  # fmt: skip
    return html.escape(json.dumps(blob), quote=True)
