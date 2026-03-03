"""
Polar H10 BLE -> Server-Sent Events service.

Endpoints
---------
GET /health       – liveness probe
GET /stream       – heart-rate (bpm) + RR intervals (ms)
GET /ecg-stream   – ECG samples (uV) at 130 Hz, batched per PMD packet
GET /acc-stream   – accelerometer samples (mG) at 200 Hz, batched per PMD packet
"""

import asyncio
from contextlib import asynccontextmanager
from typing import Optional

from bleak import BleakClient
from fastapi import FastAPI

try:
    from h10_protocol import (
        ACC_RANGE_G,
        ACC_SAMPLE_RATE_HZ,
        ACC_START_CMD,
        ECG_SAMPLE_RATE_HZ,
        ECG_START_CMD,
        H10_ADDRESS,
        HR_MEASUREMENT_UUID,
        PMD_CP_UUID,
        PMD_DATA_UUID,
        PMD_MEAS_TYPE_ACC,
        PMD_MEAS_TYPE_ECG,
        ble_connect_loop,
        parse_acc_frame,
        parse_ecg_frame,
        parse_hr_measurement,
    )
    from sse import queue_stream, sse_response
except ImportError:
    from rpi4.h10_protocol import (
        ACC_RANGE_G,
        ACC_SAMPLE_RATE_HZ,
        ACC_START_CMD,
        ECG_SAMPLE_RATE_HZ,
        ECG_START_CMD,
        H10_ADDRESS,
        HR_MEASUREMENT_UUID,
        PMD_CP_UUID,
        PMD_DATA_UUID,
        PMD_MEAS_TYPE_ACC,
        PMD_MEAS_TYPE_ECG,
        ble_connect_loop,
        parse_acc_frame,
        parse_ecg_frame,
        parse_hr_measurement,
    )
    from rpi4.sse import queue_stream, sse_response

# Latest parsed reading; written by the BLE callback, read by /health.
_latest: dict = {}

# Each SSE client gets its own subscriber queue.
_subscribers: list[asyncio.Queue] = []
_subscribers_lock = asyncio.Lock()

_ecg_subscribers: list[asyncio.Queue] = []
_ecg_subscribers_lock = asyncio.Lock()

_acc_subscribers: list[asyncio.Queue] = []
_acc_subscribers_lock = asyncio.Lock()


def _broadcast(subscribers: list[asyncio.Queue], payload: dict) -> None:
    for q in list(subscribers):
        try:
            q.put_nowait(payload)
        except asyncio.QueueFull:
            pass


async def ble_loop(stop_event: asyncio.Event) -> None:
    """Connect to the H10, stream HR/ECG/ACC, and fan out payloads to SSE queues."""
    global _latest

    def handle_hr_notification(_: int, data: bytearray) -> None:
        global _latest
        reading = parse_hr_measurement(bytes(data))
        _latest = reading
        _broadcast(_subscribers, reading)

    def handle_pmd_notification(_: int, data: bytearray) -> None:
        packet = bytes(data)
        if not packet:
            return

        meas_type = packet[0]

        if meas_type == PMD_MEAS_TYPE_ECG:
            try:
                samples = parse_ecg_frame(packet)
            except ValueError:
                return
            _broadcast(
                _ecg_subscribers,
                {"samples_uv": samples, "sample_rate_hz": ECG_SAMPLE_RATE_HZ},
            )
            return

        if meas_type == PMD_MEAS_TYPE_ACC:
            try:
                samples = parse_acc_frame(packet)
            except ValueError:
                return
            _broadcast(
                _acc_subscribers,
                {
                    "samples_mg": samples,
                    "sample_rate_hz": ACC_SAMPLE_RATE_HZ,
                    "range_g": ACC_RANGE_G,
                },
            )

    async def on_connect(client: BleakClient) -> None:
        global _latest
        _latest = {}
        await client.start_notify(HR_MEASUREMENT_UUID, handle_hr_notification)

        # ECG and ACC share the Polar PMD data characteristic.
        await client.start_notify(PMD_CP_UUID, lambda _h, _d: None)
        await client.start_notify(PMD_DATA_UUID, handle_pmd_notification)

        await client.write_gatt_char(PMD_CP_UUID, ECG_START_CMD, response=True)
        await asyncio.sleep(0.5)
        try:
            await client.write_gatt_char(PMD_CP_UUID, ACC_START_CMD, response=True)
        except Exception as exc:
            print(f"[h10] ACC stream unavailable: {exc}")

    await ble_connect_loop(H10_ADDRESS, stop_event, on_connect)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    stop_event = asyncio.Event()
    ble_task = asyncio.create_task(ble_loop(stop_event))

    yield

    stop_event.set()
    ble_task.cancel()
    try:
        await ble_task
    except asyncio.CancelledError:
        pass


app = FastAPI(title="Pi-Pulse - Polar H10 Heart Rate", lifespan=lifespan)


@app.get("/health")
async def health():
    return {
        "status": "pulsing",
        "sensor": "Polar H10",
        "address": H10_ADDRESS,
        "connected": bool(_latest),
    }


async def hr_stream(max_frames: Optional[int] = None):
    async for frame in queue_stream(_subscribers, _subscribers_lock, max_frames):
        yield frame


@app.get("/stream")
async def stream():
    """SSE stream: heart-rate (bpm) and RR intervals (ms)."""
    return sse_response(hr_stream())


async def ecg_stream(max_frames: Optional[int] = None):
    async for frame in queue_stream(
        _ecg_subscribers, _ecg_subscribers_lock, max_frames
    ):
        yield frame


async def acc_stream(max_frames: Optional[int] = None):
    async for frame in queue_stream(
        _acc_subscribers, _acc_subscribers_lock, max_frames
    ):
        yield frame


@app.get("/ecg-stream")
async def ecg_stream_endpoint():
    """SSE stream: batched ECG samples (uV) at 130 Hz from the Polar PMD service."""
    return sse_response(ecg_stream())


@app.get("/acc-stream")
async def acc_stream_endpoint():
    """SSE stream: batched accelerometer samples (mG) at 200 Hz from Polar PMD."""
    return sse_response(acc_stream())
