"""SEN66 (environmental sensor) renders: value boxes, sparklines, and chart."""

from collections import deque

import plotly.graph_objects as go
from shiny import reactive, render, ui
from shinywidgets import render_widget

from config import SEN66_DEVICES
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
        dev = input.device()
        if dev not in SEN66_DEVICES:
            return "N/A"
        return f"{sen66_latest[dev]().get('temperature_c', 0.0):.2f}°C"

    @render.text
    def sen66_hum_val():
        dev = input.device()
        if dev not in SEN66_DEVICES:
            return "N/A"
        return f"{sen66_latest[dev]().get('humidity_rh', 0.0):.2f}%"

    @render.text
    def sen66_co2_val():
        dev = input.device()
        if dev not in SEN66_DEVICES:
            return "N/A"
        return f"{sen66_latest[dev]().get('co2_ppm', 0)} ppm"

    @render.text
    def sen66_voc_val():
        dev = input.device()
        if dev not in SEN66_DEVICES:
            return "N/A"
        return f"{sen66_latest[dev]().get('voc_index', 0.0):.1f}"

    @render.text
    def sen66_nox_val():
        dev = input.device()
        if dev not in SEN66_DEVICES:
            return "N/A"
        return f"{sen66_latest[dev]().get('nox_index', 0.0):.1f}"

    # ── Sparklines ────────────────────────────────────────────────────────────
    def _sen66_spark(field, fmt=None):
        dev = input.device()
        if dev not in SEN66_DEVICES:
            return ui.HTML("")
        sen66_latest[dev]()  # reactive dependency
        vals = [d.get(field, 0.0) for _, d in sen66_history[dev]]
        return sparkline(vals, fmt=fmt) if fmt else sparkline(vals)

    @render.ui
    def sen66_temp_spark():
        return _sen66_spark("temperature_c", fmt=lambda v: f"{v:.2f}°C")

    @render.ui
    def sen66_hum_spark():
        return _sen66_spark("humidity_rh", fmt=lambda v: f"{v:.1f}%")

    @render.ui
    def sen66_co2_spark():
        return _sen66_spark("co2_ppm", fmt=lambda v: f"{v:.0f} ppm")

    @render.ui
    def sen66_voc_spark():
        return _sen66_spark("voc_index", fmt=lambda v: f"{v:.1f}")

    @render.ui
    def sen66_nox_spark():
        return _sen66_spark("nox_index", fmt=lambda v: f"{v:.1f}")

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
            with sen66_widget.batch_update():
                sen66_widget.data = []
                sen66_widget.layout.annotations = [_NO_DATA_ANNOTATION]
            sen66_state.update({"chart": None, "dev": None, "tpl": None})
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

        rebuild = (
            sen66_state["chart"] != chart
            or sen66_state["dev"] != dev
            or sen66_state["tpl"] != tpl
        )
        with sen66_widget.batch_update():
            if rebuild:
                sen66_widget.data = []
                sen66_widget.layout.annotations = []
                sen66_widget.layout.template = tpl
                sen66_state.update({"chart": chart, "dev": dev, "tpl": tpl})

                if chart == "temp_hum":
                    sen66_widget.add_scatter(
                        x=times,
                        y=[d["temperature_c"] for d in data_rows],
                        name="Temperature (°C)",
                        mode="lines+markers",
                        yaxis="y1",
                    )
                    sen66_widget.add_scatter(
                        x=times,
                        y=[d["humidity_rh"] for d in data_rows],
                        name="Humidity (%RH)",
                        mode="lines+markers",
                        yaxis="y2",
                    )
                    sen66_widget.layout.yaxis = dict(title="Temperature (°C)")
                    sen66_widget.layout.yaxis2 = dict(
                        title="Humidity (%RH)", overlaying="y", side="right"
                    )
                    sen66_widget.layout.legend = dict(orientation="h", y=-0.2)
                    sen66_widget.layout.margin = dict(l=20, r=60, t=20, b=20)

                elif chart == "co2":
                    sen66_widget.add_scatter(
                        x=times,
                        y=[d["co2_ppm"] for d in data_rows],
                        name="CO₂ (ppm)",
                        mode="lines+markers",
                    )
                    sen66_widget.layout.yaxis = dict(title="CO₂ (ppm)")
                    sen66_widget.layout.yaxis2 = {}
                    sen66_widget.layout.legend = {}
                    sen66_widget.layout.margin = dict(l=20, r=20, t=20, b=20)

                elif chart == "voc_nox":
                    sen66_widget.add_scatter(
                        x=times,
                        y=[d["voc_index"] for d in data_rows],
                        name="VOC Index",
                        mode="lines+markers",
                    )
                    sen66_widget.add_scatter(
                        x=times,
                        y=[d["nox_index"] for d in data_rows],
                        name="NOx Index",
                        mode="lines+markers",
                    )
                    sen66_widget.layout.yaxis = dict(title="Index")
                    sen66_widget.layout.yaxis2 = {}
                    sen66_widget.layout.legend = {}
                    sen66_widget.layout.margin = dict(l=20, r=20, t=20, b=20)

                elif chart == "pm_mass":
                    for key, name in [
                        ("pm1_0_ugm3", "PM1.0"),
                        ("pm2_5_ugm3", "PM2.5"),
                        ("pm4_0_ugm3", "PM4.0"),
                        ("pm10_0_ugm3", "PM10"),
                    ]:
                        sen66_widget.add_scatter(
                            x=times,
                            y=[d[key] for d in data_rows],
                            name=name,
                            mode="lines+markers",
                        )
                    sen66_widget.layout.yaxis = dict(title="µg/m³")
                    sen66_widget.layout.yaxis2 = {}
                    sen66_widget.layout.legend = {}
                    sen66_widget.layout.margin = dict(l=20, r=20, t=20, b=20)

                elif chart == "pm_nc":
                    for key, name in [
                        ("nc_pm0_5_pcm3", "NC PM0.5"),
                        ("nc_pm1_0_pcm3", "NC PM1.0"),
                        ("nc_pm2_5_pcm3", "NC PM2.5"),
                        ("nc_pm4_0_pcm3", "NC PM4.0"),
                        ("nc_pm10_0_pcm3", "NC PM10"),
                    ]:
                        sen66_widget.add_scatter(
                            x=times,
                            y=[d[key] for d in data_rows],
                            name=name,
                            mode="lines+markers",
                        )
                    sen66_widget.layout.yaxis = dict(title="#/cm³")
                    sen66_widget.layout.yaxis2 = {}
                    sen66_widget.layout.legend = {}
                    sen66_widget.layout.margin = dict(l=20, r=20, t=20, b=20)

            else:
                # Surgical data update — no DOM teardown, no flash
                if chart == "temp_hum":
                    sen66_widget.data[0].x = times
                    sen66_widget.data[0].y = [d["temperature_c"] for d in data_rows]
                    sen66_widget.data[1].x = times
                    sen66_widget.data[1].y = [d["humidity_rh"] for d in data_rows]

                elif chart == "co2":
                    sen66_widget.data[0].x = times
                    sen66_widget.data[0].y = [d["co2_ppm"] for d in data_rows]

                elif chart == "voc_nox":
                    sen66_widget.data[0].x = times
                    sen66_widget.data[0].y = [d["voc_index"] for d in data_rows]
                    sen66_widget.data[1].x = times
                    sen66_widget.data[1].y = [d["nox_index"] for d in data_rows]

                elif chart == "pm_mass":
                    for i, key in enumerate(
                        ["pm1_0_ugm3", "pm2_5_ugm3", "pm4_0_ugm3", "pm10_0_ugm3"]
                    ):
                        sen66_widget.data[i].x = times
                        sen66_widget.data[i].y = [d[key] for d in data_rows]

                elif chart == "pm_nc":
                    for i, key in enumerate(
                        [
                            "nc_pm0_5_pcm3",
                            "nc_pm1_0_pcm3",
                            "nc_pm2_5_pcm3",
                            "nc_pm4_0_pcm3",
                            "nc_pm10_0_pcm3",
                        ]
                    ):
                        sen66_widget.data[i].x = times
                        sen66_widget.data[i].y = [d[key] for d in data_rows]
