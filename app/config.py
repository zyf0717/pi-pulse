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


def build_settings(raw_config: Mapping) -> dict:
    pulse_config = raw_config.get("pi-pulse", {})
    sen66_config = raw_config.get("sen66", {})
    h10_config = raw_config.get("h10", {})

    pulse_devices = {
        key: {"label": _device_label(key), "url": value["stream"]}
        for key, value in pulse_config.items()
    }
    sen66_devices = {
        key: {
            "label": _device_label(key),
            "stream": value["stream"],
            "nc_stream": value["nc-stream"],
        }
        for key, value in sen66_config.items()
    }
    h10_devices = {
        key: {
            "label": _device_label(key),
            "stream": value["stream"],
            "ecg_stream": value.get("ecg-stream"),
            "acc_stream": value.get("acc-stream"),
        }
        for key, value in h10_config.items()
    }
    all_devices = {
        key: _device_label(key)
        for key in sorted(set(pulse_devices) | set(sen66_devices) | set(h10_devices))
    }
    return {
        "devices": pulse_devices,
        "sen66_devices": sen66_devices,
        "sen66_default_dev": next(iter(sen66_devices), None),
        "h10_devices": h10_devices,
        "h10_default_dev": next(iter(h10_devices), None),
        "all_devices": all_devices,
        "all_devices_default": "11",
    }


_SETTINGS = build_settings(load_raw_config())

DEVICES = _SETTINGS["devices"]
SEN66_DEVICES = _SETTINGS["sen66_devices"]
SEN66_DEFAULT_DEV = _SETTINGS["sen66_default_dev"]
H10_DEVICES = _SETTINGS["h10_devices"]
H10_DEFAULT_DEV = _SETTINGS["h10_default_dev"]
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
