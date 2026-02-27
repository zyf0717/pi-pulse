import config


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
