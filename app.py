import asyncio
import json
import logging
from collections import deque
from datetime import datetime
from pathlib import Path

import httpx
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import shinyswatch
import yaml
from faicons import icon_svg
from shiny import App, reactive, render, ui

_INFO_ICON = icon_svg("circle-info", fill="currentColor", height="1em")

_CONFIG_PATH = Path(__file__).parent / "config.yaml"
with _CONFIG_PATH.open() as _f:
    _CONFIG = yaml.safe_load(_f)

# pi-pulse: device-keyed dict from config
_DEVICES = {
    k: {"label": f"Device {k} (192.168.121.{k})", "url": v["stream"]}
    for k, v in _CONFIG["pi-pulse"].items()
}

# sen66: device-keyed dict; each entry has two endpoints
_SEN66_DEVICES = {
    k: {
        "label": f"Device {k} (192.168.121.{k})",
        "stream": v["stream"],
        "nc_stream": v["nc-stream"],
    }
    for k, v in _CONFIG["sen66"].items()
}
_SEN66_DEFAULT_DEV = next(iter(_SEN66_DEVICES))

# Combined device list across all tabs (sorted by key)
_ALL_DEVICES = {
    k: f"Device {k} (192.168.121.{k})"
    for k in sorted(set(_DEVICES) | set(_SEN66_DEVICES))
}
_ALL_DEVICES_DEFAULT = "11"

_PULSE_CHARTS = {
    "cpu": "CPU Usage (%)",
    "mem": "Memory Usage (%)",
    "temp": "Temperature (°C)",
}

_SEN66_CHARTS = {
    "temp_hum": "Temperature & Humidity",
    "co2": "CO₂",
    "voc_nox": "VOC & NOx",
    "pm_mass": "PM Mass Concentration (µg/m³)",
    "pm_nc": "PM Number Concentration (#/cm³)",
}

# Bootstrap themes considered dark → use plotly_dark template
_DARK_THEMES = {"cyborg", "darkly", "slate", "solar", "superhero", "vapor"}

# Web Worker keepalive + auto-reload on disconnect
_KEEPALIVE_JS = """
<script>
(function () {
  // Web Worker runs outside the throttled page context, so Chrome won't suspend it.
  // It fires a HEAD fetch every 20 s to keep the WebSocket ping/pong alive.
  var workerCode = 'setInterval(function () { postMessage("ping"); }, 20000);';
  var blob = new Blob([workerCode], { type: 'application/javascript' });
  var worker = new Worker(URL.createObjectURL(blob));
  worker.onmessage = function () {
    fetch(window.location.href, { method: 'HEAD', cache: 'no-store' }).catch(function () {});
  };

  // If the Shiny WebSocket closes for any reason, reload the page after 2 s.
  // This recovers from background-tab throttling that outlasts the server ping timeout.
  document.addEventListener('shiny:disconnected', function () {
    setTimeout(function () { window.location.reload(); }, 2000);
  });
})();
</script>
"""

app_ui = ui.page_sidebar(
    ui.sidebar(
        ui.input_select(
            "device",
            None,
            _ALL_DEVICES,
            selected=_ALL_DEVICES_DEFAULT,
        ),
        ui.hr(),
        shinyswatch.theme_picker_ui("darkly"),
        ui.hr(),
        ui.h6("Chart style"),
        ui.input_radio_buttons(
            "chart_style",
            None,
            {"plotly": "Light", "plotly_dark": "Dark"},
            selected="plotly_dark",
            inline=True,
        ),
        width=220,
    ),
    ui.HTML(_KEEPALIVE_JS),
    ui.navset_tab(
        # ── Pulse tab ────────────────────────────────────────────────────────
        ui.nav_panel(
            "System",
            ui.br(),
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
            ui.input_select(
                "pulse_chart",
                "",
                _PULSE_CHARTS,
                selected="temp",
            ),
            ui.output_ui("temp_graph"),
        ),
        # ── Environmental tab ────────────────────────────────────────────────
        ui.nav_panel(
            "SEN66",
            ui.br(),
            ui.layout_column_wrap(
                ui.card(
                    ui.card_header(
                        ui.tooltip(
                            ui.span("Temperature ", _INFO_ICON),
                            "Sensor: SHTC3",
                            ui.tags.br(),
                            "Typ. accuracy ±0.45°C (15–40°C)",
                            ui.tags.br(),
                            "Range: −40 to 125°C",
                            ui.tags.br(),
                            "Note: self-heating correction applied by firmware.",
                            placement="top",
                            id="tooltip_temp",
                        ),
                    ),
                    ui.div(ui.output_text("sen66_temp_val"), class_="fs-3 fw-bold p-2"),
                ),
                ui.card(
                    ui.card_header(
                        ui.tooltip(
                            ui.span("Humidity ", _INFO_ICON),
                            "Sensor: SHTC3",
                            ui.tags.br(),
                            "Typ. accuracy ±4.5%RH (20–80%RH)",
                            ui.tags.br(),
                            "Range: 0–100%RH",
                            placement="top",
                            id="tooltip_hum",
                        ),
                    ),
                    ui.div(ui.output_text("sen66_hum_val"), class_="fs-3 fw-bold p-2"),
                ),
                ui.card(
                    ui.card_header(
                        ui.tooltip(
                            ui.span("CO₂ ", _INFO_ICON),
                            "Sensor: SCD4x (NDIR)",
                            ui.tags.br(),
                            "Accuracy ±(50 ppm + 5% of reading) for 400–5000 ppm",
                            ui.tags.br(),
                            "Range: 0–40,000 ppm",
                            ui.tags.br(),
                            "Requires ≈3 min warm-up for stable readings.",
                            placement="top",
                            id="tooltip_co2",
                        ),
                    ),
                    ui.div(ui.output_text("sen66_co2_val"), class_="fs-3 fw-bold p-2"),
                ),
                ui.card(
                    ui.card_header(
                        ui.tooltip(
                            ui.span("VOC Index ", _INFO_ICON),
                            "Sensor: SGP4x (MOX)",
                            ui.tags.br(),
                            "Dimensionless index 0–500",
                            ui.tags.br(),
                            "100 = baseline (typical clean indoor air)",
                            ui.tags.br(),
                            "Not a direct gas concentration measurement.",
                            placement="top",
                            id="tooltip_voc",
                        ),
                    ),
                    ui.div(ui.output_text("sen66_voc_val"), class_="fs-3 fw-bold p-2"),
                ),
                ui.card(
                    ui.card_header(
                        ui.tooltip(
                            ui.span("NOx Index ", _INFO_ICON),
                            "Sensor: SGP4x (MOX)",
                            ui.tags.br(),
                            "Dimensionless index 1–500",
                            ui.tags.br(),
                            "1 = cleanest possible air",
                            ui.tags.br(),
                            "Not a direct gas concentration measurement.",
                            placement="top",
                            id="tooltip_nox",
                        ),
                    ),
                    ui.div(ui.output_text("sen66_nox_val"), class_="fs-3 fw-bold p-2"),
                ),
                fill=False,
            ),
            ui.hr(),
            ui.input_select(
                "sen66_chart",
                "",
                _SEN66_CHARTS,
                selected="temp_hum",
            ),
            ui.output_ui("sen66_graph"),
        ),
    ),
)


