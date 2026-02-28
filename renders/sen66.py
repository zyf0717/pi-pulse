"""SEN66 (environmental sensor) renders: value boxes, sparklines, and chart."""

from collections import deque

import plotly.graph_objects as go
from shiny import reactive, render, ui
from shinywidgets import render_widget

from config import SEN66_DEVICES
from renders.render_utils import (
    metric_value,
    needs_chart_rebuild,
    reset_chart_state,
    sparkline_values,
)
from sparkline import sparkline

_NO_DATA_ANNOTATION = dict(
    text="No SEN66 data is available for this device.",
    x=0.5,
    y=0.5,
    xref="paper",
    yref="paper",
    showarrow=False,
    font=dict(size=14),
)

_SEN66_TRACE_FIELDS = {
    "temp_hum": [
        ("temperature_c", "Temperature (°C)", "y1"),
        ("humidity_rh", "Humidity (%RH)", "y2"),
    ],
    "co2": [("co2_ppm", "CO₂ (ppm)", None)],
    "voc_nox": [("voc_index", "VOC Index", None), ("nox_index", "NOx Index", None)],
    "pm_mass": [
        ("pm1_0_ugm3", "PM1.0", None),
        ("pm2_5_ugm3", "PM2.5", None),
        ("pm4_0_ugm3", "PM4.0", None),
        ("pm10_0_ugm3", "PM10", None),
    ],
    "pm_nc": [
        ("nc_pm0_5_pcm3", "NC PM0.5", None),
        ("nc_pm1_0_pcm3", "NC PM1.0", None),
        ("nc_pm2_5_pcm3", "NC PM2.5", None),
        ("nc_pm4_0_pcm3", "NC PM4.0", None),
        ("nc_pm10_0_pcm3", "NC PM10", None),
    ],
}


def _sen66_spark(
    device: str,
    sen66_latest: dict[str, reactive.Value],
    sen66_history: dict[str, deque],
    field: str,
    *,
    fmt=None,
):
    values = sparkline_values(device, SEN66_DEVICES, sen66_latest, sen66_history, field)
    if values is None:
        return ui.HTML("")
    return sparkline(values, fmt=fmt) if fmt else sparkline(values)


def _reset_sen66_chart(sen66_widget: go.FigureWidget, sen66_state: dict) -> None:
    with sen66_widget.batch_update():
        sen66_widget.data = []
        sen66_widget.layout.annotations = [_NO_DATA_ANNOTATION]
    reset_chart_state(sen66_state)


def _apply_sen66_layout(sen66_widget: go.FigureWidget, chart: str, tpl: str) -> None:
    sen66_widget.layout.annotations = []
    sen66_widget.layout.template = tpl

    if chart == "temp_hum":
        sen66_widget.layout.yaxis = dict(title="Temperature (°C)")
        sen66_widget.layout.yaxis2 = dict(
            title="Humidity (%RH)", overlaying="y", side="right"
        )
        sen66_widget.layout.legend = dict(orientation="h", y=-0.2)
        sen66_widget.layout.margin = dict(l=20, r=60, t=20, b=20)
    elif chart == "co2":
        sen66_widget.layout.yaxis = dict(title="CO₂ (ppm)")
        sen66_widget.layout.yaxis2 = {}
        sen66_widget.layout.legend = {}
        sen66_widget.layout.margin = dict(l=20, r=20, t=20, b=20)
    elif chart == "voc_nox":
        sen66_widget.layout.yaxis = dict(title="Index")
        sen66_widget.layout.yaxis2 = {}
        sen66_widget.layout.legend = {}
        sen66_widget.layout.margin = dict(l=20, r=20, t=20, b=20)
    elif chart == "pm_mass":
        sen66_widget.layout.yaxis = dict(title="µg/m³")
        sen66_widget.layout.yaxis2 = {}
        sen66_widget.layout.legend = {}
        sen66_widget.layout.margin = dict(l=20, r=20, t=20, b=20)
    elif chart == "pm_nc":
        sen66_widget.layout.yaxis = dict(title="#/cm³")
        sen66_widget.layout.yaxis2 = {}
        sen66_widget.layout.legend = {}
        sen66_widget.layout.margin = dict(l=20, r=20, t=20, b=20)


