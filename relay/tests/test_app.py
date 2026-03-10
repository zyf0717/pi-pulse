import importlib.util
import asyncio
import json
from pathlib import Path

from fastapi.testclient import TestClient

from shared.streams import stream_key


RELAY_DIR = Path(__file__).resolve().parents[1]


def _load_relay_app():
    spec = importlib.util.spec_from_file_location(
        "relay_app_under_test", RELAY_DIR / "server.py"
    )
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


async def _collect_frames(relay, key: str, n: int):
    frames = []
    async for frame in relay._relay_stream(key, max_frames=n):
        frames.append(frame)
    return frames


def test_health_reports_empty_registry_initially():
    relay = _load_relay_app()
    response = asyncio.run(relay.health())

    assert response == {"status": "ok", "streams": 0, "subscribers": 0}


def test_post_then_get_replays_latest_pulse_payload():
    relay = _load_relay_app()
    client = TestClient(relay.app)
    payload = {"cpu": 45.2, "mem": 62.1}
    post_response = client.post("/ingest/10/pulse/main/default", json=payload)

    assert post_response.status_code == 200
    assert post_response.json() == {"ok": True}

    frames = asyncio.run(_collect_frames(relay, stream_key("pulse", "10"), 1))

    assert frames == [f"data: {json.dumps(payload)}\n\n"]


def test_h10_ecg_route_keeps_payload_shape_and_path_identity():
    relay = _load_relay_app()
    client = TestClient(relay.app)
    payload = {"samples_uv": [10, 12, 8, -4], "sample_rate_hz": 130}
    response = client.post("/ingest/11/h10/6FFF5628/ecg", json=payload)

    assert response.status_code == 200
    assert response.json() == {"ok": True}

    frames = asyncio.run(
        _collect_frames(relay, stream_key("h10", "11", "ecg", instance_id="6FFF5628"), 1)
    )

    assert frames == [f"data: {json.dumps(payload)}\n\n"]


def test_latest_payload_is_updated_on_second_post():
    relay = _load_relay_app()
    client = TestClient(relay.app)
    client.post("/ingest/11/sen66/main/default", json={"temperature_c": 22.5})
    client.post("/ingest/11/sen66/main/default", json={"temperature_c": 23.0})

    frames = asyncio.run(_collect_frames(relay, stream_key("sen66", "11"), 1))

    assert frames == ['data: {"temperature_c": 23.0}\n\n']


def test_invalid_route_combinations_return_not_found():
    relay = _load_relay_app()
    client = TestClient(relay.app)

    assert client.post("/ingest/11/pulse/not-main/default", json={}).status_code == 404
    assert client.post("/ingest/11/h10/main/ecg", json={}).status_code == 404
    assert client.get("/11/sen66/main/not_a_stream").status_code == 404


def test_relay_exposes_generic_ingest_and_stream_routes():
    relay = _load_relay_app()
    route_paths = {route.path for route in relay.app.routes}

    assert "/ingest/{device_id}/{system_key}/{instance_id}/{stream_name}" in route_paths
    assert "/{device_id}/{system_key}/{instance_id}/{stream_name}" in route_paths


def test_publish_replaces_stale_pending_frame_when_subscriber_queue_is_full():
    relay = _load_relay_app()
    key = stream_key("pulse", "10")
    queue = asyncio.Queue(maxsize=1)
    queue.put_nowait({"cpu": 10.0})
    relay._stream_state(key).subscribers.append(queue)

    relay._publish(key, {"cpu": 20.0})

    assert queue.qsize() == 1
    assert queue.get_nowait() == {"cpu": 20.0}
