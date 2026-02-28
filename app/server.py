import asyncio
from collections import deque
from datetime import datetime

import plotly.graph_objects as go
import shinyswatch
from shiny import reactive

from app.config import DEVICES, SEN66_DEVICES
from app.renders.pulse import register_pulse_renders
from app.renders.sen66 import register_sen66_renders
from app.streams.consumer import stream_consumer


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

    # ── SEN66 state ───────────────────────────────────────────────────────────
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

    # ── SSE callbacks ─────────────────────────────────────────────────────────
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

    # ── Register renders ──────────────────────────────────────────────────────
    pulse_widget = go.FigureWidget(layout=dict(autosize=True, height=400))
    pulse_state: dict = {"chart": None, "dev": None, "tpl": None}
    register_pulse_renders(
        input, pulse_latest, pulse_temp_history, plotly_tpl, pulse_widget, pulse_state
    )

    sen66_widget = go.FigureWidget(layout=dict(autosize=True, height=400))
    sen66_state: dict = {"chart": None, "dev": None, "tpl": None}
    register_sen66_renders(
        input,
        sen66_latest,
        sen66_nc_latest,
        sen66_history,
        sen66_nc_history,
        plotly_tpl,
        sen66_widget,
        sen66_state,
    )
