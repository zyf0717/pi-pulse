"""H10 (heart-rate monitor) renders: value boxes and chart."""

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

_H10_FIELDS = {"bpm": "heart_rate_bpm", "rr": "rr_last_ms"}
_ECG_Y_RANGE = [-2000, 2500]


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
        h10_widget.layout.xaxis = {}
    elif chart == "rr":
        h10_widget.layout.yaxis = dict(title="ms")
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
    def h10_rr_last_val():
        return metric_value(
            input.device(),
            H10_DEVICES,
            h10_latest,
            "rr_last_ms",
            lambda value: f"{value:.0f} ms",
        )

    @render.text
    def h10_ecg_val():
        dev = input.device()
        if dev not in H10_DEVICES:
            return "N/A"
        ecg_chunk = h10_ecg_latest[dev]()
        if not h10_ecg_samples[dev]:
            return "N/A"
        sample_rate_hz = ecg_chunk.get("sample_rate_hz", 130)
        return f"{sample_rate_hz:.0f} Hz"

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
    def h10_rr_last_spark():
        return _h10_spark(
            input.device(),
            h10_latest,
            h10_history,
            "rr_last_ms",
            fmt=lambda value: f"{value:.0f} ms",
        )

    @render.ui
    def h10_ecg_spark():
        dev = input.device()
        if dev not in H10_DEVICES:
            return ui.HTML("")
        h10_ecg_latest[dev]()  # establish reactive dependency
        samples = list(h10_ecg_samples[dev])
        if not samples:
            return ui.HTML("")
        return sparkline(samples, fmt=lambda v: f"{v:.0f} µV")

    @reactive.Effect
    def _update_h10_chart():
        dev = input.device()
        chart = input.h10_chart()
        tpl = plotly_tpl()

        if dev not in H10_DEVICES:
            _reset_h10_chart(h10_widget, h10_state)
            return

        if chart == "ecg":
            ecg_chunk = h10_ecg_latest[dev]()
            samples = list(h10_ecg_samples[dev])
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
        else:
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

    @render_widget
    def h10_graph():
        return h10_widget
