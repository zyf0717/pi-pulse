from collections.abc import Mapping
from pathlib import Path
import sys

import yaml

if __package__ in (None, ""):
    sys.path.append(str(Path(__file__).resolve().parents[1]))

from shared.streams import DEFAULT_STREAM, stream_path

_CONFIG_PATH = Path(__file__).parent / "config.yaml"
_DEFAULT_RELAY_BASE_URL = "http://127.0.0.1:8010"
_IP_PREFIX = "192.168.121."
PULSE_DEFAULT_METRICS = {
    "temp": {"field": "temp", "label": "Temperature", "unit": "°C"}
}


def load_raw_config(config_path: Path = _CONFIG_PATH) -> dict:
    with config_path.open() as config_file:
        return yaml.safe_load(config_file) or {}


def _device_label(device_id: str) -> str:
    return f"{device_id} ({_IP_PREFIX}{device_id})"


def _node_label(device_id: str, value: Mapping) -> str:
    label = value.get("label")
    if label:
        return str(label)
    if device_id.isdigit():
        return _device_label(device_id)
    return device_id


def _relay_url(base_url: str, path: str) -> str:
    return f"{base_url.rstrip('/')}{path}"


def _copy_metric_defaults(
    defaults: Mapping[str, Mapping[str, str | None]],
) -> dict[str, dict[str, str | None]]:
    return {key: dict(spec) for key, spec in defaults.items()}


def _normalize_metric_specs(
    value: object,
    defaults: Mapping[str, Mapping[str, str | None]],
) -> dict[str, dict[str, str | None]]:
    metrics = _copy_metric_defaults(defaults)
    if not isinstance(value, Mapping):
        return metrics

    raw_metrics = value.get("metrics")
    if not isinstance(raw_metrics, Mapping):
        return metrics

    for metric_key, defaults in metrics.items():
        raw_override = raw_metrics.get(metric_key)
        if not isinstance(raw_override, Mapping):
            continue
        field = raw_override.get("field")
        label = raw_override.get("label")
        if field:
            defaults["field"] = str(field)
        if label:
            defaults["label"] = str(label)
        if "unit" in raw_override:
            unit = raw_override["unit"]
            defaults["unit"] = None if unit is None else str(unit)
    return metrics


def _pulse_metrics(value: object) -> dict[str, dict[str, str | None]]:
    return _normalize_metric_specs(value, PULSE_DEFAULT_METRICS)


def build_settings(raw_config: Mapping) -> dict:
    relay_base_url = str(
        raw_config.get("relay_base_url") or _DEFAULT_RELAY_BASE_URL
    ).rstrip("/")
    device_config = raw_config.get("devices", {})

    all_devices: dict[str, str] = {}
    devices: dict[str, dict] = {}
    sen66_devices: dict[str, dict] = {}
    gps_devices: dict[str, dict] = {}
    h10_devices: dict[str, dict] = {}
    h10_device_options: dict[str, dict[str, str]] = {}
    h10_defaults: dict[str, str] = {}

    for device_id, value in device_config.items():
        if not isinstance(value, Mapping):
            continue
        label = _node_label(device_id, value)
        all_devices[device_id] = label

        if "pulse" in value:
            pulse_value = value.get("pulse")
            devices[device_id] = {
                "label": label,
                DEFAULT_STREAM: _relay_url(
                    relay_base_url,
                    stream_path("pulse", device_id),
                ),
                "pulse_metrics": _pulse_metrics(pulse_value),
            }

        if "sen66" in value:
            sen66_devices[device_id] = {
                "label": label,
                DEFAULT_STREAM: _relay_url(
                    relay_base_url,
                    stream_path("sen66", device_id),
                ),
                "number_concentration": _relay_url(
                    relay_base_url,
                    stream_path("sen66", device_id, "number_concentration"),
                ),
            }

        if "gps" in value:
            gps_devices[device_id] = {
                "label": label,
                DEFAULT_STREAM: _relay_url(
                    relay_base_url,
                    stream_path("gps", device_id),
                ),
            }

        h10_config = value.get("h10", {})
        if not isinstance(h10_config, Mapping):
            continue
        options: dict[str, str] = {}
        for instance_id, instance_value in h10_config.items():
            instance_label = instance_id
            if isinstance(instance_value, Mapping) and instance_value.get("label"):
                instance_label = str(instance_value["label"])
            key = f"{device_id}:{instance_id}"
            h10_devices[key] = {
                "label": instance_label,
                "device": device_id,
                "h10_id": instance_id,
                DEFAULT_STREAM: _relay_url(
                    relay_base_url,
                    stream_path("h10", device_id, instance_id=instance_id),
                ),
                "ecg": _relay_url(
                    relay_base_url,
                    stream_path("h10", device_id, "ecg", instance_id=instance_id),
                ),
                "acc": _relay_url(
                    relay_base_url,
                    stream_path("h10", device_id, "acc", instance_id=instance_id),
                ),
            }
            options[key] = instance_label
        if options:
            h10_device_options[device_id] = options
            h10_defaults[device_id] = next(iter(options))

    all_devices_default = "11" if "11" in all_devices else next(iter(all_devices), None)
    return {
        "devices": devices,
        "sen66_devices": sen66_devices,
        "gps_devices": gps_devices,
        "h10_devices": h10_devices,
        "h10_device_options": h10_device_options,
        "h10_defaults": h10_defaults,
        "all_devices": all_devices,
        "all_devices_default": all_devices_default,
    }


