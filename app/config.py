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


def build_settings(raw_config: Mapping[str, Mapping[str, Mapping[str, str]]]) -> dict:
    pulse_devices = {
        key: {"label": _device_label(key), "url": value["stream"]}
        for key, value in raw_config["pi-pulse"].items()
    }
    sen66_devices = {
        key: {
            "label": _device_label(key),
            "stream": value["stream"],
            "nc_stream": value["nc-stream"],
        }
        for key, value in raw_config["sen66"].items()
    }
    all_devices = {
        key: _device_label(key)
        for key in sorted(set(pulse_devices) | set(sen66_devices))
    }
    return {
        "devices": pulse_devices,
        "sen66_devices": sen66_devices,
        "sen66_default_dev": next(iter(sen66_devices)),
        "all_devices": all_devices,
        "all_devices_default": "11",
    }


_SETTINGS = build_settings(load_raw_config())

DEVICES = _SETTINGS["devices"]
SEN66_DEVICES = _SETTINGS["sen66_devices"]
SEN66_DEFAULT_DEV = _SETTINGS["sen66_default_dev"]
ALL_DEVICES = _SETTINGS["all_devices"]
ALL_DEVICES_DEFAULT = _SETTINGS["all_devices_default"]

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
