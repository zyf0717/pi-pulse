"""GPS renders: value cards only."""

from collections import deque
from datetime import datetime, timedelta, timezone

from shiny import reactive, render, ui

from app.config import GPS_DEVICES
from app.renders.render_utils import metric_value, sparkline_values
from app.sparkline import blank_sparkline, sparkline

_GMT_PLUS_8 = timezone(timedelta(hours=8))


def _gps_spark(
    device: str,
    gps_latest: dict[str, reactive.Value],
    gps_history: dict[str, deque],
    field: str,
    *,
    fmt=None,
):
    values = sparkline_values(device, GPS_DEVICES, gps_latest, gps_history, field)
    if values is None:
        return blank_sparkline()
    return sparkline(values, fmt=fmt) if fmt else sparkline(values)


def _format_timestamp(value: object) -> str:
    text = str(value or "").strip()
    if not text:
        return "N/A"
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(_GMT_PLUS_8).strftime("%H:%M:%S")
    except ValueError:
        return text


def _timestamp_html(value: object) -> str:
    formatted = _format_timestamp(value)
    if formatted == "N/A":
        return "N/A"
    return (
        f'{formatted} '
        '<span style="font-family:inherit;font-size:1.4rem;line-height:1;'
        'color:#9e9e9e;font-variant-numeric:tabular-nums;">GMT+8</span>'
    )


def register_gps_renders(
    input,
    gps_latest: dict[str, reactive.Value],
    gps_history: dict[str, deque],
) -> None:
    """Register all GPS-tab output renders inside the active Shiny session."""

    @render.text
    def gps_lat_val():
        return metric_value(
            input.device(),
            GPS_DEVICES,
            gps_latest,
            "latitude",
            lambda value: f"{value:.6f}",
        )

    @render.text
    def gps_lon_val():
        return metric_value(
            input.device(),
            GPS_DEVICES,
            gps_latest,
            "longitude",
            lambda value: f"{value:.6f}",
        )

    @render.text
    def gps_accuracy_val():
        return metric_value(
            input.device(),
            GPS_DEVICES,
            gps_latest,
            "accuracy",
            lambda value: f"{value:.1f} m",
        )

    @render.text
    def gps_altitude_val():
        return metric_value(
            input.device(),
            GPS_DEVICES,
            gps_latest,
            "altitude",
            lambda value: f"{value:.1f} m",
        )

    @render.text
    def gps_speed_val():
        return metric_value(
            input.device(),
            GPS_DEVICES,
            gps_latest,
            "speed",
            lambda value: f"{value:.1f} m/s",
        )

    @render.ui
    def gps_timestamp_val():
        if input.device() not in GPS_DEVICES:
            return ui.HTML("N/A")
        value = gps_latest[input.device()]().get("timestamp", "")
        return ui.HTML(_timestamp_html(value))

    @render.ui
    def gps_lat_spark():
        return _gps_spark(
            input.device(),
            gps_latest,
            gps_history,
            "latitude",
            fmt=lambda value: f"{value:.5f}",
        )

    @render.ui
    def gps_lon_spark():
        return _gps_spark(
            input.device(),
            gps_latest,
            gps_history,
            "longitude",
            fmt=lambda value: f"{value:.5f}",
        )

    @render.ui
    def gps_accuracy_spark():
        return _gps_spark(
            input.device(),
            gps_latest,
            gps_history,
            "accuracy",
            fmt=lambda value: f"{value:.1f} m",
        )

    @render.ui
    def gps_altitude_spark():
        return _gps_spark(
            input.device(),
            gps_latest,
            gps_history,
            "altitude",
            fmt=lambda value: f"{value:.1f} m",
        )

    @render.ui
    def gps_speed_spark():
        return _gps_spark(
            input.device(),
            gps_latest,
            gps_history,
            "speed",
            fmt=lambda value: f"{value:.1f} m/s",
        )
