import shinyswatch
from faicons import icon_svg
from shiny import ui
from shinywidgets import output_widget

from app.config import (
    ALL_DEVICES,
    ALL_DEVICES_DEFAULT,
    H10_ACC_DYNAMIC_WINDOW_S,
    H10_CHARTS,
    PULSE_CHARTS,
    SEN66_CHARTS,
)

_INFO_ICON = icon_svg("circle-info", fill="currentColor", height="1em")
_CARD_ATTRS_CLASS = "metric-card-trigger"

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

_CARD_CLICK_JS = """
<script>
(function () {
  function findMetricCardTrigger(node) {
    while (node) {
      if (node.classList && node.classList.contains("metric-card-trigger")) {
        return node;
      }
      node = node.parentNode;
    }
    return null;
  }

  function activateMetricCard(node) {
    var targetId = node.getAttribute("data-chart-target");
    var nextValue = node.getAttribute("data-chart-value");
    var select = document.getElementById(targetId);
    if (!select || select.value === nextValue) {
      return;
    }
    select.value = nextValue;
    select.dispatchEvent(new Event("change", { bubbles: true }));
  }

  document.addEventListener("click", function (event) {
    var trigger = findMetricCardTrigger(event.target);
    if (!trigger) {
      return;
    }
    activateMetricCard(trigger);
  });

  document.addEventListener("keydown", function (event) {
    if (event.key !== "Enter" && event.key !== " ") {
      return;
    }
    var trigger = findMetricCardTrigger(event.target);
    if (!trigger) {
      return;
    }
    event.preventDefault();
    activateMetricCard(trigger);
  });
})();
</script>
"""

_PULSE_CARD_SPECS = [
    ("CPU Usage", "cpu_val", "cpu_spark", "cpu"),
    ("CPU Frequency", "cpu_freq_val", "cpu_freq_spark", "cpu_freq"),
    ("Memory Usage", "mem_val", "mem_spark", "mem"),
    ("Temperature", "temp_val", "temp_spark", "temp"),
    ("Download", "net_rx_val", "net_rx_spark", "net"),
    ("Upload", "net_tx_val", "net_tx_spark", "net"),
]

_SEN66_CARD_SPECS = [
    ("Temperature", "sen66_temp_val", "sen66_temp_spark", "temp_hum", "tooltip_temp"),
    ("Humidity", "sen66_hum_val", "sen66_hum_spark", "temp_hum", "tooltip_hum"),
    ("CO₂", "sen66_co2_val", "sen66_co2_spark", "co2", "tooltip_co2"),
    ("VOC Index", "sen66_voc_val", "sen66_voc_spark", "voc_nox", "tooltip_voc"),
    ("NOx Index", "sen66_nox_val", "sen66_nox_spark", "voc_nox", "tooltip_nox"),
]

_H10_CARD_SPECS = [
    ("Heart Rate", "h10_bpm_val", "h10_bpm_spark", "bpm"),
    ("RR Interval", "h10_rr_last_val", "h10_rr_last_spark", "rr"),
    ("ECG", "h10_ecg_val", "h10_ecg_spark", "ecg"),
    ("Mean Dynamic Acceleration", "h10_acc_val", "h10_acc_spark", "acc_dyn"),
]


def _metric_card(
    header_content,
    value_output_id: str,
    spark_output_id: str,
    *,
    chart_target: str,
    chart_value: str,
):
    return ui.div(
        ui.card(
            ui.card_header(header_content),
            ui.div(
                ui.div(ui.output_text(value_output_id), class_="fs-3 fw-bold p-2"),
                ui.output_ui(spark_output_id),
                style="pointer-events:none;",
            ),
        ),
        **{
            "class": _CARD_ATTRS_CLASS,
            "role": "button",
            "tabindex": "0",
            "style": "cursor:pointer;",
            "data-chart-target": chart_target,
            "data-chart-value": chart_value,
        },
    )


def _visual_card(
    header_content,
    preview_output_id: str,
    *,
    chart_target: str,
    chart_value: str,
):
    return ui.div(
        ui.card(
            ui.card_header(header_content),
            ui.div(
                ui.output_ui(preview_output_id),
                style="pointer-events:none;",
            ),
        ),
        **{
            "class": _CARD_ATTRS_CLASS,
            "role": "button",
            "tabindex": "0",
            "style": "cursor:pointer;",
            "data-chart-target": chart_target,
            "data-chart-value": chart_value,
        },
    )


def _sensor_tooltip(label: str, tooltip_id: str, *lines):
    tooltip_parts = [ui.span(f"{label} ", _INFO_ICON)]
    if lines:
        for line in lines:
            tooltip_parts.extend([line, ui.tags.br()])
        tooltip_parts.pop()
    else:
        tooltip_parts.append(label)
    return ui.tooltip(*tooltip_parts, placement="top", id=tooltip_id)


def _pulse_cards():
    return [
        _metric_card(
            title,
            value_output_id,
            spark_output_id,
            chart_target="pulse_chart",
            chart_value=chart_value,
        )
        for title, value_output_id, spark_output_id, chart_value in _PULSE_CARD_SPECS
    ]


