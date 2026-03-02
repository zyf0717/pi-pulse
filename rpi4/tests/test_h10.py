"""Tests for rpi4/h10.py.

Covers:
- parse_hr_measurement  — uint8/uint16 HR format, RR conversion, edge cases
- hr_stream             — SSE framing verified via max_frames + feeder task
- parse_ecg_frame       — PMD frame parsing, sign-extension, error paths
- ecg_stream            — SSE framing verified via max_frames + feeder task
- parse_acc_frame       — PMD accelerometer parsing, error paths
- acc_stream            — SSE framing verified via max_frames + feeder task
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


# ── parse_ecg_frame ───────────────────────────────────────────────────────────
# Pure synchronous function — no async infrastructure needed.


def _build_ecg_packet(
    samples_uv: list[int], meas_type: int = 0x00, frame_type_byte: int = 0x00
) -> bytes:
    """
    Build a minimal PMD Data notification packet.

    Header (10 bytes):
      byte 0    : measurement type
      bytes 1-8 : timestamp (zeroed)
      byte 9    : frame_type_byte (bit 7 = compressed, bits 0-6 = frame type)
    Payload:
      3 bytes per sample, signed 24-bit little-endian
    """
    header = bytes([meas_type]) + b"\x00" * 8 + bytes([frame_type_byte])
    payload = b""
    for uv in samples_uv:
        # Convert Python int to unsigned 24-bit for packing
        unsigned = uv & 0xFFFFFF
        payload += bytes(
            [unsigned & 0xFF, (unsigned >> 8) & 0xFF, (unsigned >> 16) & 0xFF]
        )
    return header + payload


def test_parse_ecg_frame_positive_samples():
    """Positive µV values round-trip correctly through the parser."""
    h10 = _load_h10()
    samples = [100, 200, 300]
    packet = _build_ecg_packet(samples)
    result = h10.parse_ecg_frame(packet)
    assert result == samples


def test_parse_ecg_frame_negative_samples_sign_extended():
    """Negative µV values are sign-extended correctly from 24-bit."""
    h10 = _load_h10()
    samples = [-100, -1, -8388608]  # -8388608 = minimum signed 24-bit value
    packet = _build_ecg_packet(samples)
    result = h10.parse_ecg_frame(packet)
    assert result == samples


def test_parse_ecg_frame_empty_payload_returns_empty_list():
    """Header only (no sample bytes) → empty list, no error."""
    h10 = _load_h10()
    packet = _build_ecg_packet([])
    result = h10.parse_ecg_frame(packet)
    assert result == []


def test_parse_ecg_frame_raises_on_short_frame():
    """Frames shorter than 10 bytes raise ValueError."""
    h10 = _load_h10()
    import pytest

    with pytest.raises(ValueError, match="too short"):
        h10.parse_ecg_frame(b"\x00" * 9)


def test_parse_ecg_frame_raises_on_wrong_measurement_type():
    """Measurement type ≠ 0x00 (ECG) raises ValueError."""
    h10 = _load_h10()
    import pytest

    packet = _build_ecg_packet([100], meas_type=h10.PMD_MEAS_TYPE_ACC)
    with pytest.raises(ValueError, match="ECG"):
        h10.parse_ecg_frame(packet)


def test_parse_ecg_frame_raises_on_compressed_frame():
    """Bit-7-set frame_type_byte indicates compressed data — unsupported, raises ValueError."""
    h10 = _load_h10()
    import pytest

    packet = _build_ecg_packet([100], frame_type_byte=0x80)  # compressed flag
    with pytest.raises(ValueError, match="[Cc]ompressed"):
        h10.parse_ecg_frame(packet)


def test_parse_ecg_frame_raises_on_nonzero_frame_type():
    """Non-zero frame type (e.g. Type 1) raises ValueError."""
    h10 = _load_h10()
    import pytest

    packet = _build_ecg_packet([100], frame_type_byte=0x01)  # Type 1, not compressed
    with pytest.raises(ValueError, match="frame type"):
        h10.parse_ecg_frame(packet)


def test_parse_ecg_frame_mixed_samples():
    """A mix of positive and negative values all parse correctly."""
    h10 = _load_h10()
    samples = [0, -500, 1234, -8000, 8000]
    packet = _build_ecg_packet(samples)
    result = h10.parse_ecg_frame(packet)
    assert result == samples


# ── parse_acc_frame ───────────────────────────────────────────────────────────
# Pure synchronous function — no async infrastructure needed.


def _build_acc_packet(
    samples_xyz_mg: list[tuple[int, int, int]],
    meas_type: int = 0x02,
    frame_type_byte: int = 0x00,
) -> bytes:
    """Build a minimal PMD accelerometer packet with 16-bit x/y/z samples."""
    header = bytes([meas_type]) + b"\x00" * 8 + bytes([frame_type_byte])
    payload = b""
    for x_mg, y_mg, z_mg in samples_xyz_mg:
        payload += struct.pack("<hhh", x_mg, y_mg, z_mg)
    return header + payload


def test_parse_acc_frame_xyz_samples():
    """Signed 16-bit x/y/z values round-trip correctly."""
    h10 = _load_h10()
    samples = [(10, -20, 30), (-1000, 0, 1000)]
    packet = _build_acc_packet(samples)
    result = h10.parse_acc_frame(packet)
    assert result == [
        {"x_mg": 10, "y_mg": -20, "z_mg": 30},
        {"x_mg": -1000, "y_mg": 0, "z_mg": 1000},
    ]


def test_parse_acc_frame_empty_payload_returns_empty_list():
    """Header only (no sample bytes) -> empty list, no error."""
    h10 = _load_h10()
    packet = _build_acc_packet([])
    result = h10.parse_acc_frame(packet)
    assert result == []


def test_parse_acc_frame_raises_on_short_frame():
    """Frames shorter than 10 bytes raise ValueError."""
    h10 = _load_h10()
    import pytest

    with pytest.raises(ValueError, match="too short"):
        h10.parse_acc_frame(b"\x02" * 9)


def test_parse_acc_frame_raises_on_wrong_measurement_type():
    """Measurement type != ACC raises ValueError."""
    h10 = _load_h10()
    import pytest

    packet = _build_acc_packet([(1, 2, 3)], meas_type=h10.PMD_MEAS_TYPE_ECG)
    with pytest.raises(ValueError, match="ACC"):
        h10.parse_acc_frame(packet)


def test_parse_acc_frame_raises_on_compressed_frame():
    """Compressed ACC frames are rejected."""
    h10 = _load_h10()
    import pytest

    packet = _build_acc_packet([(1, 2, 3)], frame_type_byte=0x80)
    with pytest.raises(ValueError, match="[Cc]ompressed"):
        h10.parse_acc_frame(packet)


def test_parse_acc_frame_raises_on_nonzero_frame_type():
    """Only uncompressed Type 0 ACC frames are supported."""
    h10 = _load_h10()
    import pytest

    packet = _build_acc_packet([(1, 2, 3)], frame_type_byte=0x01)
    with pytest.raises(ValueError, match="frame type"):
        h10.parse_acc_frame(packet)


# ── ecg_stream — SSE framing ──────────────────────────────────────────────────
# ecg_stream blocks on Queue.get() waiting for PMD Data notifications.
# The feeder coroutine simulates those by writing into _ecg_subscribers.


async def _collect_ecg_frames(mod, n, payload=None):
    """
    Run ecg_stream(max_frames=n) while concurrently feeding it n fake payloads.

    Mirrors _collect_hr_frames; uses _ecg_subscribers instead of _subscribers.
    """
    if payload is None:
        payload = {"samples_uv": [100, -200, 300], "sample_rate_hz": 130}

    async def feeder():
        for _ in range(n):
            await asyncio.sleep(0)
            async with mod._ecg_subscribers_lock:
                for q in list(mod._ecg_subscribers):
                    try:
                        q.put_nowait(payload)
                    except asyncio.QueueFull:
                        pass

    feeder_task = asyncio.create_task(feeder())
    frames = []
    async for frame in mod.ecg_stream(max_frames=n):
        frames.append(frame)
    await feeder_task
    return frames


def test_ecg_stream_single_frame_has_sse_prefix():
    h10 = _load_h10()
    frames = asyncio.run(_collect_ecg_frames(h10, n=1))
    assert len(frames) == 1
    assert frames[0].startswith("data: ")


def test_ecg_stream_single_frame_is_valid_json():
    h10 = _load_h10()
    frames = asyncio.run(_collect_ecg_frames(h10, n=1))
    payload = json.loads(frames[0][len("data: ") :].strip())
    assert "samples_uv" in payload
    assert "sample_rate_hz" in payload


def test_ecg_stream_terminates_after_max_frames():
    """Generator must yield exactly N frames then stop."""
    h10 = _load_h10()
    frames = asyncio.run(_collect_ecg_frames(h10, n=4))
    assert len(frames) == 4


def test_ecg_stream_frame_contains_correct_payload():
    """Payload values match the data injected by the feeder."""
    h10 = _load_h10()
    expected = {"samples_uv": [-150, 0, 250], "sample_rate_hz": 130}
    frames = asyncio.run(_collect_ecg_frames(h10, n=1, payload=expected))
    result = json.loads(frames[0][len("data: ") :].strip())
    assert result["samples_uv"] == expected["samples_uv"]
    assert result["sample_rate_hz"] == 130


def test_ecg_stream_subscriber_cleaned_up_after_exit():
    """After the generator exits, its queue is removed from _ecg_subscribers."""
    h10 = _load_h10()
    asyncio.run(_collect_ecg_frames(h10, n=1))
    assert len(h10._ecg_subscribers) == 0


# ── acc_stream — SSE framing ──────────────────────────────────────────────────
# acc_stream blocks on Queue.get() waiting for PMD Data notifications.
# The feeder coroutine simulates those by writing into _acc_subscribers.


async def _collect_acc_frames(mod, n, payload=None):
    """
    Run acc_stream(max_frames=n) while concurrently feeding it n fake payloads.

    Mirrors _collect_ecg_frames; uses _acc_subscribers instead of _ecg_subscribers.
    """
    if payload is None:
        payload = {
            "samples_mg": [{"x_mg": 1, "y_mg": -2, "z_mg": 3}],
            "sample_rate_hz": 200,
            "range_g": 8,
        }

    async def feeder():
        for _ in range(n):
            await asyncio.sleep(0)
            async with mod._acc_subscribers_lock:
                for q in list(mod._acc_subscribers):
                    try:
                        q.put_nowait(payload)
                    except asyncio.QueueFull:
                        pass

    feeder_task = asyncio.create_task(feeder())
    frames = []
    async for frame in mod.acc_stream(max_frames=n):
        frames.append(frame)
    await feeder_task
    return frames


def test_acc_stream_single_frame_has_sse_prefix():
    h10 = _load_h10()
    frames = asyncio.run(_collect_acc_frames(h10, n=1))
    assert len(frames) == 1
    assert frames[0].startswith("data: ")


def test_acc_stream_single_frame_is_valid_json():
    h10 = _load_h10()
    frames = asyncio.run(_collect_acc_frames(h10, n=1))
    payload = json.loads(frames[0][len("data: ") :].strip())
    assert "samples_mg" in payload
    assert "sample_rate_hz" in payload
    assert "range_g" in payload


def test_acc_stream_terminates_after_max_frames():
    """Generator must yield exactly N frames then stop."""
    h10 = _load_h10()
    frames = asyncio.run(_collect_acc_frames(h10, n=3))
    assert len(frames) == 3


def test_acc_stream_frame_contains_correct_payload():
    """Payload values match the data injected by the feeder."""
    h10 = _load_h10()
    expected = {
        "samples_mg": [{"x_mg": -12, "y_mg": 34, "z_mg": -56}],
        "sample_rate_hz": 200,
        "range_g": 8,
    }
    frames = asyncio.run(_collect_acc_frames(h10, n=1, payload=expected))
    result = json.loads(frames[0][len("data: ") :].strip())
    assert result == expected


def test_acc_stream_subscriber_cleaned_up_after_exit():
    """After the generator exits, its queue is removed from _acc_subscribers."""
    h10 = _load_h10()
    asyncio.run(_collect_acc_frames(h10, n=1))
    assert len(h10._acc_subscribers) == 0


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
