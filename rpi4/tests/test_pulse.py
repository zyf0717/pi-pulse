"""Tests for rpi4/pulse.py."""

import asyncio
import importlib.util
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import mock_open, patch

RPI4_DIR = Path(__file__).resolve().parents[1]


def _load_pulse():
    spec = importlib.util.spec_from_file_location(
        "rpi4_pulse_fresh", RPI4_DIR / "pulse.py"
    )
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


def test_read_soc_temp_c_reads_sysfs_millidegrees():
    pulse = _load_pulse()
    with patch("builtins.open", mock_open(read_data="52000")):
        result = pulse.read_soc_temp_c()
    assert result == 52.0


def test_read_soc_temp_c_strips_whitespace():
    pulse = _load_pulse()
    with patch("builtins.open", mock_open(read_data="38500\n")):
        result = pulse.read_soc_temp_c()
    assert result == 38.5


def test_read_soc_temp_c_falls_back_to_psutil_cpu_thermal():
    pulse = _load_pulse()
    fake_entry = SimpleNamespace(current=67.25)
    with patch("builtins.open", side_effect=OSError):
        with patch.object(
            pulse.psutil, "sensors_temperatures", return_value={"cpu_thermal": [fake_entry]}
        ):
            result = pulse.read_soc_temp_c()
    assert result == 67.2


def test_read_soc_temp_c_returns_none_when_nothing_available():
    pulse = _load_pulse()
    with patch("builtins.open", side_effect=OSError):
        with patch.object(pulse.psutil, "sensors_temperatures", return_value={}):
            result = pulse.read_soc_temp_c()
    assert result is None


def _io(rx: int, tx: int):
    return SimpleNamespace(bytes_recv=rx, bytes_sent=tx)


def test_get_net_totals_excludes_loopback_and_down_interfaces():
    pulse = _load_pulse()
    pernic = {"lo": _io(99, 99), "eth0": _io(5_000, 3_000), "wlan0": _io(2_000, 1_000)}
    stats = {
        "lo": SimpleNamespace(isup=True),
        "eth0": SimpleNamespace(isup=True),
        "wlan0": SimpleNamespace(isup=False),
    }
    with patch.object(pulse.psutil, "net_if_stats", return_value=stats):
        result = pulse.get_net_totals(pernic)
    assert result == {"rx_bytes": 5_000, "tx_bytes": 3_000}


def test_collect_metrics_returns_expected_keys():
    pulse = _load_pulse()
    stats, new_ts, new_net = pulse.collect_metrics(
        time.monotonic(), {"rx_bytes": 0, "tx_bytes": 0}
    )
    for key in (
        "cpu",
        "mem",
        "cpu_total_pct",
        "cpu_per_core_pct",
        "cpu_freq_avg_mhz",
        "mem_pct",
        "mem_used_bytes",
        "mem_available_bytes",
        "soc_temp_c",
        "net_rx_bps_total",
        "net_tx_bps_total",
    ):
        assert key in stats
    assert new_ts > 0
    assert "rx_bytes" in new_net
    assert "tx_bytes" in new_net


class _FakeResponse:
    def raise_for_status(self):
        return None


class _FakeAsyncClient:
    def __init__(self, instances):
        self.posts = []
        instances.append(self)

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return None

    async def post(self, url, json):
        self.posts.append((url, json))
        return _FakeResponse()


def test_push_metrics_loop_posts_to_relay_with_detected_node_id():
    pulse = _load_pulse()
    payload = {"cpu": 10.0, "mem": 20.0}
    instances = []

    def _client_factory(*args, **kwargs):
        return _FakeAsyncClient(instances)

    with patch.object(pulse, "detect_node_id", return_value="10"):
        with patch.object(
            pulse,
            "collect_metrics",
            return_value=(payload, 1.0, {"rx_bytes": 1, "tx_bytes": 2}),
        ):
            with patch.object(pulse.psutil, "cpu_percent", return_value=0.0):
                with patch.object(pulse.psutil, "net_io_counters", return_value={}):
                    asyncio.run(
                        pulse.push_metrics_loop(
                            max_frames=1,
                            client_factory=_client_factory,
                        )
                    )

    assert len(instances) == 1
    assert instances[0].posts == [
        ("http://192.168.121.1:8010/ingest/pulse/10/stream", payload)
    ]


def test_push_metrics_loop_logs_post_failures_and_continues():
    pulse = _load_pulse()
    payload = {"cpu": 10.0}

    class _FailingClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def post(self, url, json):
            raise RuntimeError("network down")

    with patch.object(pulse, "detect_node_id", return_value="10"):
        with patch.object(
            pulse,
            "collect_metrics",
            return_value=(payload, 1.0, {"rx_bytes": 1, "tx_bytes": 2}),
        ):
            with patch.object(pulse.psutil, "cpu_percent", return_value=0.0):
                with patch.object(pulse.psutil, "net_io_counters", return_value={}):
                    with patch.object(pulse, "log_post_failure") as log_post_failure:
                        asyncio.run(
                            pulse.push_metrics_loop(
                                max_frames=1,
                                client_factory=lambda *args, **kwargs: _FailingClient(),
                            )
                        )

    log_post_failure.assert_called_once()
