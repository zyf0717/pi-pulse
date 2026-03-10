"""H10 (heart-rate monitor) renders: value boxes and chart."""

from collections import deque

import plotly.graph_objects as go
from shiny import reactive, render, ui
from shinywidgets import output_widget, render_widget

from app.config import H10_CHARTS, H10_DEFAULTS, H10_DEVICE_OPTIONS, H10_DEVICES
from app.renders.h10_ecg_bridge import ecg_sweep_plot_id, update_ecg_sweep
from app.renders.h10_motion import motion_detail_row_svg, motion_plane_svg
from app.renders.render_utils import (
    metric_value,
    needs_chart_rebuild,
    reset_chart_state,
    sparkline_values,
)
from app.sparkline import blank_sparkline, blank_sparkline_markup, sparkline

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


def _h10_spark(
    stream_key: str | None,
    latest_map: dict[str, reactive.Value],
    history_map: dict[str, deque],
    field: str,
    *,
    fmt=None,
):
    if stream_key is None:
        return blank_sparkline()
    values = sparkline_values(stream_key, H10_DEVICES, latest_map, history_map, field)
    if values is None:
        return blank_sparkline()
    return sparkline(values, fmt=fmt) if fmt else sparkline(values)


def _na_card_placeholder() -> ui.HTML:
    return ui.HTML(
        '<div style="font-size:1.75rem;font-weight:700;padding:0.5rem 0.75rem;">N/A</div>'
        + blank_sparkline_markup()
    )


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


def _motion_trail_points(
    stream_key: str | None,
    h10_motion_latest: dict[str, reactive.Value],
) -> list[tuple[float, ...]] | None:
    if stream_key is None:
        return None
    frame = h10_motion_latest[stream_key]()
    trail_points = frame.get("trail_points", [])
    if not trail_points:
        return None
    return trail_points


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
    field = _H10_FIELDS[chart]
    h10_widget.data[0].x = times
    h10_widget.data[0].y = [row.get(field, 0.0) for row in data_rows]


def register_h10_renders(
    input,
    h10_latest: dict[str, reactive.Value],
    h10_history: dict[str, deque],
    h10_ecg_latest: dict[str, reactive.Value],
    h10_ecg_samples: dict[str, deque],
    h10_ecg_chunks: dict[str, deque],
    h10_acc_latest: dict[str, reactive.Value],
    h10_acc_history: dict[str, deque],
    h10_motion_latest: dict[str, reactive.Value],
    plotly_tpl,
    h10_widget: go.FigureWidget,
    h10_state: dict,
    session=None,
) -> None:
    """Register all H10-tab output renders inside the active Shiny session."""
    ecg_sweep_state: dict[str, str | int | None] = {
        "chart": None,
        "stream": None,
        "tpl": None,
        "sent_total": 0,
        "plot_id": None,
    }

    @render.ui
    def h10_device_selector():
        node_key = input.device()
        options = H10_DEVICE_OPTIONS.get(node_key, {})
        if not options:
            return ui.HTML("")
        selected = _selected_h10_stream(input)
        return ui.input_select(
            "h10_device",
            "",
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
            return blank_sparkline()
        h10_ecg_latest[stream_key]()  # establish reactive dependency
        samples = list(h10_ecg_samples[stream_key])
        if not samples:
            return blank_sparkline()
        return sparkline(samples, fmt=lambda v: f"{v:.0f} µV")

    @render.ui
    def h10_motion_preview():
        trail_points = _motion_trail_points(_selected_h10_stream(input), h10_motion_latest)
        if trail_points is None:
            return _na_card_placeholder()
        return ui.HTML(
            motion_plane_svg(
                trail_points,
                axes=(0, 1),
                axis_names=("X", "Y"),
                detail=False,
            )
        )

    @render.ui
    def h10_detail_view():
        stream_key = _selected_h10_stream(input)
        if input.h10_chart() == "motion":
            trail_points = _motion_trail_points(stream_key, h10_motion_latest)
            if trail_points is None:
                return ui.HTML("N/A")
            return ui.HTML(motion_detail_row_svg(trail_points))
        if input.h10_chart() == "ecg":
            if stream_key is None:
                return ui.HTML("")
            return ui.div(
                id=ecg_sweep_plot_id(stream_key),
                style="width:100%; height:400px;",
            )
        return output_widget("h10_graph")

    @reactive.Effect
    def _update_h10_chart():
        stream_key = _selected_h10_stream(input)
        chart = input.h10_chart()
        tpl = plotly_tpl()

        if stream_key is None:
            _reset_h10_chart(h10_widget, h10_state)
            return

        if chart in {"motion", "ecg"}:
            return
        if chart == "acc_dyn":
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

    @reactive.Effect
    def _update_h10_ecg_sweep():
        stream_key = _selected_h10_stream(input)
        update_ecg_sweep(
            session,
            ecg_sweep_state,
            chart=input.h10_chart(),
            stream_key=stream_key,
            template=plotly_tpl(),
            ecg_meta=h10_ecg_latest[stream_key]() if stream_key is not None else None,
            ecg_samples=h10_ecg_samples.get(stream_key, ()),
            ecg_chunks=h10_ecg_chunks.get(stream_key, ()),
            title=H10_CHARTS["ecg"],
        )

    @render_widget
    def h10_graph():
        return h10_widget
