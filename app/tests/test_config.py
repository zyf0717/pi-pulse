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


def test_all_devices_and_defaults_match_current_config() -> None:
    assert config.ALL_DEVICES == {
        "10": "10 (192.168.121.10)",
        "11": "11 (192.168.121.11)",
    }
    assert config.ALL_DEVICES_DEFAULT == "11"


def test_chart_option_mappings_are_stable() -> None:
    assert config.PULSE_CHARTS["net"] == "Download & Upload (KB/s)"
    assert config.SEN66_CHARTS["pm_nc"] == "PM Number Concentration (#/cm³)"


def test_load_raw_config_reads_explicit_path(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        'pi-pulse:\n  "12":\n    stream: http://example/pulse\nsen66:\n  "12":\n    stream: http://example/sen66\n    nc-stream: http://example/sen66/nc\n',
        encoding="utf-8",
    )

    loaded = config.load_raw_config(config_path)

    assert loaded["pi-pulse"]["12"]["stream"] == "http://example/pulse"
    assert loaded["sen66"]["12"]["nc-stream"] == "http://example/sen66/nc"


def test_build_settings_shapes_device_maps_and_preserves_current_default_behavior() -> None:
    settings = config.build_settings(
        {
            "pi-pulse": {"12": {"stream": "http://example/pulse"}},
            "sen66": {
                "12": {
                    "stream": "http://example/sen66",
                    "nc-stream": "http://example/sen66/nc",
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
    assert settings["all_devices"] == {"12": "12 (192.168.121.12)"}
    assert settings["all_devices_default"] == "11"
