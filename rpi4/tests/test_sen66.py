"""Tests for rpi4/sen66.py.

Covers:
- _safe                      — rounding, None value, exception swallowing
- read_environmental         — key presence, value types, sensor exception path
- read_number_concentration  — key presence, value types, sensor exception path
- environmental_stream       — SSE framing verified via max_frames=1
- number_concentration_stream — SSE framing verified via max_frames=1
- FastAPI /health            — route response body
"""

import asyncio
import importlib.util
import json
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

RPI4_DIR = Path(__file__).resolve().parents[1]


# ── module loader ─────────────────────────────────────────────────────────────


def _load_sen66():
    """Fresh import of sen66.py without actual hardware interaction."""
    spec = importlib.util.spec_from_file_location(
        "rpi4_sen66_fresh", RPI4_DIR / "sen66.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ── sensor factory ────────────────────────────────────────────────────────────


def _sig(v):
    """Fake Sensirion signal object with a .value attribute."""
    return SimpleNamespace(value=v)


def _make_fake_sensor():
    """Return a MagicMock sensor with realistic read_xxx_values return values."""
    sensor = MagicMock()
    sensor.read_measured_values.return_value = (
        _sig(5.1),  # pm1p0
        _sig(10.2),  # pm2p5
        _sig(11.3),  # pm4p0
        _sig(12.4),  # pm10p0
        _sig(45.0),  # humidity
        _sig(22.5),  # temperature
        _sig(100.0),  # voc_index
        _sig(1.0),  # nox_index
        _sig(412.0),  # co2
    )
    sensor.read_number_concentration_values.return_value = (
        _sig(0.5),  # nc_pm0_5
        _sig(1.0),  # nc_pm1_0
        _sig(2.0),  # nc_pm2_5
        _sig(3.0),  # nc_pm4_0
        _sig(4.0),  # nc_pm10_0
    )
    return sensor


# ── no-op lifespan for FastAPI tests ─────────────────────────────────────────


@asynccontextmanager
async def _noop_lifespan(app):
    """Substitute lifespan that skips all hardware initialisation."""
    yield


# ── _safe ─────────────────────────────────────────────────────────────────────


def test_safe_returns_rounded_float():
    sen66 = _load_sen66()
    assert sen66._safe(_sig(12.3456)) == 12.346


def test_safe_rounds_to_three_decimal_places():
    sen66 = _load_sen66()
    assert sen66._safe(_sig(1.23456789)) == 1.235


def test_safe_returns_none_for_none_value():
    sen66 = _load_sen66()
    assert sen66._safe(_sig(None)) is None


def test_safe_returns_none_on_attribute_exception():
    """Any exception raised inside the signal access must be swallowed."""
    sen66 = _load_sen66()

    class BadSignal:
        @property
        def value(self):
            raise RuntimeError("hardware fault")

    assert sen66._safe(BadSignal()) is None


def test_safe_integer_value_is_returned_as_numeric():
    """round(int, 3) returns int in Python — _safe does not coerce to float."""
    sen66 = _load_sen66()
    result = sen66._safe(_sig(100))
    assert result == 100


# ── read_environmental ────────────────────────────────────────────────────────
# Pure sync function — no async or TestClient needed.


def test_read_environmental_returns_expected_keys():
    sen66 = _load_sen66()
    payload = sen66.read_environmental(_make_fake_sensor())
    for key in (
        "temperature_c",
        "humidity_rh",
        "co2_ppm",
        "voc_index",
        "nox_index",
        "pm1_0_ugm3",
        "pm2_5_ugm3",
        "pm4_0_ugm3",
        "pm10_0_ugm3",
    ):
        assert key in payload, f"Missing key: {key}"


def test_read_environmental_values_are_floats_or_none():
    sen66 = _load_sen66()
    payload = sen66.read_environmental(_make_fake_sensor())
    for v in payload.values():
        assert v is None or isinstance(
            v, (int, float)
        ), f"Unexpected value type: {type(v)}"


def test_read_environmental_known_temperature_value():
    """Spot-check that _safe() is called and values round-trip correctly."""
    sen66 = _load_sen66()
    payload = sen66.read_environmental(_make_fake_sensor())
    assert payload["temperature_c"] == 22.5
    assert payload["humidity_rh"] == 45.0
    assert payload["co2_ppm"] == 412.0


def test_read_environmental_sensor_exception_returns_error_dict():
    """On sensor error, payload must contain 'error' key, not raise."""
    sen66 = _load_sen66()
    bad = MagicMock()
    bad.read_measured_values.side_effect = RuntimeError("I2C timeout")
    payload = sen66.read_environmental(bad)
    assert "error" in payload
    assert "I2C timeout" in payload["error"]


# ── read_number_concentration ─────────────────────────────────────────────────


def test_read_number_concentration_returns_expected_keys():
    sen66 = _load_sen66()
    payload = sen66.read_number_concentration(_make_fake_sensor())
    for key in (
        "nc_pm0_5_pcm3",
        "nc_pm1_0_pcm3",
        "nc_pm2_5_pcm3",
        "nc_pm4_0_pcm3",
        "nc_pm10_0_pcm3",
    ):
        assert key in payload, f"Missing key: {key}"


def test_read_number_concentration_values_are_floats_or_none():
    sen66 = _load_sen66()
    payload = sen66.read_number_concentration(_make_fake_sensor())
    for v in payload.values():
        assert v is None or isinstance(
            v, (int, float)
        ), f"Unexpected value type: {type(v)}"


def test_read_number_concentration_known_values():
    sen66 = _load_sen66()
    payload = sen66.read_number_concentration(_make_fake_sensor())
    assert payload["nc_pm0_5_pcm3"] == 0.5
    assert payload["nc_pm10_0_pcm3"] == 4.0


def test_read_number_concentration_sensor_exception_returns_error_dict():
    sen66 = _load_sen66()
    bad = MagicMock()
    bad.read_number_concentration_values.side_effect = RuntimeError("bus error")
    payload = sen66.read_number_concentration(bad)
    assert "error" in payload
    assert "bus error" in payload["error"]


# ── environmental_stream — SSE framing ────────────────────────────────────────
# max_frames=1 makes the generator self-terminating; no cancellation needed.


async def _collect_frames(gen_coro, n):
    frames = []
    async for raw in gen_coro:
        frames.append(raw)
    return frames


def test_environmental_stream_single_frame_has_sse_prefix():
    sen66 = _load_sen66()
    sen66.sensor = _make_fake_sensor()
    frames = asyncio.run(_collect_frames(sen66.environmental_stream(max_frames=1), 1))
    assert len(frames) == 1
    assert frames[0].startswith("data: ")


def test_environmental_stream_single_frame_is_valid_json():
    sen66 = _load_sen66()
    sen66.sensor = _make_fake_sensor()
    frames = asyncio.run(_collect_frames(sen66.environmental_stream(max_frames=1), 1))
    payload = json.loads(frames[0][len("data: ") :].strip())
    assert "temperature_c" in payload
    assert "co2_ppm" in payload


def test_environmental_stream_terminates_after_max_frames():
    sen66 = _load_sen66()
    sen66.sensor = _make_fake_sensor()

    async def _count(n):
        count = 0
        async for _ in sen66.environmental_stream(max_frames=n):
            count += 1
        return count

    assert asyncio.run(_count(3)) == 3


def test_environmental_stream_sensor_error_yields_error_frame():
    sen66 = _load_sen66()
    bad = MagicMock()
    bad.read_measured_values.side_effect = RuntimeError("I2C timeout")
    sen66.sensor = bad
    frames = asyncio.run(_collect_frames(sen66.environmental_stream(max_frames=1), 1))
    payload = json.loads(frames[0][len("data: ") :].strip())
    assert "error" in payload


# ── number_concentration_stream — SSE framing ─────────────────────────────────


def test_nc_stream_single_frame_has_sse_prefix():
    sen66 = _load_sen66()
    sen66.sensor = _make_fake_sensor()
    frames = asyncio.run(
        _collect_frames(sen66.number_concentration_stream(max_frames=1), 1)
    )
    assert len(frames) == 1
    assert frames[0].startswith("data: ")


def test_nc_stream_single_frame_is_valid_json():
    sen66 = _load_sen66()
    sen66.sensor = _make_fake_sensor()
    frames = asyncio.run(
        _collect_frames(sen66.number_concentration_stream(max_frames=1), 1)
    )
    payload = json.loads(frames[0][len("data: ") :].strip())
    assert "nc_pm0_5_pcm3" in payload
    assert "nc_pm10_0_pcm3" in payload


def test_nc_stream_terminates_after_max_frames():
    sen66 = _load_sen66()
    sen66.sensor = _make_fake_sensor()

    async def _count(n):
        count = 0
        async for _ in sen66.number_concentration_stream(max_frames=n):
            count += 1
        return count

    assert asyncio.run(_count(2)) == 2


def test_nc_stream_sensor_error_yields_error_frame():
    sen66 = _load_sen66()
    bad = MagicMock()
    bad.read_number_concentration_values.side_effect = RuntimeError("bus error")
    sen66.sensor = bad
    frames = asyncio.run(
        _collect_frames(sen66.number_concentration_stream(max_frames=1), 1)
    )
    payload = json.loads(frames[0][len("data: ") :].strip())
    assert "error" in payload


# ── FastAPI /health ───────────────────────────────────────────────────────────


def test_health_endpoint_returns_expected_body():
    from starlette.testclient import TestClient

    sen66 = _load_sen66()
    sen66.app.router.lifespan_context = _noop_lifespan
    with TestClient(sen66.app) as client:
        resp = client.get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "pulsing"
    assert body["sensor"] == "SEN66"
