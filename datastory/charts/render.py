"""Chart rendering (SVG/PNG export via vl-convert-python) (PRD S6.4)."""

from __future__ import annotations

import vl_convert as vlc  # type: ignore[import-untyped]

from datastory.charts.models import ChartSpec


def render_spec_to_svg(spec: ChartSpec) -> str:
    """Render Vega-Lite spec to SVG (PRD S6.4).
    
    Returns SVG string. Raises if the spec is invalid or exceeds 500 KB (PRD acceptance).
    """
    if spec.size_kb() > 500:
        raise ValueError(f"Chart spec exceeds 500 KB: {spec.size_kb():.1f} KB")

    svg_str: str = vlc.vegalite_to_svg(spec.spec)
    return svg_str


def render_spec_to_png(spec: ChartSpec, scale: float = 2.0) -> bytes:
    """Render Vega-Lite spec to PNG (PRD S6.4).
    
    Returns PNG bytes. Scale factor for retina displays.
    """
    if spec.size_kb() > 500:
        raise ValueError(f"Chart spec exceeds 500 KB: {spec.size_kb():.1f} KB")

    png_data: bytes = vlc.vegalite_to_png(spec.spec, scale=scale)
    return png_data