def pulse_metric(device_id: str, metric_key: str) -> dict[str, str | None]:
    default_metric = PULSE_DEFAULT_METRICS.get(
        metric_key,
        {"field": metric_key, "label": metric_key.replace("_", " ").title(), "unit": None},
    )
    device_metrics = DEVICES.get(device_id, {}).get("pulse_metrics")
    if not isinstance(device_metrics, Mapping):
        return dict(default_metric)
    metric = device_metrics.get(metric_key)
    if not isinstance(metric, Mapping):
        return dict(default_metric)
    return {
        "field": str(metric.get("field") or default_metric["field"]),
        "label": str(metric.get("label") or default_metric["label"]),
        "unit": metric.get("unit")
        if metric.get("unit") is None
        else str(metric.get("unit")),
    }


_SETTINGS = build_settings(load_raw_config())

DEVICES = _SETTINGS["devices"]
SEN66_DEVICES = _SETTINGS["sen66_devices"]
GPS_DEVICES = _SETTINGS["gps_devices"]
H10_DEVICES = _SETTINGS["h10_devices"]
H10_DEVICE_OPTIONS = _SETTINGS["h10_device_options"]
H10_DEFAULTS = _SETTINGS["h10_defaults"]
ALL_DEVICES = _SETTINGS["all_devices"]
ALL_DEVICES_DEFAULT = _SETTINGS["all_devices_default"]
H10_ACC_DYNAMIC_WINDOW_S = 0.5

PULSE_CHARTS = {
    "cpu": "CPU Usage (%)",
    "cpu_freq": "CPU Frequency (MHz)",
    "mem": "Memory Usage (%)",
    "temp": "Temperature (°C)",
    "net": "Download & Upload (KB/s)",
}

SEN66_CHARTS = {
    "temp_hum": "Temperature & Humidity",
    "co2": "CO₂",
    "voc_nox": "VOC & NOx",
    "pm_mass": "PM Mass Concentration (µg/m³)",
    "pm_nc": "PM Number Concentration (#/cm³)",
}

H10_CHARTS = {
    "bpm": "Heart Rate (BPM)",
    "rr": "Last RR Interval (ms)",
    "ecg": "ECG (µV)",
    "acc_dyn": "Mean Dynamic Acceleration",
    "motion": "Acceleration Axes",
}

PACER_CHARTS = {
    "hr": "Heart Rate (BPM)",
    "acc": "Acceleration (mg)",
    "ppi": "PPI (ms)",
}