def _sen66_cards():
    tooltip_map = {
        "tooltip_temp": _sensor_tooltip(
            "Temperature",
            "tooltip_temp",
            "Sensor: SHTC3",
            "Typ. accuracy ±0.45°C (15–40°C)",
            "Range: −40 to 125°C",
            "Note: self-heating correction applied by firmware.",
        ),
        "tooltip_hum": _sensor_tooltip(
            "Humidity",
            "tooltip_hum",
            "Sensor: SHTC3",
            "Typ. accuracy ±4.5%RH (20–80%RH)",
            "Range: 0–100%RH",
        ),
        "tooltip_co2": _sensor_tooltip(
            "CO₂",
            "tooltip_co2",
            "Sensor: SCD4x (NDIR)",
            "Accuracy ±(50 ppm + 5% of reading) for 400–5000 ppm",
            "Range: 0–40,000 ppm",
            "Requires ≈3 min warm-up for stable readings.",
        ),
        "tooltip_voc": _sensor_tooltip(
            "VOC Index",
            "tooltip_voc",
            "Sensor: SGP4x (MOX)",
            "Dimensionless index 0–500",
            "100 = baseline (typical clean indoor air)",
            "Not a direct gas concentration measurement.",
        ),
        "tooltip_nox": _sensor_tooltip(
            "NOx Index",
            "tooltip_nox",
            "Sensor: SGP4x (MOX)",
            "Dimensionless index 1–500",
            "1 = cleanest possible air",
            "Not a direct gas concentration measurement.",
        ),
    }
    return [
        _metric_card(
            tooltip_map[tooltip_id],
            value_output_id,
            spark_output_id,
            chart_target="sen66_chart",
            chart_value=chart_value,
        )
        for _, value_output_id, spark_output_id, chart_value, tooltip_id in _SEN66_CARD_SPECS
    ]


def _h10_cards():
    window_s = f"{H10_ACC_DYNAMIC_WINDOW_S:g}"
    tooltip_map = {
        "tooltip_h10_acc": _sensor_tooltip(
            "Mean Dynamic Acceleration",
            "tooltip_h10_acc",
            f"Average movement over the last {window_s} s.",
            "Baseline tilt/gravity is removed first.",
            "Higher values mean more motion during that window.",
        ),
        "tooltip_h10_tilt": _sensor_tooltip(
            "Acceleration Axes",
            "tooltip_h10_tilt",
            "At rest, the combined X/Y/Z acceleration is usually ~1000 mg because of gravity (1g ≈ 9.81 m/s²).",
            "How the 1000 mg is distributed depends on how the sensor is physically oriented.",
            "Expanded graphs show recent X-Y, X-Z, and Y-Z acceleration pairs over time.",
            "They show which direction gravity and motion are acting on the sensor.",
        ),
    }
    cards = [
        _metric_card(
            title,
            value_output_id,
            spark_output_id,
            chart_target="h10_chart",
            chart_value=chart_value,
        )
        for title, value_output_id, spark_output_id, chart_value in _H10_CARD_SPECS[:3]
    ]
    _, acc_value_output_id, acc_spark_output_id, acc_chart_value = _H10_CARD_SPECS[3]
    cards.append(
        _metric_card(
            tooltip_map["tooltip_h10_acc"],
            acc_value_output_id,
            acc_spark_output_id,
            chart_target="h10_chart",
            chart_value=acc_chart_value,
        )
    )
    cards.append(
        _visual_card(
            tooltip_map["tooltip_h10_tilt"],
            "h10_motion_preview",
            chart_target="h10_chart",
            chart_value="motion",
        )
    )
    return cards


def _system_panel():
    return ui.nav_panel(
        "System",
        ui.br(),
        ui.layout_column_wrap(*_pulse_cards(), fill=False),
        ui.hr(),
        ui.input_select(
            "pulse_chart",
            "",
            PULSE_CHARTS,
            selected="temp",
        ),
        output_widget("temp_graph"),
    )


def _sen66_panel():
    return ui.nav_panel(
        "SEN66",
        ui.br(),
        ui.layout_column_wrap(*_sen66_cards(), fill=False),
        ui.hr(),
        ui.input_select(
            "sen66_chart",
            "",
            SEN66_CHARTS,
            selected="temp_hum",
        ),
        output_widget("sen66_graph"),
    )


def _h10_panel():
    return ui.nav_panel(
        "H10",
        ui.br(),
        ui.layout_column_wrap(*_h10_cards(), fill=False),
        ui.hr(),
        ui.input_select(
            "h10_chart",
            "",
            H10_CHARTS,
            selected="bpm",
        ),
        ui.output_ui("h10_detail_view"),
    )


app_ui = ui.page_sidebar(
    ui.sidebar(
        ui.input_select(
            "device",
            "Select a device:",
            ALL_DEVICES,
            selected=ALL_DEVICES_DEFAULT,
        ),
        ui.hr(),
        shinyswatch.theme_picker_ui(),
        ui.hr(),
        ui.input_radio_buttons(
            "chart_style",
            "Chart style:",
            {"plotly": "Light", "plotly_dark": "Dark"},
            selected="plotly_dark",
            inline=True,
        ),
        width=220,
    ),
    ui.HTML(_KEEPALIVE_JS),
    ui.HTML(_CARD_CLICK_JS),
    ui.navset_tab(
        _system_panel(),
        _sen66_panel(),
        _h10_panel(),
        selected="SEN66",
    ),
    theme=shinyswatch.theme.darkly,
)
