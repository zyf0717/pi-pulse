"""Pulse (system metrics) renders: value boxes, sparklines, and chart."""

from collections import deque

import plotly.graph_objects as go
from shiny import reactive, render, ui
from shinywidgets import render_widget

from config import DEVICES, PULSE_CHARTS
from sparkline import sparkline


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
        dev = input.device()
        if dev not in DEVICES:
            return "N/A"
        return f"{pulse_latest[dev]().get('cpu', 0.0):.1f}%"

    @render.text
    def mem_val():
        dev = input.device()
        if dev not in DEVICES:
            return "N/A"
        return f"{pulse_latest[dev]().get('mem', 0.0):.1f}%"

    @render.text
    def temp_val():
        dev = input.device()
        if dev not in DEVICES:
            return "N/A"
        return f"{pulse_latest[dev]().get('temp', 0.0):.1f}°C"

    @render.text
    def cpu_freq_val():
        dev = input.device()
        if dev not in DEVICES:
            return "N/A"
        return f"{pulse_latest[dev]().get('cpu_freq_avg_mhz', 0.0):.0f} MHz"

    @render.text
    def net_rx_val():
        dev = input.device()
        if dev not in DEVICES:
            return "N/A"
        return f"{pulse_latest[dev]().get('net_rx_bps_total', 0) / 1024:.1f} KB/s"

    @render.text
    def net_tx_val():
        dev = input.device()
        if dev not in DEVICES:
            return "N/A"
        return f"{pulse_latest[dev]().get('net_tx_bps_total', 0) / 1024:.1f} KB/s"

    # ── Sparklines ────────────────────────────────────────────────────────────
    def _pulse_spark(field, scale=1.0, fmt=None):
        dev = input.device()
        if dev not in DEVICES:
            return ui.HTML("")
        pulse_latest[dev]()  # reactive dependency
        vals = [d.get(field, 0.0) * scale for _, d in pulse_temp_history[dev]]
        return sparkline(vals, fmt=fmt) if fmt else sparkline(vals)

    @render.ui
    def cpu_spark():
        return _pulse_spark("cpu", fmt=lambda v: f"{v:.1f}%")

    @render.ui
    def cpu_freq_spark():
        return _pulse_spark("cpu_freq_avg_mhz", fmt=lambda v: f"{v:.0f} MHz")

    @render.ui
    def mem_spark():
        return _pulse_spark("mem", fmt=lambda v: f"{v:.1f}%")

    @render.ui
    def temp_spark():
        return _pulse_spark("temp", fmt=lambda v: f"{v:.1f}°C")

    @render.ui
    def net_rx_spark():
        return _pulse_spark(
            "net_rx_bps_total", scale=1 / 1024, fmt=lambda v: f"{v:.1f} KB/s"
        )

    @render.ui
    def net_tx_spark():
        return _pulse_spark(
            "net_tx_bps_total", scale=1 / 1024, fmt=lambda v: f"{v:.1f} KB/s"
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
            with pulse_widget.batch_update():
                pulse_widget.data = []
            pulse_state.update({"chart": None, "dev": None, "tpl": None})
            return

        pulse_latest[dev]()
        history = list(pulse_temp_history[dev])
        if not history:
            return

        times = [t for t, _ in history]
        data_rows = [d for _, d in history]
        label = PULSE_CHARTS[chart]

        rebuild = (
            pulse_state["chart"] != chart
            or pulse_state["dev"] != dev
            or pulse_state["tpl"] != tpl
        )
        with pulse_widget.batch_update():
            if chart == "net":
                rx_data = [d.get("net_rx_bps_total", 0) / 1024 for d in data_rows]
                tx_data = [d.get("net_tx_bps_total", 0) / 1024 for d in data_rows]
                if rebuild:
                    pulse_widget.data = []
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
                    pulse_state.update({"chart": chart, "dev": dev, "tpl": tpl})
                else:
                    pulse_widget.data[0].x = times
                    pulse_widget.data[0].y = rx_data
                    pulse_widget.data[1].x = times
                    pulse_widget.data[1].y = tx_data
            else:
                field = {
                    "cpu": "cpu",
                    "mem": "mem",
                    "temp": "temp",
                    "cpu_freq": "cpu_freq_avg_mhz",
                }[chart]
                y_data = [d.get(field, 0.0) for d in data_rows]
                if rebuild:
                    pulse_widget.data = []
                    pulse_widget.add_scatter(
                        x=times, y=y_data, mode="lines+markers", name=label
                    )
                    pulse_widget.layout.template = tpl
                    pulse_widget.layout.margin = dict(l=20, r=20, t=20, b=20)
                    pulse_widget.layout.yaxis.title = label
                    pulse_widget.layout.legend = {}
                    pulse_state.update({"chart": chart, "dev": dev, "tpl": tpl})
                else:
                    pulse_widget.data[0].x = times
                    pulse_widget.data[0].y = y_data
