import asyncio
import json
import logging
from collections import deque
from datetime import datetime

import httpx
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import shinyswatch
from shiny import reactive, render, ui

from config import DEVICES, PULSE_CHARTS, SEN66_DEVICES


def server(input, output, session):
    shinyswatch.theme_picker_server()

    # ── Plotly template (tracks chart_style input) ────────────────────────────
    @reactive.calc
    def plotly_tpl() -> str:
        return input.chart_style()

    # ── Pi-pulse state ────────────────────────────────────────────────────────
    _pulse_default = {"cpu": 0.0, "mem": 0.0, "temp": 0.0}
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

    @render.ui
    def temp_graph():
        dev = input.device()
        chart = input.pulse_chart()
        tpl = plotly_tpl()
        if dev not in DEVICES:
            return ui.p(
                f"Device {dev} has no Pi Pulse stream.",
                class_="text-warning mt-3",
            )
        pulse_latest[dev]()
        history = pulse_temp_history[dev]
        if not history:
            return ui.p("Waiting for data…")
        times = [t for t, _ in history]
        data_rows = [d for _, d in history]
        label = PULSE_CHARTS[chart]
        field = {"cpu": "cpu", "mem": "mem", "temp": "temp"}[chart]
        df = pd.DataFrame(
            {"Time": times, label: [d.get(field, 0.0) for d in data_rows]}
        )
        fig = px.line(df, x="Time", y=label, markers=True, template=tpl)
        fig.update_layout(margin=dict(l=20, r=20, t=20, b=20))
        return ui.HTML(fig.to_html(full_html=False, include_plotlyjs="cdn"))

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

    # ── Sen66 chart render ────────────────────────────────────────────────────
    @render.ui
    def sen66_graph():
        dev = input.device()
        chart = input.sen66_chart()
        tpl = plotly_tpl()

        if dev not in SEN66_DEVICES:
            return ui.p(
                f"Device {dev} has no SEN66 stream.",
                class_="text-warning mt-3",
            )

        if chart == "pm_nc":
            sen66_nc_latest[dev]()
            history = list(sen66_nc_history[dev])
        else:
            sen66_latest[dev]()
            history = list(sen66_history[dev])

        if not history:
            return ui.p("Waiting for data…")

        times = [t for t, _ in history]
        data_rows = [d for _, d in history]

        def _fig(fig):
            fig.update_layout(margin=dict(l=20, r=20, t=20, b=20))
            return ui.HTML(fig.to_html(full_html=False, include_plotlyjs="cdn"))

        if chart == "temp_hum":
            fig = go.Figure()
            fig.add_trace(
                go.Scatter(
                    x=times,
                    y=[d["temperature_c"] for d in data_rows],
                    name="Temperature (°C)",
                    mode="lines+markers",
                    yaxis="y1",
                )
            )
            fig.add_trace(
                go.Scatter(
                    x=times,
                    y=[d["humidity_rh"] for d in data_rows],
                    name="Humidity (%RH)",
                    mode="lines+markers",
                    yaxis="y2",
                )
            )
            fig.update_layout(
                template=tpl,
                yaxis=dict(title="Temperature (°C)"),
                yaxis2=dict(title="Humidity (%RH)", overlaying="y", side="right"),
                legend=dict(orientation="h", y=-0.2),
                margin=dict(l=20, r=60, t=20, b=20),
            )
            return ui.HTML(fig.to_html(full_html=False, include_plotlyjs="cdn"))

        if chart == "co2":
            df = pd.DataFrame(
                {"Time": times, "CO₂ (ppm)": [d["co2_ppm"] for d in data_rows]}
            )
            return _fig(
                px.line(df, x="Time", y="CO₂ (ppm)", markers=True, template=tpl)
            )

        if chart == "voc_nox":
            df = pd.DataFrame(
                {
                    "Time": times,
                    "VOC Index": [d["voc_index"] for d in data_rows],
                    "NOx Index": [d["nox_index"] for d in data_rows],
                }
            )
            return _fig(
                px.line(
                    df,
                    x="Time",
                    y=["VOC Index", "NOx Index"],
                    markers=True,
                    template=tpl,
                )
            )

        if chart == "pm_mass":
            df = pd.DataFrame(
                {
                    "Time": times,
                    "PM1.0": [d["pm1_0_ugm3"] for d in data_rows],
                    "PM2.5": [d["pm2_5_ugm3"] for d in data_rows],
                    "PM4.0": [d["pm4_0_ugm3"] for d in data_rows],
                    "PM10": [d["pm10_0_ugm3"] for d in data_rows],
                }
            )
            return _fig(
                px.line(
                    df,
                    x="Time",
                    y=["PM1.0", "PM2.5", "PM4.0", "PM10"],
                    markers=True,
                    template=tpl,
                    labels={"value": "µg/m³", "variable": "Fraction"},
                )
            )

        if chart == "pm_nc":
            df = pd.DataFrame(
                {
                    "Time": times,
                    "NC PM0.5": [d["nc_pm0_5_pcm3"] for d in data_rows],
                    "NC PM1.0": [d["nc_pm1_0_pcm3"] for d in data_rows],
                    "NC PM2.5": [d["nc_pm2_5_pcm3"] for d in data_rows],
                    "NC PM4.0": [d["nc_pm4_0_pcm3"] for d in data_rows],
                    "NC PM10": [d["nc_pm10_0_pcm3"] for d in data_rows],
                }
            )
            return _fig(
                px.line(
                    df,
                    x="Time",
                    y=["NC PM0.5", "NC PM1.0", "NC PM2.5", "NC PM4.0", "NC PM10"],
                    markers=True,
                    template=tpl,
                    labels={"value": "#/cm³", "variable": "Fraction"},
                )
            )

        return ui.p("Unknown chart selection.")
