"""
h10.py — Polar H10 heart-rate + ECG BLE → Server-Sent Events
Mirrors the output-stream style of pulse.py and sen66.py.

Endpoints
---------
GET /health       – liveness probe
GET /stream       – SSE: heart-rate (bpm) + RR intervals (ms) at notification rate
GET /ecg-stream   – SSE: ECG samples (µV) at 130 Hz, batched per PMD packet

BLE device
----------
Address : A0:9E:1A:6F:FF:56
Name    : Polar H10 6FFF5628

ECG protocol (Polar PMD, proprietary over BLE)
----------------------------------------------
PMD Service   : FB005C80-02E7-F387-1CAD-8ACD2D8DF0C8
PMD CP (ctrl) : FB005C81-02E7-F387-1CAD-8ACD2D8DF0C8
PMD Data      : FB005C82-02E7-F387-1CAD-8ACD2D8DF0C8

Start-measurement command written to PMD CP:
  [0x02, 0x00,               # op=START, type=ECG
   0x00, 0x01, 0x82, 0x00,  # setting: SAMPLE_RATE=130 Hz
   0x01, 0x01, 0x0E, 0x00]  # setting: RESOLUTION=14 bit

PMD Data frame layout (per notification):
  byte 0    : measurement type (0x00 = ECG)
  bytes 1-8 : 64-bit timestamp, little-endian, nanoseconds since 2000-01-01
  byte 9    : frame_type_byte (bit 7 = compressed; bits 0-6 = frame type)
  bytes 10+ : ECG samples, 3 bytes each, signed 24-bit little-endian, µV

Only uncompressed Type 0 frames are produced by the H10.
"""

import asyncio
import json
import struct
from contextlib import asynccontextmanager
from typing import List, Optional

from bleak import BleakClient, BleakError
from fastapi import FastAPI
from fastapi.responses import StreamingResponse

# ── Polar H10 identifiers ─────────────────────────────────────────────────────
H10_ADDRESS = "A0:9E:1A:6F:FF:56"

# Standard Bluetooth Heart Rate Measurement characteristic
HR_MEASUREMENT_UUID = "00002a37-0000-1000-8000-00805f9b34fb"

# Polar Measurement Data (PMD) — proprietary ECG service
PMD_SERVICE_UUID = "FB005C80-02E7-F387-1CAD-8ACD2D8DF0C8"
PMD_CP_UUID = "FB005C81-02E7-F387-1CAD-8ACD2D8DF0C8"
PMD_DATA_UUID = "FB005C82-02E7-F387-1CAD-8ACD2D8DF0C8"

# Command: start ECG at 130 Hz / 14-bit resolution
ECG_START_CMD = bytearray(
    [
        0x02,
        0x00,  # op=START_MEASUREMENT, type=ECG
        0x00,
        0x01,
        0x82,
        0x00,  # setting SAMPLE_RATE=130 (uint16 LE)
        0x01,
        0x01,
        0x0E,
        0x00,  # setting RESOLUTION=14  (uint16 LE)
    ]
)

# ── Shared state ──────────────────────────────────────────────────────────────
# Latest parsed reading; written by the BLE callback, read by SSE consumers.
_latest: dict = {}

# Broadcast queue: every SSE client gets its own subscriber queue.
# The BLE callback puts one item here; fan-out is handled in ble_loop.
_subscribers: List[asyncio.Queue] = []
_subscribers_lock = asyncio.Lock()

# ECG subscribers — same fan-out pattern; each item is a list of µV samples.
_ecg_subscribers: List[asyncio.Queue] = []
_ecg_subscribers_lock = asyncio.Lock()


# ── HR packet parser ──────────────────────────────────────────────────────────


