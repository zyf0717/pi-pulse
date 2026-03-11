"""Pacer renders: value cards and charts."""

from collections import deque

import plotly.graph_objects as go
from shiny import reactive, render, ui
from shinywidgets import output_widget, render_widget

from app.config import PACER_CHARTS, PACER_DEFAULTS, PACER_DEVICE_OPTIONS, PACER_DEVICES
from app.renders.h10_motion import motion_detail_row_svg, motion_plane_svg
from app.renders.render_utils import (
    metric_value,
    needs_chart_rebuild,
    reset_chart_state,
    sparkline_values,
)
from app.sparkline import blank_sparkline, blank_sparkline_markup, sparkline

_NO_DATA_ANNOTATION = dict(
    text="No pacer data is available for this device.",
    x=0.5,
    y=0.5,
    xref="paper",
    yref="paper",
    showarrow=False,
    font=dict(size=14),
)

_PACER_FIELDS = {
    "hr": "heart_rate_bpm",
    "acc_dyn": "mean_dynamic_accel_mg",
    "ppi": "ppi_ms",
}


def _selected_pacer_stream(input) -> str | None:
    node_key = input.device()
    options = PACER_DEVICE_OPTIONS.get(node_key, {})
    if not options:
        return None
    if len(options) == 1:
        return next(iter(options))

    selected_input = getattr(input, "pacer_device", None)
    try:
        selected = selected_input() if callable(selected_input) else None
    except Exception:
        selected = None
    if selected in options:
        return selected

    return PACER_DEFAULTS.get(node_key) or next(iter(options), None)


def _pacer_spark(
    stream_key: str | None,
    latest_map: dict[str, reactive.Value],
    history_map: dict[str, deque],
    field: str,
    *,
    fmt=None,
):
    if stream_key is None:
        return blank_sparkline()
    values = sparkline_values(stream_key, PACER_DEVICES, latest_map, history_map, field)
    if values is None:
        return blank_sparkline()
    return sparkline(values, fmt=fmt) if fmt else sparkline(values)


def _na_card_placeholder() -> ui.HTML:
    return ui.HTML(
        '<div style="font-size:1.75rem;font-weight:700;padding:0.5rem 0.75rem;">N/A</div>'
        + blank_sparkline_markup()
    )


def _motion_trail_points(
    stream_key: str | None,
    pacer_motion_latest: dict[str, reactive.Value],
) -> list[tuple[float, ...]] | None:
    if stream_key is None:
        return None
    frame = pacer_motion_latest[stream_key]()
    trail_points = frame.get("trail_points", [])
    if not trail_points:
        return None
    return trail_points


def _reset_pacer_chart(pacer_widget: go.FigureWidget, pacer_state: dict) -> None:
    with pacer_widget.batch_update():
        pacer_widget.data = []
        pacer_widget.layout.annotations = [_NO_DATA_ANNOTATION]
    reset_chart_state(pacer_state)


def _apply_pacer_layout(pacer_widget: go.FigureWidget, chart: str, tpl: str) -> None:
    pacer_widget.layout.annotations = []
    pacer_widget.layout.template = tpl
    pacer_widget.layout.margin = dict(l=20, r=20, t=20, b=20)
    pacer_widget.layout.legend = {}
    if chart == "hr":
        pacer_widget.layout.yaxis = dict(title="BPM")
    elif chart == "acc_dyn":
        pacer_widget.layout.yaxis = dict(title="mg")
    elif chart == "ppi":
        pacer_widget.layout.yaxis = dict(title="ms")
    pacer_widget.layout.xaxis = {}


def _rebuild_pacer_chart(
    pacer_widget: go.FigureWidget,
    pacer_state: dict,
    chart: str,
    dev: str,
    tpl: str,
    times: list,
    data_rows: list[dict],
) -> None:
    pacer_widget.data = []
    _apply_pacer_layout(pacer_widget, chart, tpl)
    field = _PACER_FIELDS[chart]
    pacer_widget.add_scatter(
        x=times,
        y=[row.get(field, 0.0) for row in data_rows],
        mode="lines+markers",
        name=PACER_CHARTS[chart],
    )
    pacer_state.update({"chart": chart, "dev": dev, "tpl": tpl})


def _update_pacer_chart_data(
    pacer_widget: go.FigureWidget,
    chart: str,
    times: list,
    data_rows: list[dict],
) -> None:
    field = _PACER_FIELDS[chart]
    pacer_widget.data[0].x = times
    pacer_widget.data[0].y = [row.get(field, 0.0) for row in data_rows]


