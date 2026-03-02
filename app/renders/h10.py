"""H10 (heart-rate monitor) renders: value boxes, sparklines, chart, and payload."""

import json
from collections import deque

import plotly.graph_objects as go
from shiny import reactive, render, ui
from shinywidgets import render_widget

from app.config import H10_CHARTS, H10_DEVICES
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
    "rr": "rr_avg_ms",
}


def _h10_spark(
    device: str,
    h10_latest: dict[str, reactive.Value],
    h10_history: dict[str, deque],
    field: str,
    *,
    fmt=None,
):
    values = sparkline_values(device, H10_DEVICES, h10_latest, h10_history, field)
    if values is None:
        return ui.HTML("")
    return sparkline(values, fmt=fmt) if fmt else sparkline(values)


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
    else:
        h10_widget.layout.yaxis = dict(title="ms")


def _rebuild_h10_chart(
    h10_widget: go.FigureWidget,
    h10_state: dict,
    chart: str,
    dev: str,
    tpl: str,
    times: list,
    data_rows: list[dict],
) -> None:
    field = _H10_FIELDS[chart]
    h10_widget.data = []
    _apply_h10_layout(h10_widget, chart, tpl)
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
    plotly_tpl,
    h10_widget: go.FigureWidget,
    h10_state: dict,
) -> None:
    """Register all H10-tab output renders inside the active Shiny session."""

    @render.text
    def h10_bpm_val():
        return metric_value(
            input.device(),
            H10_DEVICES,
            h10_latest,
            "heart_rate_bpm",
            lambda value: f"{value:.0f} bpm",
        )

    @render.text
    def h10_rr_avg_val():
        return metric_value(
            input.device(),
            H10_DEVICES,
            h10_latest,
            "rr_avg_ms",
            lambda value: f"{value:.0f} ms",
        )

    @render.text
    def h10_rr_last_val():
        return metric_value(
            input.device(),
            H10_DEVICES,
            h10_latest,
            "rr_last_ms",
            lambda value: f"{value:.0f} ms",
        )

    @render.text
    def h10_rr_count_val():
        return metric_value(
            input.device(),
            H10_DEVICES,
            h10_latest,
            "rr_count",
            lambda value: f"{value:.0f}",
        )

    @render.text
    def h10_payload():
        dev = input.device()
        if dev not in H10_DEVICES:
            return "No H10 device configured for the selected host."
        return json.dumps(h10_latest[dev](), sort_keys=True, default=str)

    @render.ui
    def h10_bpm_spark():
        return _h10_spark(
            input.device(),
            h10_latest,
            h10_history,
            "heart_rate_bpm",
            fmt=lambda value: f"{value:.0f} bpm",
        )

    @render.ui
    def h10_rr_avg_spark():
        return _h10_spark(
            input.device(),
            h10_latest,
            h10_history,
            "rr_avg_ms",
            fmt=lambda value: f"{value:.0f} ms",
        )

    @render.ui
    def h10_rr_last_spark():
        return _h10_spark(
            input.device(),
            h10_latest,
            h10_history,
            "rr_last_ms",
            fmt=lambda value: f"{value:.0f} ms",
        )

    @render.ui
    def h10_rr_count_spark():
        return _h10_spark(
            input.device(),
            h10_latest,
            h10_history,
            "rr_count",
            fmt=lambda value: f"{value:.0f}",
        )

    @render_widget
    def h10_graph():
        return h10_widget

    @reactive.Effect
    def _update_h10_chart():
        dev = input.device()
        chart = input.h10_chart()
        tpl = plotly_tpl()

        if dev not in H10_DEVICES:
            _reset_h10_chart(h10_widget, h10_state)
            return

        h10_latest[dev]()
        history = list(h10_history[dev])
        if not history:
            return

        times = [t for t, _ in history]
        data_rows = [d for _, d in history]
        rebuild = needs_chart_rebuild(h10_state, chart, dev, tpl)
        with h10_widget.batch_update():
            if rebuild:
                _rebuild_h10_chart(
                    h10_widget, h10_state, chart, dev, tpl, times, data_rows
                )
            else:
                _update_h10_chart_data(h10_widget, chart, times, data_rows)
