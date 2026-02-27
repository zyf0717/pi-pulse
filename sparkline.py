"""Minimal SVG sparkline rendered as a Shiny UI element."""

from collections.abc import Callable

from shiny import ui

_COLOR = "#64b5f6"
_VBOX_W = 120  # internal SVG coordinate width
_HEIGHT = 34
_STROKE = 1.5
_LABEL_COLOR = "#9e9e9e"


def _default_fmt(v: float) -> str:
    return f"{v:.0f}" if v == int(v) else f"{v:.1f}"


def sparkline(
    values: list[float],
    *,
    height: int = _HEIGHT,
    color: str = _COLOR,
    stroke: float = _STROKE,
    fmt: Callable[[float], str] = _default_fmt,
) -> ui.HTML:
    """Return a full-width SVG sparkline with stacked max/min on the right."""
    if len(values) < 2:
        return ui.HTML("")

    lo, hi = min(values), max(values)
    span = hi - lo or 1.0
    n = len(values)
    pad = stroke
    inner_w = _VBOX_W - 2 * pad
    inner_h = height - 2 * pad

    xs = [pad + i * inner_w / (n - 1) for i in range(n)]
    ys = [pad + inner_h - (v - lo) / span * inner_h for v in values]

    pts = " ".join(f"{x:.1f},{y:.1f}" for x, y in zip(xs, ys))
    svg = (
        f'<svg width="100%" height="{height}" '
        f'viewBox="0 0 {_VBOX_W} {height}" '
        f'preserveAspectRatio="none" '
        f'xmlns="http://www.w3.org/2000/svg" '
        f'style="display:block;flex:1 1 0;min-width:0">'
        f'<polyline points="{pts}" fill="none" '
        f'stroke="{color}" stroke-width="{stroke}" '
        f'stroke-linejoin="round" stroke-linecap="round"/>'
        f"</svg>"
    )
    stats = (
        f'<div style="'
        f"display:flex;flex-direction:column;justify-content:space-between;"
        f"height:{height}px;"
        f"font-size:0.7rem;line-height:1;text-align:right;"
        f"color:{_LABEL_COLOR};white-space:nowrap;flex-shrink:0;"
        f'font-variant-numeric:tabular-nums">'
        f"<div>{fmt(hi)}</div>"
        f"<div>{fmt(lo)}</div>"
        f"</div>"
    )
    wrapper = (
        f'<div style="display:flex;align-items:stretch;'
        f'padding:0 0.75rem 0.5rem;gap:6px">'
        f"{svg}{stats}</div>"
    )
    return ui.HTML(wrapper)