def _rebuild_sen66_chart(
    sen66_widget: go.FigureWidget,
    sen66_state: dict,
    chart: str,
    dev: str,
    tpl: str,
    times: list,
    data_rows: list[dict],
) -> None:
    sen66_widget.data = []
    _apply_sen66_layout(sen66_widget, chart, tpl)

    for field, name, yaxis in _SEN66_TRACE_FIELDS[chart]:
        scatter_kwargs = {
            "x": times,
            "y": [row[field] for row in data_rows],
            "name": name,
            "mode": "lines+markers",
        }
        if yaxis is not None:
            scatter_kwargs["yaxis"] = yaxis
        sen66_widget.add_scatter(**scatter_kwargs)

    sen66_state.update({"chart": chart, "dev": dev, "tpl": tpl})


def _update_sen66_chart_data(
    sen66_widget: go.FigureWidget,
    chart: str,
    times: list,
    data_rows: list[dict],
) -> None:
    for index, (field, _, _) in enumerate(_SEN66_TRACE_FIELDS[chart]):
        sen66_widget.data[index].x = times
        sen66_widget.data[index].y = [row[field] for row in data_rows]


def register_sen66_renders(
    input,
    sen66_latest: dict[str, reactive.Value],
    sen66_nc_latest: dict[str, reactive.Value],
    sen66_history: dict[str, deque],
    sen66_nc_history: dict[str, deque],
    plotly_tpl,
    sen66_widget: go.FigureWidget,
    sen66_state: dict,
) -> None:
    """Register all SEN66-tab output renders inside the active Shiny session."""

    # ── Value boxes ───────────────────────────────────────────────────────────
    @render.text
    def sen66_temp_val():
        return metric_value(
            input.device(),
            SEN66_DEVICES,
            sen66_latest,
            "temperature_c",
            lambda value: f"{value:.2f}°C",
        )

    @render.text
    def sen66_hum_val():
        return metric_value(
            input.device(),
            SEN66_DEVICES,
            sen66_latest,
            "humidity_rh",
            lambda value: f"{value:.2f}%",
        )

    @render.text
    def sen66_co2_val():
        return metric_value(
            input.device(),
            SEN66_DEVICES,
            sen66_latest,
            "co2_ppm",
            lambda value: f"{value:.0f} ppm",
        )

    @render.text
    def sen66_voc_val():
        return metric_value(
            input.device(),
            SEN66_DEVICES,
            sen66_latest,
            "voc_index",
            lambda value: f"{value:.1f}",
        )

    @render.text
    def sen66_nox_val():
        return metric_value(
            input.device(),
            SEN66_DEVICES,
            sen66_latest,
            "nox_index",
            lambda value: f"{value:.1f}",
        )

    @render.ui
    def sen66_temp_spark():
        return _sen66_spark(
            input.device(), sen66_latest, sen66_history, "temperature_c", fmt=lambda value: f"{value:.2f}°C"
        )

    @render.ui
    def sen66_hum_spark():
        return _sen66_spark(
            input.device(), sen66_latest, sen66_history, "humidity_rh", fmt=lambda value: f"{value:.1f}%"
        )

    @render.ui
    def sen66_co2_spark():
        return _sen66_spark(
            input.device(), sen66_latest, sen66_history, "co2_ppm", fmt=lambda value: f"{value:.0f} ppm"
        )

    @render.ui
    def sen66_voc_spark():
        return _sen66_spark(
            input.device(), sen66_latest, sen66_history, "voc_index", fmt=lambda value: f"{value:.1f}"
        )

    @render.ui
    def sen66_nox_spark():
        return _sen66_spark(
            input.device(), sen66_latest, sen66_history, "nox_index", fmt=lambda value: f"{value:.1f}"
        )

    # ── Chart ─────────────────────────────────────────────────────────────────
    @render_widget
    def sen66_graph():
        return sen66_widget

    @reactive.Effect
    def _update_sen66_chart():
        dev = input.device()
        chart = input.sen66_chart()
        tpl = plotly_tpl()

        if dev not in SEN66_DEVICES:
            _reset_sen66_chart(sen66_widget, sen66_state)
            return

        if chart == "pm_nc":
            sen66_nc_latest[dev]()
            history = list(sen66_nc_history[dev])
        else:
            sen66_latest[dev]()
            history = list(sen66_history[dev])

        if not history:
            return

        times = [t for t, _ in history]
        data_rows = [d for _, d in history]

        rebuild = needs_chart_rebuild(sen66_state, chart, dev, tpl)
        with sen66_widget.batch_update():
            if rebuild:
                _rebuild_sen66_chart(
                    sen66_widget, sen66_state, chart, dev, tpl, times, data_rows
                )
            else:
                _update_sen66_chart_data(sen66_widget, chart, times, data_rows)
