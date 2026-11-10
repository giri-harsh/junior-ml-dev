"""The junior ML dev: an illustrated character made of HTML boxes (no images, no canvas).

Poses are CSS keyed on `data-state` (idle, listening, working, done, error) and `data-sweat`.
The same markup appears on the landing page, the run page and the report; `avatar.js` sets the
state and the words from real events, and `avatar.css` draws everything.
"""

from __future__ import annotations

import html

LINE_WIDTHS = (62, 38, 74, 50, 28, 66, 44, 58, 34, 70, 46, 54)
LINE_COLORS = ("a", "g", "t", "a", "d", "t", "g", "a", "t", "d", "a", "g")


def _code_lines() -> str:
    """Twice the same lines, so the scrolling screen loops without a jump."""
    one = "".join(
        f'<i class="c{c}" style="width:{w}%"></i>'
        for w, c in zip(LINE_WIDTHS, LINE_COLORS, strict=True)
    )
    return one + one


def avatar_html(
    *,
    bubble: bool = True,
    small: bool = False,
    state: str = "idle",
    greet: bool = False,
    say: str = "",
) -> str:
    cls = "jd small" if small else "jd"
    bub = (
        '<div class="jd-bubble" aria-live="polite" role="status">'
        f'<span class="jd-say">{html.escape(say)}</span><a class="jd-cta" hidden></a></div>'
        if bubble
        else ""
    )
    return (
        f'<div class="{cls}" data-state="{state}"{" data-greet=1" if greet else ""}>{bub}'
        '<button class="jd-btn" type="button" aria-label="Junior ML dev — click for a tip">'
        '<span class="jd-box"><span class="jd-rig">'
        '<span class="jd-body"><i class="jd-hood"></i><i class="jd-pocket"></i>'
        '<i class="jd-cord l"></i><i class="jd-cord r"></i></span>'
        '<span class="jd-arm l"><i class="jd-hand"></i></span>'
        '<span class="jd-arm r"><i class="jd-hand"></i></span>'
        '<span class="jd-head"><i class="jd-hair"></i><i class="jd-fringe"></i>'
        '<i class="jd-ear l"></i><i class="jd-ear r"></i>'
        '<span class="jd-glass l"><i class="jd-eye"></i></span>'
        '<span class="jd-glass r"><i class="jd-eye"></i></span><i class="jd-bridge"></i>'
        '<i class="jd-cheek l"></i><i class="jd-cheek r"></i><i class="jd-mouth"></i>'
        '<i class="jd-sweat"></i></span></span>'
        '<span class="jd-lap"><span class="jd-screen"><span class="jd-code">'
        + _code_lines()
        + '</span></span><i class="jd-base"></i></span>'
        "</span></button></div>"
    )
