"""Pulse (system metrics) renders: value boxes, sparklines, and chart."""

from collections import deque

import plotly.graph_objects as go
from shiny import reactive, render, ui
from shinywidgets import render_widget

from config import DEVICES, PULSE_CHARTS
from renders.render_utils import (
    metric_value,
    needs_chart_rebuild,
    reset_chart_state,
    sparkline_values,
)
from sparkline import sparkline

_PULSE_FIELDS = {
    "cpu": "cpu",
    "mem": "mem",
    "temp": "temp",
    "cpu_freq": "cpu_freq_avg_mhz",
}


def _pulse_spark(
    device: str,
    pulse_latest: dict[str, reactive.Value],
    pulse_temp_history: dict[str, deque],
    field: str,
    *,
    scale: float = 1.0,
    fmt=None,
):
    values = sparkline_values(
        device,
        DEVICES,
        pulse_latest,
        pulse_temp_history,
        field,
        scale=scale,
    )
    if values is None:
        return ui.HTML("")
    return sparkline(values, fmt=fmt) if fmt else sparkline(values)


def _reset_pulse_chart(pulse_widget: go.FigureWidget, pulse_state: dict) -> None:
    with pulse_widget.batch_update():
        pulse_widget.data = []
    reset_chart_state(pulse_state)


def _rebuild_pulse_chart(
    pulse_widget: go.FigureWidget,
    pulse_state: dict,
    chart: str,
    dev: str,
    tpl: str,
    times: list,
    data_rows: list[dict],
) -> None:
    pulse_widget.data = []
    if chart == "net":
        rx_data = [row.get("net_rx_bps_total", 0) / 1024 for row in data_rows]
        tx_data = [row.get("net_tx_bps_total", 0) / 1024 for row in data_rows]
        pulse_widget.add_scatter(
            x=times, y=rx_data, mode="lines+markers", name="Download (KB/s)"
        )
        pulse_widget.add_scatter(
            x=times, y=tx_data, mode="lines+markers", name="Upload (KB/s)"
        )
        pulse_widget.layout.template = tpl
        pulse_widget.layout.margin = dict(l=20, r=20, t=20, b=20)
        pulse_widget.layout.yaxis.title = "KB/s"
        pulse_widget.layout.legend = dict(orientation="h", y=-0.2)
    else:
        field = _PULSE_FIELDS[chart]
        y_data = [row.get(field, 0.0) for row in data_rows]
        pulse_widget.add_scatter(x=times, y=y_data, mode="lines+markers", name=PULSE_CHARTS[chart])
        pulse_widget.layout.template = tpl
        pulse_widget.layout.margin = dict(l=20, r=20, t=20, b=20)
        pulse_widget.layout.yaxis.title = PULSE_CHARTS[chart]
        pulse_widget.layout.legend = {}

    pulse_state.update({"chart": chart, "dev": dev, "tpl": tpl})


def _update_pulse_chart_data(
    pulse_widget: go.FigureWidget,
    chart: str,
    times: list,
    data_rows: list[dict],
) -> None:
    if chart == "net":
        rx_data = [row.get("net_rx_bps_total", 0) / 1024 for row in data_rows]
        tx_data = [row.get("net_tx_bps_total", 0) / 1024 for row in data_rows]
        pulse_widget.data[0].x = times
        pulse_widget.data[0].y = rx_data
        pulse_widget.data[1].x = times
        pulse_widget.data[1].y = tx_data
        return

    field = _PULSE_FIELDS[chart]
    pulse_widget.data[0].x = times
    pulse_widget.data[0].y = [row.get(field, 0.0) for row in data_rows]


def register_pulse_renders(
    input,
    pulse_latest: dict[str, reactive.Value],
    pulse_temp_history: dict[str, deque],
    plotly_tpl,
    pulse_widget: go.FigureWidget,
    pulse_state: dict,
) -> None:
    """Register all pulse-tab output renders inside the active Shiny session."""

    # ── Value boxes ───────────────────────────────────────────────────────────
    @render.text
    def cpu_val():
        return metric_value(
            input.device(), DEVICES, pulse_latest, "cpu", lambda value: f"{value:.1f}%"
        )

    @render.text
    def mem_val():
        return metric_value(
            input.device(), DEVICES, pulse_latest, "mem", lambda value: f"{value:.1f}%"
        )

    @render.text
    def temp_val():
        return metric_value(
            input.device(), DEVICES, pulse_latest, "temp", lambda value: f"{value:.1f}°C"
        )

    @render.text
    def cpu_freq_val():
        return metric_value(
            input.device(),
            DEVICES,
            pulse_latest,
            "cpu_freq_avg_mhz",
            lambda value: f"{value:.0f} MHz",
        )

    @render.text
    def net_rx_val():
        return metric_value(
            input.device(),
            DEVICES,
            pulse_latest,
            "net_rx_bps_total",
            lambda value: f"{value / 1024:.1f} KB/s",
        )

    @render.text
    def net_tx_val():
        return metric_value(
            input.device(),
            DEVICES,
            pulse_latest,
            "net_tx_bps_total",
            lambda value: f"{value / 1024:.1f} KB/s",
        )

    @render.ui
    def cpu_spark():
        return _pulse_spark(
            input.device(), pulse_latest, pulse_temp_history, "cpu", fmt=lambda value: f"{value:.1f}%"
        )

    @render.ui
    def cpu_freq_spark():
        return _pulse_spark(
            input.device(),
            pulse_latest,
            pulse_temp_history,
            "cpu_freq_avg_mhz",
            fmt=lambda value: f"{value:.0f} MHz",
        )

    @render.ui
    def mem_spark():
        return _pulse_spark(
            input.device(), pulse_latest, pulse_temp_history, "mem", fmt=lambda value: f"{value:.1f}%"
        )

    @render.ui
    def temp_spark():
        return _pulse_spark(
            input.device(), pulse_latest, pulse_temp_history, "temp", fmt=lambda value: f"{value:.1f}°C"
        )

    @render.ui
    def net_rx_spark():
        return _pulse_spark(
            input.device(),
            pulse_latest,
            pulse_temp_history,
            "net_rx_bps_total",
            scale=1 / 1024,
            fmt=lambda value: f"{value:.1f} KB/s",
        )

    @render.ui
    def net_tx_spark():
        return _pulse_spark(
            input.device(),
            pulse_latest,
            pulse_temp_history,
            "net_tx_bps_total",
            scale=1 / 1024,
            fmt=lambda value: f"{value:.1f} KB/s",
        )

    # ── Chart ─────────────────────────────────────────────────────────────────
    @render_widget
    def temp_graph():
        return pulse_widget

    @reactive.Effect
    def _update_pulse_chart():
        dev = input.device()
        chart = input.pulse_chart()
        tpl = plotly_tpl()

        if dev not in DEVICES:
            _reset_pulse_chart(pulse_widget, pulse_state)
            return

        pulse_latest[dev]()
        history = list(pulse_temp_history[dev])
        if not history:
            return

        times = [t for t, _ in history]
        data_rows = [d for _, d in history]
        rebuild = needs_chart_rebuild(pulse_state, chart, dev, tpl)
        with pulse_widget.batch_update():
            if rebuild:
                _rebuild_pulse_chart(
                    pulse_widget, pulse_state, chart, dev, tpl, times, data_rows
                )
            else:
                _update_pulse_chart_data(pulse_widget, chart, times, data_rows)
