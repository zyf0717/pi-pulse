import shinyswatch
from faicons import icon_svg
from shiny import ui

from config import ALL_DEVICES, ALL_DEVICES_DEFAULT, PULSE_CHARTS, SEN66_CHARTS

_INFO_ICON = icon_svg("circle-info", fill="currentColor", height="1em")

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
            ALL_DEVICES,
            selected=ALL_DEVICES_DEFAULT,
        ),
        ui.hr(),
        shinyswatch.theme_picker_ui(),
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
                PULSE_CHARTS,
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
                SEN66_CHARTS,
                selected="temp_hum",
            ),
            ui.output_ui("sen66_graph"),
        ),
        selected="SEN66",
    ),
    theme=shinyswatch.theme.darkly,
)