def register_pacer_renders(
    input,
    pacer_hr_latest: dict[str, reactive.Value],
    pacer_hr_history: dict[str, deque],
    pacer_acc_latest: dict[str, reactive.Value],
    pacer_acc_history: dict[str, deque],
    pacer_motion_latest: dict[str, reactive.Value],
    pacer_ppi_latest: dict[str, reactive.Value],
    pacer_ppi_history: dict[str, deque],
    plotly_tpl,
    pacer_widget: go.FigureWidget,
    pacer_state: dict,
) -> None:
    """Register all Pacer-tab output renders inside the active Shiny session."""

    @render.ui
    def pacer_device_selector():
        node_key = input.device()
        options = PACER_DEVICE_OPTIONS.get(node_key, {})
        if not options:
            return ui.HTML("")
        return ui.input_select(
            "pacer_device",
            "",
            options,
            selected=_selected_pacer_stream(input),
        )

    @render.text
    def pacer_hr_val():
        stream_key = _selected_pacer_stream(input)
        if stream_key is None:
            return "N/A"
        return metric_value(
            stream_key,
            PACER_DEVICES,
            pacer_hr_latest,
            "heart_rate_bpm",
            lambda value: f"{value:.0f} bpm",
        )

    @render.text
    def pacer_acc_val():
        stream_key = _selected_pacer_stream(input)
        if stream_key is None:
            return "N/A"
        return metric_value(
            stream_key,
            PACER_DEVICES,
            pacer_acc_latest,
            "mean_dynamic_accel_mg",
            lambda value: f"{value:.0f} mg",
        )

    @render.text
    def pacer_ppi_val():
        stream_key = _selected_pacer_stream(input)
        if stream_key is None:
            return "N/A"
        return metric_value(
            stream_key,
            PACER_DEVICES,
            pacer_ppi_latest,
            "ppi_ms",
            lambda value: f"{value:.0f} ms",
        )

    @render.ui
    def pacer_hr_spark():
        return _pacer_spark(
            _selected_pacer_stream(input),
            pacer_hr_latest,
            pacer_hr_history,
            "heart_rate_bpm",
            fmt=lambda value: f"{value:.0f} bpm",
        )

    @render.ui
    def pacer_acc_spark():
        return _pacer_spark(
            _selected_pacer_stream(input),
            pacer_acc_latest,
            pacer_acc_history,
            "mean_dynamic_accel_mg",
            fmt=lambda value: f"{value:.0f} mg",
        )

    @render.ui
    def pacer_ppi_spark():
        return _pacer_spark(
            _selected_pacer_stream(input),
            pacer_ppi_latest,
            pacer_ppi_history,
            "ppi_ms",
            fmt=lambda value: f"{value:.0f} ms",
        )

    @render.ui
    def pacer_motion_preview():
        trail_points = _motion_trail_points(_selected_pacer_stream(input), pacer_motion_latest)
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
    def pacer_detail_view():
        stream_key = _selected_pacer_stream(input)
        if input.pacer_chart() == "motion":
            trail_points = _motion_trail_points(stream_key, pacer_motion_latest)
            if trail_points is None:
                return ui.HTML("N/A")
            return ui.HTML(motion_detail_row_svg(trail_points))
        return output_widget("pacer_graph")

    @reactive.Effect
    def _update_pacer_chart():
        stream_key = _selected_pacer_stream(input)
        chart = input.pacer_chart()
        tpl = plotly_tpl()

        if stream_key is None:
            _reset_pacer_chart(pacer_widget, pacer_state)
            return

        if chart == "motion":
            return
        if chart == "hr":
            pacer_hr_latest[stream_key]()
            history = list(pacer_hr_history[stream_key])
        elif chart == "acc_dyn":
            pacer_acc_latest[stream_key]()
            history = list(pacer_acc_history[stream_key])
        else:
            pacer_ppi_latest[stream_key]()
            history = list(pacer_ppi_history[stream_key])
        if not history:
            return

        times = [t for t, _ in history]
        data_rows = [d for _, d in history]
        rebuild = needs_chart_rebuild(pacer_state, chart, stream_key, tpl)
        with pacer_widget.batch_update():
            if rebuild:
                _rebuild_pacer_chart(
                    pacer_widget, pacer_state, chart, stream_key, tpl, times, data_rows
                )
            else:
                _update_pacer_chart_data(pacer_widget, chart, times, data_rows)

    @render_widget
    def pacer_graph():
        return pacer_widget
