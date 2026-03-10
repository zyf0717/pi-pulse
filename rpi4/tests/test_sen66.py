"""Tests for rpi4/sen66.py."""

import asyncio
import importlib.util
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

RPI4_DIR = Path(__file__).resolve().parents[1]


def _load_sen66():
    spec = importlib.util.spec_from_file_location(
        "rpi4_sen66_fresh", RPI4_DIR / "sen66.py"
    )
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


def _sig(v):
    return SimpleNamespace(value=v)


def _make_fake_sensor():
    sensor = MagicMock()
    sensor.read_measured_values.return_value = (
        _sig(5.1),
        _sig(10.2),
        _sig(11.3),
        _sig(12.4),
        _sig(45.0),
        _sig(22.5),
        _sig(100.0),
        _sig(1.0),
        _sig(412.0),
    )
    sensor.read_number_concentration_values.return_value = (
        _sig(0.5),
        _sig(1.0),
        _sig(2.0),
        _sig(3.0),
        _sig(4.0),
    )
    return sensor


def test_safe_returns_rounded_float():
    sen66 = _load_sen66()
    assert sen66._safe(_sig(12.3456)) == 12.346


def test_safe_returns_none_for_none_value():
    sen66 = _load_sen66()
    assert sen66._safe(_sig(None)) is None


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
        assert key in payload


def test_read_environmental_sensor_exception_returns_error_dict():
    sen66 = _load_sen66()
    bad = MagicMock()
    bad.read_measured_values.side_effect = RuntimeError("I2C timeout")
    payload = sen66.read_environmental(bad)
    assert "error" in payload
    assert "I2C timeout" in payload["error"]


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
        assert key in payload


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


def test_push_environmental_loop_posts_to_relay():
    sen66 = _load_sen66()
    sensor = _make_fake_sensor()
    instances = []

    def _client_factory(*args, **kwargs):
        return _FakeAsyncClient(instances)

    asyncio.run(
        sen66.push_environmental_loop(
            sensor,
            node_id="11",
            max_frames=1,
            client_factory=_client_factory,
        )
    )

    assert len(instances) == 1
    assert instances[0].posts == [
        (
            "http://192.168.121.1:8010/ingest/11/sen66/main/default",
            sen66.read_environmental(sensor),
        )
    ]


def test_push_number_concentration_loop_posts_to_relay():
    sen66 = _load_sen66()
    sensor = _make_fake_sensor()
    instances = []

    def _client_factory(*args, **kwargs):
        return _FakeAsyncClient(instances)

    asyncio.run(
        sen66.push_number_concentration_loop(
            sensor,
            node_id="11",
            max_frames=1,
            client_factory=_client_factory,
        )
    )

    assert len(instances) == 1
    assert instances[0].posts == [
        (
            "http://192.168.121.1:8010/ingest/11/sen66/main/number_concentration",
            sen66.read_number_concentration(sensor),
        )
    ]


def test_push_environmental_loop_logs_failures():
    sen66 = _load_sen66()
    sensor = _make_fake_sensor()

    class _FailingClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def post(self, url, json):
            raise RuntimeError("network down")

    with patch.object(sen66, "log_post_failure") as log_post_failure:
        asyncio.run(
            sen66.push_environmental_loop(
                sensor,
                node_id="11",
                max_frames=1,
                client_factory=lambda *args, **kwargs: _FailingClient(),
            )
        )

    log_post_failure.assert_called_once()
