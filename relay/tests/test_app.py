import importlib.util
import asyncio
import json
from pathlib import Path


RELAY_DIR = Path(__file__).resolve().parents[1]


def _load_relay_app():
    spec = importlib.util.spec_from_file_location(
        "relay_app_under_test", RELAY_DIR / "server.py"
    )
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


async def _collect_frames(relay, stream_key: str, n: int):
    frames = []
    async for frame in relay._relay_stream(stream_key, max_frames=n):
        frames.append(frame)
    return frames


def test_health_reports_empty_registry_initially():
    relay = _load_relay_app()
    response = asyncio.run(relay.health())

    assert response == {"status": "ok", "streams": 0, "subscribers": 0}


def test_post_then_get_replays_latest_pulse_payload():
    relay = _load_relay_app()
    payload = {"cpu": 45.2, "mem": 62.1}
    post_response = asyncio.run(relay.ingest_pulse("10", payload))

    assert post_response == {"ok": True}

    frames = asyncio.run(_collect_frames(relay, "pulse/10/stream", 1))

    assert frames == [f"data: {json.dumps(payload)}\n\n"]


def test_h10_ecg_route_keeps_payload_shape_and_path_identity():
    relay = _load_relay_app()
    payload = {"samples_uv": [10, 12, 8, -4], "sample_rate_hz": 130}
    asyncio.run(relay.ingest_h10_ecg("6FFF5628", payload))

    frames = asyncio.run(_collect_frames(relay, "h10/6FFF5628/ecg-stream", 1))

    assert frames == [f"data: {json.dumps(payload)}\n\n"]


def test_latest_payload_is_updated_on_second_post():
    relay = _load_relay_app()
    asyncio.run(relay.ingest_sen66("11", {"temperature_c": 22.5}))
    asyncio.run(relay.ingest_sen66("11", {"temperature_c": 23.0}))

    frames = asyncio.run(_collect_frames(relay, "sen66/11/stream", 1))

    assert frames == ['data: {"temperature_c": 23.0}\n\n']
