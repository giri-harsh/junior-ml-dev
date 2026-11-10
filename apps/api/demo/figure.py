"""The 3D hero figure as plain HTML: six stacked 6x6 grids that CSS rotates, bobs and scans.

Generated once at build/start time (no JS, no images). The top layer is "the model"; the lower five
are the data going in. Lit-cell patterns are deterministic so the page is reproducible.
"""

from __future__ import annotations

LAYERS = 6
GRID = 6


def _lit(layer: int, row: int, col: int) -> bool:
    if layer == LAYERS - 1:
        return (row * 2 + col * 3 + 1) % 4 == 0
    return (row * 3 + col * 5 + layer * 2) % 7 == 0


def figure_html(labels: str = "", mini: bool = False) -> str:
    """`labels` is trusted markup placed beside the stage (the four floating captions)."""
    layers = []
    for i in range(LAYERS):
        cells = "".join(
            '<i class="o"></i>' if _lit(i, r, c) else "<i></i>"
            for r in range(GRID)
            for c in range(GRID)
        )
        top = " top" if i == LAYERS - 1 else ""
        layers.append(f'<div class="ly{top}" style="--i:{i}">{cells}</div>')
    return (
        f'<div class="fig{" mini" if mini else ""}" aria-hidden="true">'
        '<div class="fs"><div class="bob"><div class="stage">'
        '<div class="ring"></div>'
        + "".join(layers)
        + '<div class="scan"></div></div></div>'
        + labels
        + "</div></div>"
    )