def parse_hr_measurement(data: bytes) -> dict:
    """
    Parse a Bluetooth Heart Rate Measurement characteristic packet.

    Flags byte (byte 0):
      bit 0  – HR value format: 0 = UINT8, 1 = UINT16
      bit 4  – RR interval(s) present

    RR intervals are encoded as UINT16 little-endian, unit = 1/1024 s.
    We convert to milliseconds (rounded to 1 ms).
    """
    flags = data[0]
    hr_uint16 = bool(flags & 0x01)
    rr_present = bool(flags & 0x10)

    offset = 1
    if hr_uint16:
        bpm = struct.unpack_from("<H", data, offset)[0]
        offset += 2
    else:
        bpm = data[offset]
        offset += 1

    rr_ms: List[int] = []
    if rr_present:
        while offset + 1 < len(data):
            raw = struct.unpack_from("<H", data, offset)[0]
            offset += 2
            rr_ms.append(round(raw * 1000 / 1024))

    return {"bpm": bpm, "rr_ms": rr_ms}


# ── ECG packet parser ─────────────────────────────────────────────────────────


def parse_ecg_frame(data: bytes) -> List[int]:
    """
    Parse a Polar PMD Data notification carrying ECG samples.

    Frame layout:
      byte 0    : measurement type (0x00 = ECG — validated here)
      bytes 1-8 : 64-bit timestamp, little-endian (nanoseconds since 2000-01-01)
      byte 9    : frame_type_byte
                    bit 7 = 1 → compressed (not supported by H10 for ECG)
                    bits 0-6   → frame type (0 = Type 0, raw signed-24-bit)
      bytes 10+ : ECG samples, 3 bytes each, signed 24-bit little-endian, µV

    Returns a list of integer microvolts, one per sample in the packet.
    Typically ~73 samples per packet at 130 Hz.
    Raises ValueError on unexpected measurement type or compressed frame.
    """
    if len(data) < 10:
        raise ValueError(f"PMD frame too short: {len(data)} bytes")

    meas_type = data[0]
    if meas_type != 0x00:
        raise ValueError(f"Expected ECG (0x00), got measurement type {meas_type:#04x}")

    frame_type_byte = data[9]
    compressed = bool(frame_type_byte & 0x80)
    frame_type = frame_type_byte & 0x7F

    if compressed:
        raise ValueError(
            f"Compressed ECG frames are not supported (frame type byte {frame_type_byte:#04x})"
        )
    if frame_type != 0:
        raise ValueError(
            f"Unsupported ECG frame type {frame_type} (only Type 0 implemented)"
        )

    samples: List[int] = []
    payload = data[10:]
    for i in range(0, len(payload) - 2, 3):
        raw = payload[i] | (payload[i + 1] << 8) | (payload[i + 2] << 16)
        # Sign-extend from 24 bits
        if raw >= 0x800000:
            raw -= 0x1000000
        samples.append(raw)

    return samples


# ── BLE background loop ───────────────────────────────────────────────────────


async def ble_loop(stop_event: asyncio.Event) -> None:
    """
    Connect to the H10, subscribe to HR notifications and start ECG streaming,
    then fan-out each parsed reading to all active SSE subscriber queues.

    Reconnects automatically on disconnection or BLE error.
    """
    global _latest

    def handle_hr_notification(_: int, data: bytearray) -> None:
        reading = parse_hr_measurement(bytes(data))
        _latest = reading
        for q in list(_subscribers):
            try:
                q.put_nowait(reading)
            except asyncio.QueueFull:
                pass

    def handle_ecg_notification(_: int, data: bytearray) -> None:
        try:
            samples = parse_ecg_frame(bytes(data))
        except ValueError:
            return
        payload = {"samples_uv": samples, "sample_rate_hz": 130}
        for q in list(_ecg_subscribers):
            try:
                q.put_nowait(payload)
            except asyncio.QueueFull:
                pass

    while not stop_event.is_set():
        try:
            async with BleakClient(H10_ADDRESS) as client:
                # ── Heart rate ────────────────────────────────────────────────
                await client.start_notify(HR_MEASUREMENT_UUID, handle_hr_notification)

                # ── ECG via PMD ───────────────────────────────────────────────
                # 1. Enable notifications on the PMD control point so we can
                #    receive the start-measurement acknowledgement.
                await client.start_notify(PMD_CP_UUID, lambda _h, _d: None)
                # 2. Write the start-ECG command and wait for the ack.
                await client.write_gatt_char(PMD_CP_UUID, ECG_START_CMD, response=True)
                # 3. Subscribe to actual ECG data frames.
                await client.start_notify(PMD_DATA_UUID, handle_ecg_notification)

                # Wait until the server is shutting down or the device drops.
                await stop_event.wait()

                await client.stop_notify(HR_MEASUREMENT_UUID)
                await client.stop_notify(PMD_DATA_UUID)
                await client.stop_notify(PMD_CP_UUID)

        except BleakError as exc:
            if stop_event.is_set():
                break
            _latest = {}
            print(f"[h10] BLE error: {exc} — reconnecting in 5 s")
            await asyncio.sleep(5)
        except Exception as exc:
            if stop_event.is_set():
                break
            _latest = {}
            print(f"[h10] Unexpected error: {exc} — reconnecting in 5 s")
            await asyncio.sleep(5)


