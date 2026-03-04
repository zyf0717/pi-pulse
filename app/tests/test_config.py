from pathlib import Path

from app import config


def test_devices_match_checked_in_config() -> None:
    assert config.DEVICES == {
        "10": {
            "label": "10 (192.168.121.10)",
            "url": "http://192.168.121.10:8001/stream",
        },
        "11": {
            "label": "11 (192.168.121.11)",
            "url": "http://192.168.121.11:8001/stream",
        },
    }


def test_sen66_devices_match_checked_in_config() -> None:
    assert config.SEN66_DEVICES == {
        "11": {
            "label": "11 (192.168.121.11)",
            "stream": "http://192.168.121.11:8002/stream",
            "nc_stream": "http://192.168.121.11:8002/nc-stream",
        }
    }
    assert config.SEN66_DEFAULT_DEV == "11"


def test_h10_devices_match_checked_in_config() -> None:
    assert config.H10_DEVICES == {
        "11:6FFF5628": {
            "label": "6FFF5628",
            "device": "11",
            "h10_id": "6FFF5628",
            "stream": "http://192.168.121.11:8003/h10/6FFF5628/stream",
            "ecg_stream": "http://192.168.121.11:8003/h10/6FFF5628/ecg-stream",
            "acc_stream": "http://192.168.121.11:8003/h10/6FFF5628/acc-stream",
        }
    }
    assert config.H10_DEVICE_OPTIONS == {"11": {"11:6FFF5628": "6FFF5628"}}
    assert config.H10_DEFAULTS == {"11": "11:6FFF5628"}
    assert config.H10_ACC_DYNAMIC_WINDOW_S == 0.5


def test_all_devices_and_defaults_match_current_config() -> None:
    assert config.ALL_DEVICES == {
        "10": "10 (192.168.121.10)",
        "11": "11 (192.168.121.11)",
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
        'devices:\n  "12":\n    pulse:\n      stream: http://example/pulse\n    sen66:\n      stream: http://example/sen66\n      nc-stream: http://example/sen66/nc\n    h10:\n      "strap-a":\n        stream: http://example/h10/strap-a/stream\n        ecg-stream: http://example/h10/strap-a/ecg-stream\n        acc-stream: http://example/h10/strap-a/acc-stream\n',
        encoding="utf-8",
    )

    loaded = config.load_raw_config(config_path)

    assert loaded["devices"]["12"]["pulse"]["stream"] == "http://example/pulse"
    assert loaded["devices"]["12"]["sen66"]["nc-stream"] == "http://example/sen66/nc"
    assert loaded["devices"]["12"]["h10"]["strap-a"]["stream"] == "http://example/h10/strap-a/stream"
    assert loaded["devices"]["12"]["h10"]["strap-a"]["ecg-stream"] == "http://example/h10/strap-a/ecg-stream"
    assert loaded["devices"]["12"]["h10"]["strap-a"]["acc-stream"] == "http://example/h10/strap-a/acc-stream"


def test_build_settings_shapes_device_maps_and_nests_h10_by_node() -> None:
    settings = config.build_settings(
        {
            "devices": {
                "12": {
                    "pulse": {"stream": "http://example/pulse"},
                    "sen66": {
                        "stream": "http://example/sen66",
                        "nc-stream": "http://example/sen66/nc",
                    },
                    "h10": {
                        "strap-a": {
                            "label": "Test H10 A",
                            "stream": "http://example/h10/strap-a/stream",
                            "ecg-stream": "http://example/h10/strap-a/ecg-stream",
                            "acc-stream": "http://example/h10/strap-a/acc-stream",
                        },
                        "strap-b": {
                            "stream": "http://example/h10/strap-b/stream",
                        },
                    },
                }
            },
        }
    )

    assert settings["devices"] == {
        "12": {"label": "12 (192.168.121.12)", "url": "http://example/pulse"}
    }
    assert settings["sen66_devices"] == {
        "12": {
            "label": "12 (192.168.121.12)",
            "stream": "http://example/sen66",
            "nc_stream": "http://example/sen66/nc",
        }
    }
    assert settings["sen66_default_dev"] == "12"
    assert settings["h10_devices"] == {
        "12:strap-a": {
            "label": "Test H10 A",
            "device": "12",
            "h10_id": "strap-a",
            "stream": "http://example/h10/strap-a/stream",
            "ecg_stream": "http://example/h10/strap-a/ecg-stream",
            "acc_stream": "http://example/h10/strap-a/acc-stream",
        },
        "12:strap-b": {
            "label": "strap-b",
            "device": "12",
            "h10_id": "strap-b",
            "stream": "http://example/h10/strap-b/stream",
            "ecg_stream": None,
            "acc_stream": None,
        }
    }
    assert settings["h10_device_options"] == {
        "12": {
            "12:strap-a": "Test H10 A",
            "12:strap-b": "strap-b",
        }
    }
    assert settings["h10_defaults"] == {"12": "12:strap-a"}
    assert settings["all_devices"] == {"12": "12 (192.168.121.12)"}
    assert settings["all_devices_default"] == "12"
