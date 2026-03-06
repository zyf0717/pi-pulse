"""Motion SVG helpers for the H10 acceleration views."""

_TILT_AXIS_LIMIT_MG = 1500.0


def _motion_axis_value(
    point: tuple[float, ...] | list[float], axis_index: int
) -> float:
    if axis_index >= len(point):
        return 0.0
    value = point[axis_index]
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    return 0.0


def motion_plane_svg(
    trail_points: list[tuple[float, ...]],
    *,
    axes: tuple[int, int],
    axis_names: tuple[str, str],
    detail: bool,
) -> str:
    width = 240 if detail else 160
    height = 240 if detail else 96
    center_x = width / 2
    center_y = height / 2
    pad_x = 32 if detail else 14
    pad_y = 32 if detail else 12
    max_component = _TILT_AXIS_LIMIT_MG
    span_x = max(1.0, center_x - pad_x)
    span_y = max(1.0, center_y - pad_y)
    x_name, y_name = axis_names

    def _project(point: tuple[float, ...]) -> tuple[float, float]:
        x_mg = _motion_axis_value(point, axes[0])
        y_mg = _motion_axis_value(point, axes[1])
        x = center_x + (x_mg / max_component) * span_x
        y = center_y - (y_mg / max_component) * span_y
        return x, y

    polyline = ""
    head = ""
    if len(trail_points) >= 2:
        pts = " ".join(
            f"{x:.1f},{y:.1f}" for x, y in (_project(point) for point in trail_points)
        )
        polyline = (
            f'<polyline points="{pts}" fill="none" stroke="#64b5f6" '
            f'stroke-width="{"3" if detail else "2"}" '
            'stroke-linejoin="round" stroke-linecap="round" />'
        )
    if trail_points:
        head_x, head_y = _project(trail_points[-1])
        head = (
            f'<circle cx="{head_x:.1f}" cy="{head_y:.1f}" r="{"4.5" if detail else "3"}" '
            'fill="#64b5f6" />'
        )

    tick_marks = ""
    tick_labels = ""
    if detail:
        labels = ""
    else:
        labels = (
            f'<text x="{width - 10:.1f}" y="{center_y - 6:.1f}" text-anchor="end" fill="#9e9e9e" font-size="10">{x_name}</text>'
            f'<text x="{center_x + 6:.1f}" y="{14:.1f}" fill="#9e9e9e" font-size="10">{y_name}</text>'
        )
    if detail:
        latest_x = (
            _motion_axis_value(trail_points[-1], axes[0]) if trail_points else 0.0
        )
        latest_y = (
            _motion_axis_value(trail_points[-1], axes[1]) if trail_points else 0.0
        )
        detail_font_size = "5.5"
        axis_end_gap = 8
        tick_size = 6
        tick_values = (
            -_TILT_AXIS_LIMIT_MG,
            -1000.0,
            -500.0,
            500.0,
            1000.0,
            _TILT_AXIS_LIMIT_MG,
        )
        for tick_value in tick_values:
            tick_x = center_x + (tick_value / max_component) * span_x
            tick_y = center_y - (tick_value / max_component) * span_y
            tick_marks += (
                f'<line x1="{tick_x:.1f}" y1="{center_y - tick_size:.1f}" '
                f'x2="{tick_x:.1f}" y2="{center_y + tick_size:.1f}" '
                'stroke="#7a7f85" stroke-width="1" />'
            )
            tick_marks += (
                f'<line x1="{center_x - tick_size:.1f}" y1="{tick_y:.1f}" '
                f'x2="{center_x + tick_size:.1f}" y2="{tick_y:.1f}" '
                'stroke="#7a7f85" stroke-width="1" />'
            )
            if abs(tick_value) == _TILT_AXIS_LIMIT_MG:
                tick_label = f"{tick_value:+.0f}"
                tick_labels += (
                    f'<text x="{tick_x:.1f}" y="{center_y + 12:.1f}" text-anchor="middle" '
                    f'fill="#9e9e9e" font-size="{detail_font_size}">'
                    f"{tick_label}</text>"
                )
                tick_labels += (
                    f'<text x="{center_x - 8:.1f}" y="{tick_y + 2:.1f}" text-anchor="end" '
                    f'fill="#9e9e9e" font-size="{detail_font_size}">'
                    f"{tick_label}</text>"
                )
        labels += (
            f'<text x="{12:.1f}" y="{12:.1f}" fill="#9e9e9e" font-size="{detail_font_size}">'
            f"{x_name}: {latest_x:+.0f} mg</text>"
            f'<text x="{12:.1f}" y="{20:.1f}" fill="#9e9e9e" font-size="{detail_font_size}">'
            f"{y_name}: {latest_y:+.0f} mg</text>"
            f'<text x="{width - pad_x + axis_end_gap:.1f}" y="{center_y:.1f}" dominant-baseline="middle" fill="#9e9e9e" font-size="{detail_font_size}">{x_name}</text>'
            f'<text x="{center_x:.1f}" y="{pad_y - axis_end_gap:.1f}" text-anchor="middle" dominant-baseline="middle" fill="#9e9e9e" font-size="{detail_font_size}">{y_name}</text>'
        )

    svg_height = "100%" if detail else str(height)
    return (
        f'<svg viewBox="0 0 {width} {height}" width="100%" height="{svg_height}" '
        'preserveAspectRatio="xMidYMid meet" '
        'xmlns="http://www.w3.org/2000/svg" style="display:block">'
        f'<line x1="{pad_x:.1f}" y1="{center_y:.1f}" x2="{width - pad_x:.1f}" y2="{center_y:.1f}" '
        'stroke="#5f6368" stroke-width="1" />'
        f'<line x1="{center_x:.1f}" y1="{pad_y:.1f}" x2="{center_x:.1f}" y2="{height - pad_y:.1f}" '
        'stroke="#5f6368" stroke-width="1" />'
        + tick_marks
        + polyline
        + head
        + tick_labels
        + labels
        + "</svg>"
    )


def motion_detail_row_svg(trail_points: list[tuple[float, ...]]) -> str:
    panels = []
    for axes, axis_names in (
        ((0, 1), ("X", "Y")),
        ((0, 2), ("X", "Z")),
        ((1, 2), ("Y", "Z")),
    ):
        panels.append(
            '<div style="flex:1 1 0; min-width:0; height:100%;">'
            + motion_plane_svg(
                trail_points,
                axes=axes,
                axis_names=axis_names,
                detail=True,
            )
            + "</div>"
        )
    return (
        '<div style="display:flex; gap:0.75rem; align-items:stretch; height:100%; min-height:0;">'
        + "".join(panels)
        + "</div>"
    )
