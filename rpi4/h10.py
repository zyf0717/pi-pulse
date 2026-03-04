"""
Polar H10 BLE -> Server-Sent Events service.

Endpoints
---------
GET /h10/{device_id}/health       – liveness probe for one configured H10
GET /h10/{device_id}/stream       – heart-rate (bpm) + RR intervals (ms)
GET /h10/{device_id}/ecg-stream   – ECG samples (uV) at 130 Hz, batched per PMD packet
GET /h10/{device_id}/acc-stream   – accelerometer samples (mG) at 200 Hz, batched per PMD packet
"""

import asyncio
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Optional

from bleak import BleakClient
from fastapi import FastAPI, HTTPException

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

@dataclass
class DeviceState:
    address: str
    latest: dict = field(default_factory=dict)
    subscribers: list[asyncio.Queue] = field(default_factory=list)
    subscribers_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    ecg_subscribers: list[asyncio.Queue] = field(default_factory=list)
    ecg_subscribers_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    acc_subscribers: list[asyncio.Queue] = field(default_factory=list)
    acc_subscribers_lock: asyncio.Lock = field(default_factory=asyncio.Lock)


_DEVICE_STATES: dict[str, DeviceState] = {
    device_id: DeviceState(address=address)
    for device_id, address in H10_ADDRESS.items()
}


def _broadcast(subscribers: list[asyncio.Queue], payload: dict) -> None:
    for q in list(subscribers):
        try:
            q.put_nowait(payload)
        except asyncio.QueueFull:
            pass


def _device_state(device_id: str) -> DeviceState:
    state = _DEVICE_STATES.get(device_id)
    if state is None:
        raise HTTPException(status_code=404, detail=f"Unknown H10 device: {device_id}")
    return state


async def ble_loop(device_id: str, address: str, stop_event: asyncio.Event) -> None:
    """Connect to one H10, stream HR/ECG/ACC, and fan out payloads to SSE queues."""
    state = _DEVICE_STATES[device_id]

    def handle_hr_notification(_: int, data: bytearray) -> None:
        reading = parse_hr_measurement(bytes(data))
        state.latest = reading
        _broadcast(state.subscribers, reading)

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
                state.ecg_subscribers,
                {"samples_uv": samples, "sample_rate_hz": ECG_SAMPLE_RATE_HZ},
            )
            return

        if meas_type == PMD_MEAS_TYPE_ACC:
            try:
                samples = parse_acc_frame(packet)
            except ValueError:
                return
            _broadcast(
                state.acc_subscribers,
                {
                    "samples_mg": samples,
                    "sample_rate_hz": ACC_SAMPLE_RATE_HZ,
                    "range_g": ACC_RANGE_G,
                },
            )

    async def on_connect(client: BleakClient) -> None:
        state.latest = {}
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

    await ble_connect_loop(address, stop_event, on_connect)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    stop_event = asyncio.Event()
    ble_tasks = [
        asyncio.create_task(ble_loop(device_id, address, stop_event))
        for device_id, address in H10_ADDRESS.items()
    ]

    yield

    stop_event.set()
    for ble_task in ble_tasks:
        ble_task.cancel()
    if ble_tasks:
        await asyncio.gather(*ble_tasks, return_exceptions=True)


app = FastAPI(title="Pi-Pulse - Polar H10 Heart Rate", lifespan=lifespan)


@app.get("/h10/{device_id}/health")
async def health(device_id: str):
    state = _device_state(device_id)
    return {
        "status": "pulsing",
        "sensor": "Polar H10",
        "device_id": device_id,
        "address": state.address,
        "connected": bool(state.latest),
    }


async def hr_stream(device_id: str, max_frames: Optional[int] = None):
    state = _device_state(device_id)
    async for frame in queue_stream(state.subscribers, state.subscribers_lock, max_frames):
        yield frame


@app.get("/h10/{device_id}/stream")
async def stream(device_id: str):
    """SSE stream: heart-rate (bpm) and RR intervals (ms)."""
    return sse_response(hr_stream(device_id))


async def ecg_stream(device_id: str, max_frames: Optional[int] = None):
    state = _device_state(device_id)
    async for frame in queue_stream(
        state.ecg_subscribers, state.ecg_subscribers_lock, max_frames
    ):
        yield frame


async def acc_stream(device_id: str, max_frames: Optional[int] = None):
    state = _device_state(device_id)
    async for frame in queue_stream(
        state.acc_subscribers, state.acc_subscribers_lock, max_frames
    ):
        yield frame


@app.get("/h10/{device_id}/ecg-stream")
async def ecg_stream_endpoint(device_id: str):
    """SSE stream: batched ECG samples (uV) at 130 Hz from the Polar PMD service."""
    return sse_response(ecg_stream(device_id))


@app.get("/h10/{device_id}/acc-stream")
async def acc_stream_endpoint(device_id: str):
    """SSE stream: batched accelerometer samples (mG) at 200 Hz from Polar PMD."""
    return sse_response(acc_stream(device_id))