# ── FastAPI lifespan ──────────────────────────────────────────────────────────


@asynccontextmanager
async def lifespan(_app: FastAPI):
    stop_event = asyncio.Event()
    ble_task = asyncio.create_task(ble_loop(stop_event))

    yield  # server handles requests here

    stop_event.set()
    ble_task.cancel()
    try:
        await ble_task
    except asyncio.CancelledError:
        pass


app = FastAPI(title="Pi-Pulse — Polar H10 Heart Rate", lifespan=lifespan)


# ── Endpoints ─────────────────────────────────────────────────────────────────


@app.get("/health")
async def health():
    connected = bool(_latest)
    return {
        "status": "pulsing",
        "sensor": "Polar H10",
        "address": H10_ADDRESS,
        "connected": connected,
    }


async def hr_stream(max_frames: Optional[int] = None):
    """
    Async generator yielding SSE-formatted HR frames.

    Each subscriber gets its own asyncio.Queue so the fan-out from the BLE
    callback is non-blocking.

    Args:
        max_frames: Terminate after this many frames (None = run forever).
    """
    q: asyncio.Queue = asyncio.Queue(maxsize=64)

    async with _subscribers_lock:
        _subscribers.append(q)

    frame = 0
    try:
        while max_frames is None or frame < max_frames:
            reading = await q.get()
            yield f"data: {json.dumps(reading)}\n\n"
            frame += 1
    except asyncio.CancelledError:
        return
    finally:
        async with _subscribers_lock:
            try:
                _subscribers.remove(q)
            except ValueError:
                pass


@app.get("/stream")
async def stream():
    """SSE stream: heart-rate (bpm) and RR intervals (ms)."""
    headers = {
        "Cache-Control": "no-cache",
        "X-Accel-Buffering": "no",
    }
    return StreamingResponse(
        hr_stream(), media_type="text/event-stream", headers=headers
    )


async def ecg_stream(max_frames: Optional[int] = None):
    """
    Async generator yielding SSE-formatted ECG frames.

    Each frame contains a batch of samples from one PMD Data notification:
      {"samples_uv": [int, ...], "sample_rate_hz": 130}

    At 130 Hz the H10 sends ~73 samples per BLE packet (~1.8 packets/s).

    Args:
        max_frames: Terminate after this many frames (None = run forever).
    """
    q: asyncio.Queue = asyncio.Queue(maxsize=64)

    async with _ecg_subscribers_lock:
        _ecg_subscribers.append(q)

    frame = 0
    try:
        while max_frames is None or frame < max_frames:
            payload = await q.get()
            yield f"data: {json.dumps(payload)}\n\n"
            frame += 1
    except asyncio.CancelledError:
        return
    finally:
        async with _ecg_subscribers_lock:
            try:
                _ecg_subscribers.remove(q)
            except ValueError:
                pass


@app.get("/ecg-stream")
async def ecg_stream_endpoint():
    """SSE stream: batched ECG samples (µV) at 130 Hz from the Polar PMD service."""
    headers = {
        "Cache-Control": "no-cache",
        "X-Accel-Buffering": "no",
    }
    return StreamingResponse(
        ecg_stream(), media_type="text/event-stream", headers=headers
    )
