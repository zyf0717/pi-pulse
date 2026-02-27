import asyncio
import json
import logging
from collections import deque
from datetime import datetime

import httpx
import plotly.graph_objects as go
import shinyswatch
from shiny import reactive, render, ui
from shinywidgets import render_widget

from config import DEVICES, PULSE_CHARTS, SEN66_DEVICES


def server(input, output, session):
    shinyswatch.theme_picker_server()

    # ── Plotly template (tracks chart_style input) ────────────────────────────
    @reactive.calc
    def plotly_tpl() -> str:
        return input.chart_style()

    # ── Pi-pulse state ────────────────────────────────────────────────────────
    _pulse_default = {
        "cpu": 0.0,
        "mem": 0.0,
        "temp": 0.0,
        "cpu_freq_avg_mhz": 0.0,
        "net_rx_bps_total": 0,
        "net_tx_bps_total": 0,
    }
    pulse_latest: dict[str, reactive.Value] = {
        k: reactive.Value(dict(_pulse_default)) for k in DEVICES
    }
    pulse_temp_history: dict[str, deque] = {k: deque(maxlen=60) for k in DEVICES}

    # ── Sen66 state — per device ──────────────────────────────────────────────
    _sen66_default = {
        "temperature_c": 0.0,
        "humidity_rh": 0.0,
        "co2_ppm": 0,
        "voc_index": 0.0,
        "nox_index": 0.0,
        "pm1_0_ugm3": 0.0,
        "pm2_5_ugm3": 0.0,
        "pm4_0_ugm3": 0.0,
        "pm10_0_ugm3": 0.0,
    }
    _sen66_nc_default = {
        "nc_pm0_5_pcm3": 0.0,
        "nc_pm1_0_pcm3": 0.0,
        "nc_pm2_5_pcm3": 0.0,
        "nc_pm4_0_pcm3": 0.0,
        "nc_pm10_0_pcm3": 0.0,
    }
    sen66_latest: dict[str, reactive.Value] = {
        k: reactive.Value(dict(_sen66_default)) for k in SEN66_DEVICES
    }
    sen66_nc_latest: dict[str, reactive.Value] = {
        k: reactive.Value(dict(_sen66_nc_default)) for k in SEN66_DEVICES
    }
    sen66_history: dict[str, deque] = {k: deque(maxlen=60) for k in SEN66_DEVICES}
    sen66_nc_history: dict[str, deque] = {k: deque(maxlen=60) for k in SEN66_DEVICES}

    # ── Generic SSE consumer ──────────────────────────────────────────────────
    async def stream_consumer(label: str, url: str, on_data):
        """Consume an SSE endpoint; call on_data(parsed_dict) under reactive.lock."""
        backoff = 1
        while True:
            try:
                async with httpx.AsyncClient(timeout=None) as client:
                    async with client.stream("GET", url) as response:
                        response.raise_for_status()
                        backoff = 1
                        async for line in response.aiter_lines():
                            if line.startswith("data: "):
                                json_str = line[len("data: ") :]
                                try:
                                    data = json.loads(json_str)
                                except json.JSONDecodeError:
                                    logging.warning(
                                        "Malformed SSE packet [%s], skipping: %r",
                                        label,
                                        json_str,
                                    )
                                    continue
                                async with reactive.lock():
                                    await on_data(data)
                                    await reactive.flush()
            except asyncio.CancelledError:
                return
            except Exception as exc:
                logging.warning(
                    "Stream error [%s] (%s: %s); reconnecting in %ds…",
                    label,
                    type(exc).__name__,
                    exc,
                    backoff,
                )
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 30)

    # ── Callbacks ─────────────────────────────────────────────────────────────
    async def on_pulse(key: str, data: dict):
        pulse_temp_history[key].append((datetime.now(), data))
        pulse_latest[key].set(data)

    async def on_sen66(key: str, data: dict):
        sen66_history[key].append((datetime.now(), data))
        sen66_latest[key].set(data)

    async def on_sen66_nc(key: str, data: dict):
        sen66_nc_history[key].append((datetime.now(), data))
        sen66_nc_latest[key].set(data)

    # ── Start all streams at session open ─────────────────────────────────────
    tasks = (
        [
            asyncio.create_task(
                stream_consumer(f"pulse-{k}", v["url"], lambda d, k=k: on_pulse(k, d))
            )
            for k, v in DEVICES.items()
        ]
        + [
            asyncio.create_task(
                stream_consumer(
                    f"sen66-{k}", v["stream"], lambda d, k=k: on_sen66(k, d)
                )
            )
            for k, v in SEN66_DEVICES.items()
        ]
        + [
            asyncio.create_task(
                stream_consumer(
                    f"sen66-nc-{k}", v["nc_stream"], lambda d, k=k: on_sen66_nc(k, d)
                )
            )
            for k, v in SEN66_DEVICES.items()
        ]
    )
    session.on_ended(lambda: [t.cancel() for t in tasks])

    # ── Pulse renders ─────────────────────────────────────────────────────────
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

    # ── Pulse chart — persistent widget, surgical data updates ─────────────
    pulse_widget = go.FigureWidget()
    _pulse_state: dict = {"chart": None, "dev": None, "tpl": None}

    @render_widget
    def temp_graph():
        return pulse_widget

    @reactive.Effect
    def _update_pulse_chart():
        dev = input.device()
        chart = input.pulse_chart()
        tpl = plotly_tpl()

        if dev not in DEVICES:
            return

        pulse_latest[dev]()
        history = list(pulse_temp_history[dev])
        if not history:
            return

        times = [t for t, _ in history]
        data_rows = [d for _, d in history]
        label = PULSE_CHARTS[chart]

        rebuild = (
            _pulse_state["chart"] != chart
            or _pulse_state["dev"] != dev
            or _pulse_state["tpl"] != tpl
        )
        with pulse_widget.batch_update():
            if chart == "net":
                rx_data = [d.get("net_rx_bps_total", 0) / 1024 for d in data_rows]
                tx_data = [d.get("net_tx_bps_total", 0) / 1024 for d in data_rows]
                if rebuild:
                    pulse_widget.data = []
                    pulse_widget.add_scatter(
                        x=times, y=rx_data, mode="lines+markers", name="Receive (KB/s)"
                    )
                    pulse_widget.add_scatter(
                        x=times, y=tx_data, mode="lines+markers", name="Transmit (KB/s)"
                    )
                    pulse_widget.layout.template = tpl
                    pulse_widget.layout.margin = dict(l=20, r=20, t=20, b=20)
                    pulse_widget.layout.yaxis.title = "KB/s"
                    pulse_widget.layout.legend = dict(orientation="h", y=-0.2)
                    _pulse_state.update({"chart": chart, "dev": dev, "tpl": tpl})
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
                scale = 1
                y_data = [d.get(field, 0.0) * scale for d in data_rows]
                if rebuild:
                    pulse_widget.data = []
                    pulse_widget.add_scatter(
                        x=times, y=y_data, mode="lines+markers", name=label
                    )
                    pulse_widget.layout.template = tpl
                    pulse_widget.layout.margin = dict(l=20, r=20, t=20, b=20)
                    pulse_widget.layout.yaxis.title = label
                    pulse_widget.layout.legend = {}
                    _pulse_state.update({"chart": chart, "dev": dev, "tpl": tpl})
                else:
                    pulse_widget.data[0].x = times
                    pulse_widget.data[0].y = y_data

    # ── Sen66 value box renders ───────────────────────────────────────────────
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

    # ── SEN66 chart — persistent widget, surgical data updates ──────────────
    sen66_widget = go.FigureWidget()
    _sen66_state: dict = {"chart": None, "dev": None, "tpl": None}

    @render_widget
    def sen66_graph():
        return sen66_widget

    @reactive.Effect
    def _update_sen66_chart():
        dev = input.device()
        chart = input.sen66_chart()
        tpl = plotly_tpl()

        if dev not in SEN66_DEVICES:
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
            _sen66_state["chart"] != chart
            or _sen66_state["dev"] != dev
            or _sen66_state["tpl"] != tpl
        )
        with sen66_widget.batch_update():
            if rebuild:
                sen66_widget.data = []
                sen66_widget.layout.template = tpl
                _sen66_state.update({"chart": chart, "dev": dev, "tpl": tpl})

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
