"""Tests for rpi4/pulse.py.

Covers:
- read_soc_temp_c   — sysfs path, psutil fallback, nothing available
- get_net_totals    — loopback exclusion, down-interface filtering, multi-NIC
                      sum, net_if_stats exception path
- collect_metrics   — key presence, value ranges, network bytes non-negative
- metric_stream     — SSE framing verified via max_frames=1 (no infinite loop)
- FastAPI /health   — route response body
"""

import asyncio
import importlib.util
import json
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import mock_open, patch

RPI4_DIR = Path(__file__).resolve().parents[1]


# ── module loader ─────────────────────────────────────────────────────────────


def _load_pulse():
    """Fresh import of pulse.py each call to avoid cross-test state leakage."""
    spec = importlib.util.spec_from_file_location(
        "rpi4_pulse_fresh", RPI4_DIR / "pulse.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ── read_soc_temp_c ───────────────────────────────────────────────────────────


def test_read_soc_temp_c_reads_sysfs_millidegrees():
    """Normal path: valid millidegree value in sysfs → converted to °C."""
    pulse = _load_pulse()
    with patch("builtins.open", mock_open(read_data="52000")):
        result = pulse.read_soc_temp_c()
    assert result == 52.0


def test_read_soc_temp_c_strips_whitespace():
    """Sysfs values often contain a trailing newline."""
    pulse = _load_pulse()
    with patch("builtins.open", mock_open(read_data="38500\n")):
        result = pulse.read_soc_temp_c()
    assert result == 38.5


def test_read_soc_temp_c_falls_back_to_psutil_cpu_thermal():
    """When sysfs is unavailable, fall back to psutil cpu_thermal sensor."""
    pulse = _load_pulse()
    fake_entry = SimpleNamespace(current=67.25)
    fake_temps = {"cpu_thermal": [fake_entry]}
    with patch("builtins.open", side_effect=OSError):
        with patch.object(
            pulse.psutil, "sensors_temperatures", return_value=fake_temps
        ):
            result = pulse.read_soc_temp_c()
    assert result == 67.2


def test_read_soc_temp_c_falls_back_to_first_psutil_sensor():
    """psutil fallback uses the first entry of whichever sensor key is present."""
    pulse = _load_pulse()
    fake_temps = {"some_sensor": [SimpleNamespace(current=55.0)]}
    with patch("builtins.open", side_effect=OSError):
        with patch.object(
            pulse.psutil, "sensors_temperatures", return_value=fake_temps
        ):
            result = pulse.read_soc_temp_c()
    assert result == 55.0


def test_read_soc_temp_c_returns_none_when_nothing_available():
    """Returns None when both sysfs and psutil yield nothing."""
    pulse = _load_pulse()
    with patch("builtins.open", side_effect=OSError):
        with patch.object(pulse.psutil, "sensors_temperatures", return_value={}):
            result = pulse.read_soc_temp_c()
    assert result is None


# ── get_net_totals ────────────────────────────────────────────────────────────


def _io(rx: int, tx: int):
    return SimpleNamespace(bytes_recv=rx, bytes_sent=tx)


def test_get_net_totals_excludes_loopback():
    pulse = _load_pulse()
    pernic = {"lo": _io(9_999, 9_999), "eth0": _io(5_000, 3_000)}
    stats = {"lo": SimpleNamespace(isup=True), "eth0": SimpleNamespace(isup=True)}
    with patch.object(pulse.psutil, "net_if_stats", return_value=stats):
        result = pulse.get_net_totals(pernic)
    assert result == {"rx_bytes": 5_000, "tx_bytes": 3_000}


def test_get_net_totals_skips_down_interfaces():
    pulse = _load_pulse()
    pernic = {"eth0": _io(5_000, 3_000), "wlan0": _io(1_000, 500)}
    stats = {
        "eth0": SimpleNamespace(isup=True),
        "wlan0": SimpleNamespace(isup=False),
    }
    with patch.object(pulse.psutil, "net_if_stats", return_value=stats):
        result = pulse.get_net_totals(pernic)
    assert result == {"rx_bytes": 5_000, "tx_bytes": 3_000}


def test_get_net_totals_sums_multiple_up_interfaces():
    pulse = _load_pulse()
    pernic = {"eth0": _io(5_000, 3_000), "wlan0": _io(2_000, 1_000)}
    stats = {
        "eth0": SimpleNamespace(isup=True),
        "wlan0": SimpleNamespace(isup=True),
    }
    with patch.object(pulse.psutil, "net_if_stats", return_value=stats):
        result = pulse.get_net_totals(pernic)
    assert result == {"rx_bytes": 7_000, "tx_bytes": 4_000}


def test_get_net_totals_net_if_stats_exception_includes_all_non_lo():
    """If net_if_stats() raises, no interface is filtered as 'down'."""
    pulse = _load_pulse()
    pernic = {"eth0": _io(5_000, 3_000), "wlan0": _io(2_000, 1_000)}
    with patch.object(pulse.psutil, "net_if_stats", side_effect=RuntimeError):
        result = pulse.get_net_totals(pernic)
    assert result == {"rx_bytes": 7_000, "tx_bytes": 4_000}


def test_get_net_totals_empty_pernic():
    pulse = _load_pulse()
    with patch.object(pulse.psutil, "net_if_stats", return_value={}):
        result = pulse.get_net_totals({})
    assert result == {"rx_bytes": 0, "tx_bytes": 0}


# ── collect_metrics ───────────────────────────────────────────────────────────
# collect_metrics is a pure synchronous function — no async infrastructure needed.


def test_collect_metrics_returns_expected_keys():
    pulse = _load_pulse()
    last_ts = time.monotonic()
    last_net = {"rx_bytes": 0, "tx_bytes": 0}
    stats, new_ts, new_net = pulse.collect_metrics(last_ts, last_net)
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
        assert key in stats, f"Missing key: {key}"


def test_collect_metrics_cpu_in_range():
    pulse = _load_pulse()
    stats, _, _ = pulse.collect_metrics(time.monotonic(), {"rx_bytes": 0, "tx_bytes": 0})
    assert 0.0 <= stats["cpu_total_pct"] <= 100.0
    assert 0.0 <= stats["mem_pct"] <= 100.0


def test_collect_metrics_network_bytes_non_negative():
    pulse = _load_pulse()
    stats, _, _ = pulse.collect_metrics(time.monotonic(), {"rx_bytes": 0, "tx_bytes": 0})
    assert stats["net_rx_bps_total"] >= 0
    assert stats["net_tx_bps_total"] >= 0


def test_collect_metrics_advances_timestamp():
    pulse = _load_pulse()
    before = time.monotonic()
    _, new_ts, _ = pulse.collect_metrics(before, {"rx_bytes": 0, "tx_bytes": 0})
    assert new_ts >= before


def test_collect_metrics_net_totals_updated():
    """new_net should contain the same keys as the seed last_net."""
    pulse = _load_pulse()
    last_net = {"rx_bytes": 0, "tx_bytes": 0}
    _, _, new_net = pulse.collect_metrics(time.monotonic(), last_net)
    assert "rx_bytes" in new_net
    assert "tx_bytes" in new_net


# ── metric_stream — SSE framing ───────────────────────────────────────────────
# max_frames=1 makes the generator self-terminating; no cancellation needed.


async def _collect_one_sse_frame(pulse):
    frames = []
    async for raw in pulse.metric_stream(max_frames=1):
        frames.append(raw)
    return frames


def test_metric_stream_single_frame_has_sse_prefix():
    pulse = _load_pulse()
    frames = asyncio.run(_collect_one_sse_frame(pulse))
    assert len(frames) == 1
    assert frames[0].startswith("data: ")


def test_metric_stream_single_frame_is_valid_json():
    pulse = _load_pulse()
    frames = asyncio.run(_collect_one_sse_frame(pulse))
    raw = frames[0][len("data: "):].strip()
    data = json.loads(raw)
    assert "cpu" in data
    assert "mem" in data


def test_metric_stream_terminates_after_max_frames():
    """Generator must stop after exactly N frames — not block forever."""
    pulse = _load_pulse()

    async def _count(n):
        count = 0
        async for _ in pulse.metric_stream(max_frames=n):
            count += 1
        return count

    assert asyncio.run(_count(3)) == 3


# ── FastAPI /health ───────────────────────────────────────────────────────────


def test_health_endpoint_returns_pulsing():
    from starlette.testclient import TestClient

    pulse = _load_pulse()
    client = TestClient(pulse.app)
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "pulsing"}
