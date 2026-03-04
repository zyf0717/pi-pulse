"""H10 (heart-rate monitor) renders: value boxes and chart."""

from collections import deque

import plotly.graph_objects as go
from shiny import reactive, render, ui
from shinywidgets import output_widget, render_widget

from app.config import H10_CHARTS, H10_DEFAULTS, H10_DEVICE_OPTIONS, H10_DEVICES
from app.renders.render_utils import (
    metric_value,
    needs_chart_rebuild,
    reset_chart_state,
    sparkline_values,
)
from app.sparkline import sparkline

_NO_DATA_ANNOTATION = dict(
    text="No H10 data is available for this device.",
    x=0.5,
    y=0.5,
    xref="paper",
    yref="paper",
    showarrow=False,
    font=dict(size=14),
)

_H10_FIELDS = {
    "bpm": "heart_rate_bpm",
    "rr": "rr_last_ms",
    "acc_dyn": "mean_dynamic_accel_mg",
}
_ECG_Y_RANGE = [-2000, 2500]
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


def _motion_plane_svg(
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


def _motion_detail_row_svg(trail_points: list[tuple[float, ...]]) -> str:
    panels = []
    for axes, axis_names in (
        ((0, 1), ("X", "Y")),
        ((0, 2), ("X", "Z")),
        ((1, 2), ("Y", "Z")),
    ):
        panels.append(
            '<div style="flex:1 1 0; min-width:0; height:100%;">'
            + _motion_plane_svg(
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


def _h10_spark(
    stream_key: str | None,
    latest_map: dict[str, reactive.Value],
    history_map: dict[str, deque],
    field: str,
    *,
    fmt=None,
):
    if stream_key is None:
        return ui.HTML("")
    values = sparkline_values(stream_key, H10_DEVICES, latest_map, history_map, field)
    if values is None:
        return ui.HTML("")
    return sparkline(values, fmt=fmt) if fmt else sparkline(values)


def _selected_h10_stream(input) -> str | None:
    node_key = input.device()
    options = H10_DEVICE_OPTIONS.get(node_key, {})
    if not options:
        return None
    if len(options) == 1:
        return next(iter(options))

    selected_input = getattr(input, "h10_device", None)
    try:
        selected = selected_input() if callable(selected_input) else None
    except Exception:
        selected = None
    if selected in options:
        return selected

    return H10_DEFAULTS.get(node_key) or next(iter(options), None)


def _reset_h10_chart(h10_widget: go.FigureWidget, h10_state: dict) -> None:
    with h10_widget.batch_update():
        h10_widget.data = []
        h10_widget.layout.annotations = [_NO_DATA_ANNOTATION]
    reset_chart_state(h10_state)


def _apply_h10_layout(h10_widget: go.FigureWidget, chart: str, tpl: str) -> None:
    h10_widget.layout.annotations = []
    h10_widget.layout.template = tpl
    h10_widget.layout.margin = dict(l=20, r=20, t=20, b=20)
    h10_widget.layout.legend = {}
    if chart == "bpm":
        h10_widget.layout.yaxis = dict(title="BPM")
        h10_widget.layout.xaxis = {}
    elif chart == "rr":
        h10_widget.layout.yaxis = dict(title="ms")
        h10_widget.layout.xaxis = {}
    elif chart == "acc_dyn":
        h10_widget.layout.yaxis = dict(title="mg")
        h10_widget.layout.xaxis = {}
    else:
        h10_widget.layout.yaxis = dict(
            title="µV",
            range=list(_ECG_Y_RANGE),
            fixedrange=True,
        )
        h10_widget.layout.xaxis = dict(title="Seconds")


def _rebuild_h10_chart(
    h10_widget: go.FigureWidget,
    h10_state: dict,
    chart: str,
    dev: str,
    tpl: str,
    times: list,
    data_rows: list[dict],
) -> None:
    h10_widget.data = []
    _apply_h10_layout(h10_widget, chart, tpl)
    if chart == "ecg":
        sample_rate_hz = int(data_rows[-1].get("sample_rate_hz", 130) or 130)
        y_data = list(data_rows[-1].get("samples_uv", []))
        x_data = _ecg_time_axis(len(y_data), sample_rate_hz)
        h10_widget.add_scatter(
            x=x_data,
            y=y_data,
            mode="lines",
            name=H10_CHARTS[chart],
        )
        h10_state.update({"chart": chart, "dev": dev, "tpl": tpl})
        return

    field = _H10_FIELDS[chart]
    h10_widget.add_scatter(
        x=times,
        y=[row.get(field, 0.0) for row in data_rows],
        mode="lines+markers",
        name=H10_CHARTS[chart],
    )
    h10_state.update({"chart": chart, "dev": dev, "tpl": tpl})


def _update_h10_chart_data(
    h10_widget: go.FigureWidget,
    chart: str,
    times: list,
    data_rows: list[dict],
) -> None:
    if chart == "ecg":
        sample_rate_hz = int(data_rows[-1].get("sample_rate_hz", 130) or 130)
        y_data = list(data_rows[-1].get("samples_uv", []))
        h10_widget.data[0].x = _ecg_time_axis(len(y_data), sample_rate_hz)
        h10_widget.data[0].y = y_data
        return

    field = _H10_FIELDS[chart]
    h10_widget.data[0].x = times
    h10_widget.data[0].y = [row.get(field, 0.0) for row in data_rows]


def _ecg_time_axis(sample_count: int, sample_rate_hz: int) -> list[float]:
    if sample_count <= 0:
        return []
    if sample_rate_hz <= 0:
        sample_rate_hz = 130
    end_offset = (sample_count - 1) / sample_rate_hz
    return [(index / sample_rate_hz) - end_offset for index in range(sample_count)]


def register_h10_renders(
    input,
    h10_latest: dict[str, reactive.Value],
    h10_history: dict[str, deque],
    h10_ecg_latest: dict[str, reactive.Value],
    h10_ecg_samples: dict[str, deque],
    h10_acc_latest: dict[str, reactive.Value],
    h10_acc_history: dict[str, deque],
    h10_motion_latest: dict[str, reactive.Value],
    plotly_tpl,
    h10_widget: go.FigureWidget,
    h10_state: dict,
) -> None:
    """Register all H10-tab output renders inside the active Shiny session."""

    @render.ui
    def h10_device_selector():
        node_key = input.device()
        options = H10_DEVICE_OPTIONS.get(node_key, {})
        if not options:
            return ui.HTML("")
        selected = _selected_h10_stream(input)
        return ui.input_select(
            "h10_device",
            "H10 stream:",
            options,
            selected=selected,
        )

    @render.text
    def h10_bpm_val():
        stream_key = _selected_h10_stream(input)
        if stream_key is None:
            return "N/A"
        return metric_value(
            stream_key,
            H10_DEVICES,
            h10_latest,
            "heart_rate_bpm",
            lambda value: f"{value:.0f} bpm",
        )

    @render.text
    def h10_rr_last_val():
        stream_key = _selected_h10_stream(input)
        if stream_key is None:
            return "N/A"
        return metric_value(
            stream_key,
            H10_DEVICES,
            h10_latest,
            "rr_last_ms",
            lambda value: f"{value:.0f} ms",
        )

    @render.text
    def h10_ecg_val():
        stream_key = _selected_h10_stream(input)
        if stream_key is None:
            return "N/A"
        ecg_chunk = h10_ecg_latest[stream_key]()
        if not h10_ecg_samples[stream_key]:
            return "N/A"
        sample_rate_hz = ecg_chunk.get("sample_rate_hz", 130)
        return f"{sample_rate_hz:.0f} Hz"

    @render.text
    def h10_acc_val():
        stream_key = _selected_h10_stream(input)
        if stream_key is None:
            return "N/A"
        return metric_value(
            stream_key,
            H10_DEVICES,
            h10_acc_latest,
            "mean_dynamic_accel_mg",
            lambda value: f"{value:.0f} mg",
        )

    @render.ui
    def h10_bpm_spark():
        return _h10_spark(
            _selected_h10_stream(input),
            h10_latest,
            h10_history,
            "heart_rate_bpm",
            fmt=lambda value: f"{value:.0f} bpm",
        )

    @render.ui
    def h10_rr_last_spark():
        return _h10_spark(
            _selected_h10_stream(input),
            h10_latest,
            h10_history,
            "rr_last_ms",
            fmt=lambda value: f"{value:.0f} ms",
        )

    @render.ui
    def h10_acc_spark():
        return _h10_spark(
            _selected_h10_stream(input),
            h10_acc_latest,
            h10_acc_history,
            "mean_dynamic_accel_mg",
            fmt=lambda value: f"{value:.0f} mg",
        )

    @render.ui
    def h10_ecg_spark():
        stream_key = _selected_h10_stream(input)
        if stream_key is None:
            return ui.HTML("")
        h10_ecg_latest[stream_key]()  # establish reactive dependency
        samples = list(h10_ecg_samples[stream_key])
        if not samples:
            return ui.HTML("")
        return sparkline(samples, fmt=lambda v: f"{v:.0f} µV")

    @render.ui
    def h10_motion_preview():
        stream_key = _selected_h10_stream(input)
        if stream_key is None:
            return ui.HTML("")
        frame = h10_motion_latest[stream_key]()
        return ui.HTML(
            _motion_plane_svg(
                frame.get("trail_points", []),
                axes=(0, 1),
                axis_names=("X", "Y"),
                detail=False,
            )
        )

    @render.ui
    def h10_detail_view():
        stream_key = _selected_h10_stream(input)
        if input.h10_chart() == "motion":
            if stream_key is None:
                return ui.HTML("")
            frame = h10_motion_latest[stream_key]()
            return ui.HTML(_motion_detail_row_svg(frame.get("trail_points", [])))
        return output_widget("h10_graph")

    @reactive.Effect
    def _update_h10_chart():
        stream_key = _selected_h10_stream(input)
        chart = input.h10_chart()
        tpl = plotly_tpl()

        if stream_key is None:
            _reset_h10_chart(h10_widget, h10_state)
            return

        if chart == "motion":
            return

        if chart == "ecg":
            ecg_chunk = h10_ecg_latest[stream_key]()
            samples = list(h10_ecg_samples[stream_key])
            if not samples:
                _reset_h10_chart(h10_widget, h10_state)
                return
            history = [
                (
                    None,
                    {
                        "samples_uv": samples,
                        "sample_rate_hz": ecg_chunk.get("sample_rate_hz", 130),
                    },
                )
            ]
        elif chart == "acc_dyn":
            h10_acc_latest[stream_key]()
            history = list(h10_acc_history[stream_key])
        else:
            h10_latest[stream_key]()
            history = list(h10_history[stream_key])
        if not history:
            return

        times = [t for t, _ in history]
        data_rows = [d for _, d in history]
        rebuild = needs_chart_rebuild(h10_state, chart, stream_key, tpl)
        with h10_widget.batch_update():
            if rebuild:
                _rebuild_h10_chart(
                    h10_widget, h10_state, chart, stream_key, tpl, times, data_rows
                )
            else:
                _update_h10_chart_data(h10_widget, chart, times, data_rows)

    @render_widget
    def h10_graph():
        return h10_widget
