"""Tests for rpi4/h10.py.

Covers:
- parse_hr_measurement  — uint8/uint16 HR format, RR conversion, edge cases
- hr_stream             — SSE framing verified via max_frames + feeder task
- FastAPI /health       — route response body
"""

import asyncio
import importlib.util
import json
import struct
from contextlib import asynccontextmanager
from pathlib import Path

RPI4_DIR = Path(__file__).resolve().parents[1]


# ── module loader ─────────────────────────────────────────────────────────────


def _load_h10():
    """Fresh import of h10.py each call to avoid cross-test state leakage."""
    spec = importlib.util.spec_from_file_location("rpi4_h10_fresh", RPI4_DIR / "h10.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ── no-op lifespan for FastAPI tests ─────────────────────────────────────────


@asynccontextmanager
async def _noop_lifespan(app):
    """Substitute lifespan that skips all BLE initialisation."""
    yield


# ── hr_stream feeder helper ───────────────────────────────────────────────────


async def _collect_hr_frames(mod, n, reading=None):
    """
    Run hr_stream(max_frames=n) while concurrently feeding it n fake readings.

    hr_stream blocks on asyncio.Queue.get() waiting for BLE notifications; in
    tests we simulate those notifications by putting items directly into every
    queue registered in mod._subscribers.
    """
    if reading is None:
        reading = {"bpm": 72, "rr_ms": [833]}

    async def feeder():
        for _ in range(n):
            # Yield once so the generator can start and register its queue,
            # then wait on q.get(); after that we can safely put_nowait.
            await asyncio.sleep(0)
            async with mod._subscribers_lock:
                for q in list(mod._subscribers):
                    try:
                        q.put_nowait(reading)
                    except asyncio.QueueFull:
                        pass

    feeder_task = asyncio.create_task(feeder())
    frames = []
    async for frame in mod.hr_stream(max_frames=n):
        frames.append(frame)
    await feeder_task
    return frames


# ── parse_hr_measurement ──────────────────────────────────────────────────────
# Pure synchronous function — no async infrastructure needed.


def _build_packet(
    bpm: int, rr_raw: list[int] = (), uint16_hr: bool = False, rr_present: bool = False
) -> bytes:
    """Helper: construct a minimal Heart Rate Measurement packet."""
    flags = 0
    if uint16_hr:
        flags |= 0x01
    if rr_present:
        flags |= 0x10
    parts = [bytes([flags])]
    if uint16_hr:
        parts.append(struct.pack("<H", bpm))
    else:
        parts.append(bytes([bpm]))
    for rr in rr_raw:
        parts.append(struct.pack("<H", rr))
    return b"".join(parts)


def test_parse_hr_uint8_format_no_rr():
    """Standard uint8 HR value, no RR intervals."""
    h10 = _load_h10()
    packet = _build_packet(bpm=72)
    result = h10.parse_hr_measurement(packet)
    assert result["bpm"] == 72
    assert result["rr_ms"] == []


def test_parse_hr_uint16_format_no_rr():
    """uint16 HR flag set — bpm read as two bytes little-endian."""
    h10 = _load_h10()
    packet = _build_packet(bpm=200, uint16_hr=True)
    result = h10.parse_hr_measurement(packet)
    assert result["bpm"] == 200
    assert result["rr_ms"] == []


def test_parse_hr_single_rr_interval_converted_to_ms():
    """RR interval in 1/1024 s units converted to milliseconds."""
    h10 = _load_h10()
    # 1024 raw units == 1000 ms exactly
    packet = _build_packet(bpm=60, rr_raw=[1024], rr_present=True)
    result = h10.parse_hr_measurement(packet)
    assert result["bpm"] == 60
    assert result["rr_ms"] == [1000]


def test_parse_hr_multiple_rr_intervals():
    """All RR values in the packet are parsed and converted."""
    h10 = _load_h10()
    # Two RR values: 512 raw = 500 ms, 1024 raw = 1000 ms
    packet = _build_packet(bpm=75, rr_raw=[512, 1024], rr_present=True)
    result = h10.parse_hr_measurement(packet)
    assert result["bpm"] == 75
    assert len(result["rr_ms"]) == 2
    assert result["rr_ms"][0] == 500
    assert result["rr_ms"][1] == 1000


def test_parse_hr_rr_conversion_rounds_correctly():
    """Conversion: round(raw * 1000 / 1024) — verify rounding on odd value."""
    h10 = _load_h10()
    # 857 raw → 857000/1024 ≈ 836.9 → rounds to 837
    packet = _build_packet(bpm=70, rr_raw=[857], rr_present=True)
    result = h10.parse_hr_measurement(packet)
    assert result["rr_ms"] == [round(857 * 1000 / 1024)]


def test_parse_hr_high_bpm_uint8():
    """uint8 HR can represent up to 255 bpm."""
    h10 = _load_h10()
    packet = _build_packet(bpm=255)
    result = h10.parse_hr_measurement(packet)
    assert result["bpm"] == 255


def test_parse_hr_returns_dict_with_bpm_and_rr_ms_keys():
    """Result always has both expected keys regardless of packet content."""
    h10 = _load_h10()
    packet = _build_packet(bpm=65)
    result = h10.parse_hr_measurement(packet)
    assert "bpm" in result
    assert "rr_ms" in result


# ── hr_stream — SSE framing ───────────────────────────────────────────────────
# hr_stream blocks on Queue.get() waiting for BLE notifications.
# The feeder coroutine simulates BLE callbacks by writing into _subscribers.


def test_hr_stream_single_frame_has_sse_prefix():
    h10 = _load_h10()
    frames = asyncio.run(_collect_hr_frames(h10, n=1))
    assert len(frames) == 1
    assert frames[0].startswith("data: ")


def test_hr_stream_single_frame_is_valid_json():
    h10 = _load_h10()
    frames = asyncio.run(_collect_hr_frames(h10, n=1))
    payload = json.loads(frames[0][len("data: ") :].strip())
    assert "bpm" in payload
    assert "rr_ms" in payload


def test_hr_stream_terminates_after_max_frames():
    """Generator must yield exactly N frames then stop — not block forever."""
    h10 = _load_h10()

    async def _count(n):
        count = 0
        async for _ in _collect_hr_frames(h10, n=n):
            count += 1
        # _collect_hr_frames returns a list, not an async gen — count directly
        return count

    frames = asyncio.run(_collect_hr_frames(h10, n=3))
    assert len(frames) == 3


def test_hr_stream_frame_contains_correct_bpm():
    """Payload bpm matches the reading injected by the feeder."""
    h10 = _load_h10()
    reading = {"bpm": 88, "rr_ms": [681]}
    frames = asyncio.run(_collect_hr_frames(h10, n=1, reading=reading))
    payload = json.loads(frames[0][len("data: ") :].strip())
    assert payload["bpm"] == 88
    assert payload["rr_ms"] == [681]


def test_hr_stream_subscriber_cleaned_up_after_exit():
    """After the generator exits, its queue is removed from _subscribers."""
    h10 = _load_h10()
    asyncio.run(_collect_hr_frames(h10, n=1))
    assert len(h10._subscribers) == 0


# ── FastAPI /health ───────────────────────────────────────────────────────────


def test_health_endpoint_returns_expected_body():
    from starlette.testclient import TestClient

    h10 = _load_h10()
    h10.app.router.lifespan_context = _noop_lifespan
    with TestClient(h10.app) as client:
        resp = client.get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "pulsing"
    assert body["sensor"] == "Polar H10"
    assert body["address"] == h10.H10_ADDRESS
    assert "connected" in body