def server(input, output, session):
    shinyswatch.theme_picker_server()

    # ── Plotly template (tracks chart_style input) ────────────────────────────
    @reactive.calc
    def plotly_tpl() -> str:
        return input.chart_style()

    # ── Pi-pulse state ────────────────────────────────────────────────────────
    _pulse_default = {"cpu": 0.0, "mem": 0.0, "temp": 0.0}
    pulse_latest: dict[str, reactive.Value] = {
        k: reactive.Value(dict(_pulse_default)) for k in _DEVICES
    }
    pulse_temp_history: dict[str, deque] = {k: deque(maxlen=60) for k in _DEVICES}

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
        k: reactive.Value(dict(_sen66_default)) for k in _SEN66_DEVICES
    }
    sen66_nc_latest: dict[str, reactive.Value] = {
        k: reactive.Value(dict(_sen66_nc_default)) for k in _SEN66_DEVICES
    }
    sen66_history: dict[str, deque] = {k: deque(maxlen=60) for k in _SEN66_DEVICES}
    sen66_nc_history: dict[str, deque] = {k: deque(maxlen=60) for k in _SEN66_DEVICES}

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
            for k, v in _DEVICES.items()
        ]
        + [
            asyncio.create_task(
                stream_consumer(
                    f"sen66-{k}", v["stream"], lambda d, k=k: on_sen66(k, d)
                )
            )
            for k, v in _SEN66_DEVICES.items()
        ]
        + [
            asyncio.create_task(
                stream_consumer(
                    f"sen66-nc-{k}", v["nc_stream"], lambda d, k=k: on_sen66_nc(k, d)
                )
            )
            for k, v in _SEN66_DEVICES.items()
        ]
    )
    session.on_ended(lambda: [t.cancel() for t in tasks])

    # ── Pulse renders ─────────────────────────────────────────────────────────
    @render.text
    def cpu_val():
        dev = input.device()
        if dev not in _DEVICES:
            return "N/A"
        return f"{pulse_latest[dev]().get('cpu', 0.0):.1f}%"

    @render.text
    def mem_val():
        dev = input.device()
        if dev not in _DEVICES:
            return "N/A"
        return f"{pulse_latest[dev]().get('mem', 0.0):.1f}%"

    @render.text
    def temp_val():
        dev = input.device()
        if dev not in _DEVICES:
            return "N/A"
        return f"{pulse_latest[dev]().get('temp', 0.0):.1f}°C"

    @render.ui
    def temp_graph():
        dev = input.device()
        chart = input.pulse_chart()
        tpl = plotly_tpl()
        if dev not in _DEVICES:
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
        label = _PULSE_CHARTS[chart]
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
        if dev not in _SEN66_DEVICES:
            return "N/A"
        return f"{sen66_latest[dev]().get('temperature_c', 0.0):.2f}°C"

    @render.text
    def sen66_hum_val():
        dev = input.device()
        if dev not in _SEN66_DEVICES:
            return "N/A"
        return f"{sen66_latest[dev]().get('humidity_rh', 0.0):.2f}%"

    @render.text
    def sen66_co2_val():
        dev = input.device()
        if dev not in _SEN66_DEVICES:
            return "N/A"
        return f"{sen66_latest[dev]().get('co2_ppm', 0)} ppm"

    @render.text
    def sen66_voc_val():
        dev = input.device()
        if dev not in _SEN66_DEVICES:
            return "N/A"
        return f"{sen66_latest[dev]().get('voc_index', 0.0):.1f}"

    @render.text
    def sen66_nox_val():
        dev = input.device()
        if dev not in _SEN66_DEVICES:
            return "N/A"
        return f"{sen66_latest[dev]().get('nox_index', 0.0):.1f}"

    # ── Sen66 chart render ────────────────────────────────────────────────────
    @render.ui
    def sen66_graph():
        dev = input.device()
        chart = input.sen66_chart()
        tpl = plotly_tpl()

        if dev not in _SEN66_DEVICES:
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


app = App(app_ui, server)
