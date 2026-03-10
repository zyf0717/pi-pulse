"""Push-to-pull relay for Pi-Pulse sensor streams."""

import asyncio
import sys
from dataclasses import dataclass, field
from pathlib import Path

import uvicorn
from fastapi import Body, FastAPI, HTTPException

if __package__ in (None, ""):
    sys.path.append(str(Path(__file__).resolve().parents[1]))

from relay.config import HOST, PORT, QUEUE_MAXSIZE
from rpi4.sse import encode_sse, put_latest, queue_stream, sse_response
from shared.streams import (
    DEFAULT_INSTANCE,
    is_multi_instance,
    is_valid_stream,
    stream_key,
)


@dataclass
class StreamState:
    latest: dict | None = None
    subscribers: list[asyncio.Queue] = field(default_factory=list)
    subscribers_lock: asyncio.Lock = field(default_factory=asyncio.Lock)


_STREAMS: dict[str, StreamState] = {}


def _stream_state(key: str) -> StreamState:
    state = _STREAMS.get(key)
    if state is None:
        state = StreamState()
        _STREAMS[key] = state
    return state


def _validate_path(system_key: str, instance_id: str, stream_name: str) -> None:
    if not is_valid_stream(system_key, stream_name):
        raise HTTPException(status_code=404, detail="Unknown stream")
    if is_multi_instance(system_key):
        if instance_id == DEFAULT_INSTANCE:
            raise HTTPException(status_code=404, detail="Missing instance")
        return
    if instance_id != DEFAULT_INSTANCE:
        raise HTTPException(status_code=404, detail="Unexpected instance")


def _publish(key: str, payload: dict) -> None:
    state = _stream_state(key)
    state.latest = payload
    for queue in list(state.subscribers):
        put_latest(queue, payload)


async def _relay_stream(key: str, *, max_frames: int | None = None):
    state = _stream_state(key)
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


@app.post("/ingest/{device_id}/{system_key}/{instance_id}/{stream_name}")
async def ingest(
    device_id: str,
    system_key: str,
    instance_id: str,
    stream_name: str,
    payload: dict = Body(...),
):
    _validate_path(system_key, instance_id, stream_name)
    _publish(stream_key(system_key, device_id, stream_name, instance_id=instance_id), payload)
    return {"ok": True}


@app.get("/{device_id}/{system_key}/{instance_id}/{stream_name}")
async def stream(
    device_id: str,
    system_key: str,
    instance_id: str,
    stream_name: str,
    max_frames: int | None = None,
):
    _validate_path(system_key, instance_id, stream_name)
    return sse_response(
        _relay_stream(
            stream_key(system_key, device_id, stream_name, instance_id=instance_id),
            max_frames=max_frames,
        )
    )


if __name__ == "__main__":
    uvicorn.run(app, host=HOST, port=PORT, reload=False, access_log=False)
