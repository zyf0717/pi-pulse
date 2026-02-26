from pathlib import Path

import yaml

_CONFIG_PATH = Path(__file__).parent / "config.yaml"
with _CONFIG_PATH.open() as _f:
    _CONFIG = yaml.safe_load(_f)

# pi-pulse: device-keyed dict from config
DEVICES = {
    k: {"label": f"Device {k} (192.168.121.{k})", "url": v["stream"]}
    for k, v in _CONFIG["pi-pulse"].items()
}

# sen66: device-keyed dict; each entry has two endpoints
SEN66_DEVICES = {
    k: {
        "label": f"Device {k} (192.168.121.{k})",
        "stream": v["stream"],
        "nc_stream": v["nc-stream"],
    }
    for k, v in _CONFIG["sen66"].items()
}
SEN66_DEFAULT_DEV = next(iter(SEN66_DEVICES))

# Combined device list across all tabs (sorted by key)
ALL_DEVICES = {
    k: f"Device {k} (192.168.121.{k})"
    for k in sorted(set(DEVICES) | set(SEN66_DEVICES))
}
ALL_DEVICES_DEFAULT = "11"

PULSE_CHARTS = {
    "cpu": "CPU Usage (%)",
    "mem": "Memory Usage (%)",
    "temp": "Temperature (°C)",
}

SEN66_CHARTS = {
    "temp_hum": "Temperature & Humidity",
    "co2": "CO₂",
    "voc_nox": "VOC & NOx",
    "pm_mass": "PM Mass Concentration (µg/m³)",
    "pm_nc": "PM Number Concentration (#/cm³)",
}
