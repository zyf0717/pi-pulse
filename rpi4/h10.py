"""
h10.py — Polar H10 heart-rate BLE → Server-Sent Events
Mirrors the output-stream style of pulse.py and sen66.py.

Endpoints
---------
GET /health      – liveness probe
GET /stream      – SSE: heart-rate (bpm) + RR intervals (ms) at notification rate

BLE device
----------
Address : AA:BB:CC:DD:EE:01
Name    : Polar H10 6FFF5628
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
H10_ADDRESS = "AA:BB:CC:DD:EE:01"

# Standard Bluetooth Heart Rate Measurement characteristic
HR_MEASUREMENT_UUID = "00002a37-0000-1000-8000-00805f9b34fb"

# ── Shared state ──────────────────────────────────────────────────────────────
# Latest parsed reading; written by the BLE callback, read by SSE consumers.
_latest: dict = {}

# Broadcast queue: every SSE client gets its own subscriber queue.
# The BLE callback puts one item here; fan-out is handled in ble_loop.
_subscribers: List[asyncio.Queue] = []
_subscribers_lock = asyncio.Lock()


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


# ── BLE background loop ───────────────────────────────────────────────────────


async def ble_loop(stop_event: asyncio.Event) -> None:
    """
    Connect to the H10, subscribe to HR notifications, and fan-out each
    parsed reading to all active SSE subscriber queues.

    Reconnects automatically on disconnection or BLE error.
    """
    global _latest

    def handle_notification(_: int, data: bytearray) -> None:
        reading = parse_hr_measurement(bytes(data))
        _latest = reading
        # Fan-out to all SSE subscribers (non-blocking put_nowait; drop if full)
        for q in list(_subscribers):
            try:
                q.put_nowait(reading)
            except asyncio.QueueFull:
                pass

    while not stop_event.is_set():
        try:
            async with BleakClient(H10_ADDRESS) as client:
                await client.start_notify(HR_MEASUREMENT_UUID, handle_notification)
                # Wait until the server is shutting down or the device drops
                await stop_event.wait()
                await client.stop_notify(HR_MEASUREMENT_UUID)
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
