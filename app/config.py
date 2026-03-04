from collections.abc import Mapping
from pathlib import Path

import yaml

_CONFIG_PATH = Path(__file__).parent / "config.yaml"
_IP_PREFIX = "192.168.121."


def load_raw_config(config_path: Path = _CONFIG_PATH) -> dict:
    with config_path.open() as config_file:
        return yaml.safe_load(config_file) or {}


def _device_label(key: str) -> str:
    return f"{key} ({_IP_PREFIX}{key})"


def _node_label(key: str, value: Mapping) -> str:
    label = value.get("label")
    if label:
        return str(label)
    if key.isdigit():
        return _device_label(key)
    return key


def _h10_stream_key(node_key: str, h10_key: str) -> str:
    return f"{node_key}:{h10_key}"


def build_settings(raw_config: Mapping) -> dict:
    device_config = raw_config.get("devices", {})

    all_devices: dict[str, str] = {}
    pulse_devices: dict[str, dict] = {}
    sen66_devices: dict[str, dict] = {}
    h10_devices: dict[str, dict] = {}
    h10_device_options: dict[str, dict[str, str]] = {}
    h10_defaults: dict[str, str | None] = {}

    for node_key, node_value in device_config.items():
        node_label = _node_label(node_key, node_value)
        all_devices[node_key] = node_label

        pulse_value = node_value.get("pulse")
        if isinstance(pulse_value, Mapping):
            pulse_devices[node_key] = {"label": node_label, "url": pulse_value["stream"]}

        sen66_value = node_value.get("sen66")
        if isinstance(sen66_value, Mapping):
            sen66_devices[node_key] = {
                "label": node_label,
                "stream": sen66_value["stream"],
                "nc_stream": sen66_value["nc-stream"],
            }

        h10_options: dict[str, str] = {}
        h10_streams = node_value.get("h10", {})
        if not isinstance(h10_streams, Mapping):
            h10_streams = {}
        for h10_key, h10_value in h10_streams.items():
            if not isinstance(h10_value, Mapping):
                continue
            stream_key = _h10_stream_key(node_key, h10_key)
            label = str(h10_value.get("label") or h10_key)
            h10_devices[stream_key] = {
                "label": label,
                "device": node_key,
                "h10_id": h10_key,
                "stream": h10_value["stream"],
                "ecg_stream": h10_value.get("ecg-stream"),
                "acc_stream": h10_value.get("acc-stream"),
            }
            h10_options[stream_key] = label
        if h10_options:
            h10_device_options[node_key] = h10_options
            h10_defaults[node_key] = next(iter(h10_options))

    all_devices_default = "11" if "11" in all_devices else next(iter(all_devices), None)
    return {
        "devices": pulse_devices,
        "sen66_devices": sen66_devices,
        "sen66_default_dev": next(iter(sen66_devices), None),
        "h10_devices": h10_devices,
        "h10_device_options": h10_device_options,
        "h10_defaults": h10_defaults,
        "all_devices": all_devices,
        "all_devices_default": all_devices_default,
    }


_SETTINGS = build_settings(load_raw_config())

DEVICES = _SETTINGS["devices"]
SEN66_DEVICES = _SETTINGS["sen66_devices"]
SEN66_DEFAULT_DEV = _SETTINGS["sen66_default_dev"]
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
