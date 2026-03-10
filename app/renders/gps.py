"""GPS renders: value cards only."""

from collections import deque

from shiny import reactive, render, ui

from app.config import GPS_DEVICES
from app.renders.render_utils import metric_value, sparkline_values
from app.sparkline import sparkline


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
        return ui.HTML("")
    return sparkline(values, fmt=fmt) if fmt else sparkline(values)


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

    @render.text
    def gps_timestamp_val():
        if input.device() not in GPS_DEVICES:
            return "N/A"
        value = gps_latest[input.device()]().get("timestamp", "")
        return str(value or "N/A")

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
