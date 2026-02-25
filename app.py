import asyncio
import json
import logging
import os
from collections import deque
from datetime import datetime

import httpx
import pandas as pd
import plotly.express as px
from dotenv import load_dotenv
from shiny import App, reactive, render, ui

load_dotenv()

STREAM_URL = os.getenv("STREAM_URL", "http://192.168.121.10:8001/stream")

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
    ui.h2("Pi-Pulse Real-Time Telemetry"),
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
    # Reactive value to store the latest stream packet
    latest_data = reactive.Value({"cpu": 0.0, "mem": 0.0, "temp": 0.0})

    # Rolling history: (timestamp, temp) for the last 60 readings
    temp_history: deque[tuple[datetime, float]] = deque(maxlen=60)

    # Background task to consume the SSE stream, with reconnect/backoff on errors
    async def stream_consumer():
        backoff = 1  # seconds; doubles on each consecutive failure, capped at 30 s
        while True:
            try:
                async with httpx.AsyncClient(timeout=None) as client:
                    async with client.stream("GET", STREAM_URL) as response:
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
                                    temp_history.append((datetime.now(), data["temp"]))
                                    latest_data.set(data)
                                    await reactive.flush()
            except asyncio.CancelledError:
                return  # session ended — exit cleanly
            except Exception as exc:
                logging.warning(
                    "Stream error (%s: %s); reconnecting in %ds…",
                    type(exc).__name__,
                    exc,
                    backoff,
                )
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 30)

    # Start as a true background asyncio task; cancel on session end
    task = asyncio.create_task(stream_consumer())
    session.on_ended(lambda: task.cancel())

    @render.text
    def cpu_val():
        return f"{latest_data().get('cpu', 0.0):.1f}%"

    @render.text
    def mem_val():
        return f"{latest_data().get('mem', 0.0):.1f}%"

    @render.text
    def temp_val():
        return f"{latest_data().get('temp', 0.0):.1f}°C"

    @render.ui
    def temp_graph():
        latest_data()  # reactive dependency — re-runs on every new packet
        if not temp_history:
            return ui.p("Waiting for data…")
        times, temps = zip(*temp_history)
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
