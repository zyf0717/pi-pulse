"""Push-to-pull relay for Pi-Pulse sensor streams."""

import asyncio
from dataclasses import dataclass, field
from typing import Optional

import uvicorn
from fastapi import Body, FastAPI

from relay.config import HOST, PORT, QUEUE_MAXSIZE
from rpi4.sse import encode_sse, queue_stream, sse_response


@dataclass
class StreamState:
    latest: Optional[dict] = None
    subscribers: list[asyncio.Queue] = field(default_factory=list)
    subscribers_lock: asyncio.Lock = field(default_factory=asyncio.Lock)


_STREAMS: dict[str, StreamState] = {}


def _stream_state(stream_key: str) -> StreamState:
    state = _STREAMS.get(stream_key)
    if state is None:
        state = StreamState()
        _STREAMS[stream_key] = state
    return state


def _publish(stream_key: str, payload: dict) -> None:
    state = _stream_state(stream_key)
    state.latest = payload
    for q in list(state.subscribers):
        try:
            q.put_nowait(payload)
        except asyncio.QueueFull:
            pass


async def _relay_stream(
    stream_key: str,
    *,
    max_frames: Optional[int] = None,
):
    state = _stream_state(stream_key)
    emitted = 0
    if state.latest is not None:
        yield encode_sse(state.latest)
        emitted = 1
        if max_frames is not None and emitted >= max_frames:
            return

    remaining = None if max_frames is None else max_frames - emitted
    async for frame in queue_stream(
        state.subscribers,
        state.subscribers_lock,
        max_frames=remaining,
        queue_maxsize=QUEUE_MAXSIZE,
    ):
        yield frame


app = FastAPI(title="Pi-Pulse Relay")


@app.get("/health")
async def health():
    return {
        "status": "ok",
        "streams": len(_STREAMS),
        "subscribers": sum(len(state.subscribers) for state in _STREAMS.values()),
    }


@app.post("/ingest/pulse/{node_id}/stream")
async def ingest_pulse(node_id: str, payload: dict = Body(...)):
    _publish(f"pulse/{node_id}/stream", payload)
    return {"ok": True}


@app.post("/ingest/sen66/{node_id}/stream")
async def ingest_sen66(node_id: str, payload: dict = Body(...)):
    _publish(f"sen66/{node_id}/stream", payload)
    return {"ok": True}


@app.post("/ingest/sen66/{node_id}/nc-stream")
async def ingest_sen66_nc(node_id: str, payload: dict = Body(...)):
    _publish(f"sen66/{node_id}/nc-stream", payload)
    return {"ok": True}


@app.post("/ingest/h10/{device_id}/stream")
async def ingest_h10(device_id: str, payload: dict = Body(...)):
    _publish(f"h10/{device_id}/stream", payload)
    return {"ok": True}


@app.post("/ingest/h10/{device_id}/ecg-stream")
async def ingest_h10_ecg(device_id: str, payload: dict = Body(...)):
    _publish(f"h10/{device_id}/ecg-stream", payload)
    return {"ok": True}


@app.post("/ingest/h10/{device_id}/acc-stream")
async def ingest_h10_acc(device_id: str, payload: dict = Body(...)):
    _publish(f"h10/{device_id}/acc-stream", payload)
    return {"ok": True}


@app.get("/pulse/{node_id}/stream")
async def pulse_stream(node_id: str, max_frames: Optional[int] = None):
    return sse_response(_relay_stream(f"pulse/{node_id}/stream", max_frames=max_frames))


@app.get("/sen66/{node_id}/stream")
async def sen66_stream(node_id: str, max_frames: Optional[int] = None):
    return sse_response(_relay_stream(f"sen66/{node_id}/stream", max_frames=max_frames))


@app.get("/sen66/{node_id}/nc-stream")
async def sen66_nc_stream(node_id: str, max_frames: Optional[int] = None):
    return sse_response(
        _relay_stream(f"sen66/{node_id}/nc-stream", max_frames=max_frames)
    )


@app.get("/h10/{device_id}/stream")
async def h10_stream(device_id: str, max_frames: Optional[int] = None):
    return sse_response(_relay_stream(f"h10/{device_id}/stream", max_frames=max_frames))


@app.get("/h10/{device_id}/ecg-stream")
async def h10_ecg_stream(device_id: str, max_frames: Optional[int] = None):
    return sse_response(
        _relay_stream(f"h10/{device_id}/ecg-stream", max_frames=max_frames)
    )


@app.get("/h10/{device_id}/acc-stream")
async def h10_acc_stream(device_id: str, max_frames: Optional[int] = None):
    return sse_response(
        _relay_stream(f"h10/{device_id}/acc-stream", max_frames=max_frames)
    )


if __name__ == "__main__":
    uvicorn.run(app, host=HOST, port=PORT, reload=False, access_log=False)
