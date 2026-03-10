from pathlib import Path

from app import config


def test_devices_match_checked_in_config() -> None:
    assert config.DEVICES == {
        "10": {
            "label": "RPi4 (192.168.121.10)",
            "default": "http://127.0.0.1:8010/10/pulse/main/default",
            "pulse_metrics": {
                "temp": {"field": "temp", "label": "Temperature", "unit": "°C"}
            },
        },
        "11": {
            "label": "RPi4 (192.168.121.11)",
            "default": "http://127.0.0.1:8010/11/pulse/main/default",
            "pulse_metrics": {
                "temp": {"field": "temp", "label": "Temperature", "unit": "°C"}
            },
        },
        "pixel-7": {
            "label": "Pixel 7 (100.81.55.124)",
            "default": "http://127.0.0.1:8010/pixel-7/pulse/main/default",
            "pulse_metrics": {
                "temp": {
                    "field": "thermal_headroom",
                    "label": "Thermal Headroom",
                    "unit": None,
                }
            },
        },
    }


def test_sen66_devices_match_checked_in_config() -> None:
    assert config.SEN66_DEVICES == {
        "11": {
            "label": "RPi4 (192.168.121.11)",
            "default": "http://127.0.0.1:8010/11/sen66/main/default",
            "number_concentration": "http://127.0.0.1:8010/11/sen66/main/number_concentration",
        }
    }


def test_h10_devices_match_checked_in_config() -> None:
    assert config.H10_DEVICES == {
        "11:EA78562C": {
            "label": "EA78562C",
            "device": "11",
            "h10_id": "EA78562C",
            "default": "http://127.0.0.1:8010/11/h10/EA78562C/default",
            "ecg": "http://127.0.0.1:8010/11/h10/EA78562C/ecg",
            "acc": "http://127.0.0.1:8010/11/h10/EA78562C/acc",
        },
        "pixel-7:6FFF5628": {
            "label": "6FFF5628",
            "device": "pixel-7",
            "h10_id": "6FFF5628",
            "default": "http://127.0.0.1:8010/pixel-7/h10/6FFF5628/default",
            "ecg": "http://127.0.0.1:8010/pixel-7/h10/6FFF5628/ecg",
            "acc": "http://127.0.0.1:8010/pixel-7/h10/6FFF5628/acc",
        },
    }
    assert config.H10_DEVICE_OPTIONS == {
        "11": {"11:EA78562C": "EA78562C"},
        "pixel-7": {"pixel-7:6FFF5628": "6FFF5628"},
    }
    assert config.H10_DEFAULTS == {
        "11": "11:EA78562C",
        "pixel-7": "pixel-7:6FFF5628",
    }
    assert config.H10_ACC_DYNAMIC_WINDOW_S == 0.5


def test_gps_devices_match_checked_in_config() -> None:
    assert config.GPS_DEVICES == {
        "pixel-7": {
            "label": "Pixel 7 (100.81.55.124)",
            "default": "http://127.0.0.1:8010/pixel-7/gps/main/default",
        }
    }


def test_all_devices_and_defaults_match_current_config() -> None:
    assert config.ALL_DEVICES == {
        "10": "RPi4 (192.168.121.10)",
        "11": "RPi4 (192.168.121.11)",
        "pixel-7": "Pixel 7 (100.81.55.124)",
    }
    assert config.ALL_DEVICES_DEFAULT == "11"


def test_chart_option_mappings_are_stable() -> None:
    assert config.PULSE_CHARTS["net"] == "Download & Upload (KB/s)"
    assert config.SEN66_CHARTS["pm_nc"] == "PM Number Concentration (#/cm³)"
    assert config.H10_CHARTS["rr"] == "Last RR Interval (ms)"
    assert config.H10_CHARTS["ecg"] == "ECG (µV)"
    assert config.H10_CHARTS["acc_dyn"] == "Mean Dynamic Acceleration"
    assert config.H10_CHARTS["motion"] == "Acceleration Axes"


def test_load_raw_config_reads_explicit_path(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        'relay_base_url: http://example\n'
        'devices:\n'
        '  "12":\n'
        '    pulse: {}\n'
        '    sen66: {}\n'
        '    gps: {}\n'
        '    h10:\n'
        '      "strap-a": {}\n',
        encoding="utf-8",
    )

    loaded = config.load_raw_config(config_path)

    assert loaded["relay_base_url"] == "http://example"
    assert loaded["devices"]["12"]["pulse"] == {}
    assert loaded["devices"]["12"]["sen66"] == {}
    assert loaded["devices"]["12"]["gps"] == {}
    assert loaded["devices"]["12"]["h10"]["strap-a"] == {}


def test_build_settings_derives_urls_from_structured_config() -> None:
    settings = config.build_settings(
        {
            "relay_base_url": "http://example",
            "devices": {
                "12": {
                    "label": "Lab Pi",
                    "pulse": {},
                    "sen66": {},
                    "gps": {},
                    "h10": {
                        "strap-a": {"label": "Test H10 A"},
                        "strap-b": {},
                    },
                }
            },
        }
    )

    assert settings["devices"] == {
        "12": {
            "label": "Lab Pi",
            "default": "http://example/12/pulse/main/default",
            "pulse_metrics": {
                "temp": {"field": "temp", "label": "Temperature", "unit": "°C"}
            },
        }
    }
    assert settings["sen66_devices"] == {
        "12": {
            "label": "Lab Pi",
            "default": "http://example/12/sen66/main/default",
            "number_concentration": "http://example/12/sen66/main/number_concentration",
        }
    }
    assert settings["gps_devices"] == {
        "12": {
            "label": "Lab Pi",
            "default": "http://example/12/gps/main/default",
        }
    }
    assert settings["h10_devices"] == {
        "12:strap-a": {
            "label": "Test H10 A",
            "device": "12",
            "h10_id": "strap-a",
            "default": "http://example/12/h10/strap-a/default",
            "ecg": "http://example/12/h10/strap-a/ecg",
            "acc": "http://example/12/h10/strap-a/acc",
        },
        "12:strap-b": {
            "label": "strap-b",
            "device": "12",
            "h10_id": "strap-b",
            "default": "http://example/12/h10/strap-b/default",
            "ecg": "http://example/12/h10/strap-b/ecg",
            "acc": "http://example/12/h10/strap-b/acc",
        },
    }
    assert settings["h10_device_options"] == {
        "12": {
            "12:strap-a": "Test H10 A",
            "12:strap-b": "strap-b",
        }
    }
    assert settings["h10_defaults"] == {"12": "12:strap-a"}
    assert settings["all_devices"] == {"12": "Lab Pi"}
    assert settings["all_devices_default"] == "12"


def test_build_settings_applies_pulse_metric_overrides() -> None:
    settings = config.build_settings(
        {
            "devices": {
                "pixel-7": {
                    "pulse": {
                        "metrics": {
                            "temp": {
                                "field": "thermal_headroom",
                                "label": "Thermal Headroom",
                                "unit": None,
                            }
                        }
                    }
                }
            }
        }
    )

    assert settings["devices"]["pixel-7"]["pulse_metrics"] == {
        "temp": {
            "field": "thermal_headroom",
            "label": "Thermal Headroom",
            "unit": None,
        }
    }


def test_pulse_metric_returns_default_and_overridden_specs() -> None:
    assert config.pulse_metric("10", "temp") == {
        "field": "temp",
        "label": "Temperature",
        "unit": "°C",
    }
    assert config.pulse_metric("pixel-7", "temp") == {
        "field": "thermal_headroom",
        "label": "Thermal Headroom",
        "unit": None,
    }
