import asyncio
import json
import logging
from collections import deque
from datetime import datetime
from pathlib import Path

import httpx
import pandas as pd
import plotly.express as px
import yaml
from shiny import App, reactive, render, ui

_CONFIG_PATH = Path(__file__).parent / "config.yaml"
with _CONFIG_PATH.open() as _f:
    _CONFIG = yaml.safe_load(_f)

# pi-pulse URLs indexed by device: 0 → .10, 1 → .11
_PI_PULSE_URLS: list[str] = _CONFIG["pi-pulse"]
_DEVICES = {
    "10": {"label": "Device 10 (192.168.121.10)", "url": _PI_PULSE_URLS[0]},
    "11": {"label": "Device 11 (192.168.121.11)", "url": _PI_PULSE_URLS[1]},
}

# Web Worker keepalive: browsers do not throttle Web Workers even when the tab
# is hidden/not in focus, so this prevents the WebSocket from being closed due
# to missed pong responses caused by browser timer throttling.
_KEEPALIVE_JS = """
<script>
(function () {
  var workerCode = [
    'setInterval(function () { postMessage("ping"); }, 20000);'
  ].join('');
  var blob = new Blob([workerCode], { type: 'application/javascript' });
  var worker = new Worker(URL.createObjectURL(blob));
  worker.onmessage = function () {
    // Fetch a cheap resource to produce a real network round-trip,
    // which keeps the underlying TCP/WebSocket path alive.
    fetch(window.location.href, { method: 'HEAD', cache: 'no-store' }).catch(function () {});
  };
})();
</script>
"""

app_ui = ui.page_fluid(
    ui.HTML(_KEEPALIVE_JS),
    ui.input_radio_buttons(
        "device",
        "",
        {k: v["label"] for k, v in _DEVICES.items()},
        selected="10",
        inline=True,
    ),
    ui.hr(),
    ui.layout_column_wrap(
        ui.value_box(
            "CPU Usage",
            ui.output_text("cpu_val"),
            showcase=ui.tags.i(class_="bi bi-cpu"),
        ),
        ui.value_box(
            "Memory Usage",
            ui.output_text("mem_val"),
            showcase=ui.tags.i(class_="bi bi-memory"),
        ),
        ui.value_box(
            "Temperature",
            ui.output_text("temp_val"),
            showcase=ui.tags.i(class_="bi bi-thermometer-half"),
        ),
        fill=False,
    ),
    ui.hr(),
    ui.h4("Temperature — Last 60 Readings"),
    ui.output_ui("temp_graph"),
)


def server(input, output, session):
    # Per-device reactive state — one entry per device key, all maintained in parallel
    _default = {"cpu": 0.0, "mem": 0.0, "temp": 0.0}
    latest_data: dict[str, reactive.Value] = {
        k: reactive.Value(dict(_default)) for k in _DEVICES
    }
    temp_history: dict[str, deque] = {k: deque(maxlen=60) for k in _DEVICES}

    # Background task to consume one SSE stream indefinitely
    async def stream_consumer(device_key: str, url: str):
        backoff = 1  # seconds; doubles on each consecutive failure, capped at 30 s
        while True:
            try:
                async with httpx.AsyncClient(timeout=None) as client:
                    async with client.stream("GET", url) as response:
                        response.raise_for_status()
                        backoff = 1  # reset on successful connection
                        async for line in response.aiter_lines():
                            if line.startswith("data: "):
                                json_str = line[len("data: ") :]
                                try:
                                    data = json.loads(json_str)
                                except json.JSONDecodeError:
                                    logging.warning(
                                        "Malformed SSE packet, skipping: %r", json_str
                                    )
                                    continue
                                async with reactive.lock():
                                    temp_history[device_key].append(
                                        (datetime.now(), data["temp"])
                                    )
                                    latest_data[device_key].set(data)
                                    await reactive.flush()
            except asyncio.CancelledError:
                return  # session ended — exit cleanly
            except Exception as exc:
                logging.warning(
                    "Stream error [%s] (%s: %s); reconnecting in %ds…",
                    device_key,
                    type(exc).__name__,
                    exc,
                    backoff,
                )
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 30)

    # Start ALL device streams immediately; cancel all when session ends
    tasks = {
        k: asyncio.create_task(stream_consumer(k, v["url"]))
        for k, v in _DEVICES.items()
    }
    session.on_ended(lambda: [t.cancel() for t in tasks.values()])

    @render.text
    def cpu_val():
        return f"{latest_data[input.device()]().get('cpu', 0.0):.1f}%"

    @render.text
    def mem_val():
        return f"{latest_data[input.device()]().get('mem', 0.0):.1f}%"

    @render.text
    def temp_val():
        return f"{latest_data[input.device()]().get('temp', 0.0):.1f}°C"

    @render.ui
    def temp_graph():
        dev = input.device()
        latest_data[dev]()  # reactive dependency — re-runs on every new packet
        history = temp_history[dev]
        if not history:
            return ui.p("Waiting for data…")
        times, temps = zip(*history)
        df = pd.DataFrame({"Time": list(times), "Temperature (°C)": list(temps)})
        fig = px.line(
            df,
            x="Time",
            y="Temperature (°C)",
            markers=True,
        )
        fig.update_layout(
            margin=dict(l=20, r=20, t=20, b=20),
            xaxis_title="Time",
            yaxis_title="Temperature (°C)",
        )
        return ui.HTML(fig.to_html(full_html=False, include_plotlyjs="cdn"))


app = App(app_ui, server)
