import asyncio
import json
from typing import Any, Optional

from fastapi.responses import StreamingResponse

SSE_HEADERS = {
    "Cache-Control": "no-cache",
    "X-Accel-Buffering": "no",
}


def encode_sse(payload: Any) -> str:
    """Serialize one payload as a server-sent event frame."""
    return f"data: {json.dumps(payload)}\n\n"


def put_latest(q: asyncio.Queue, payload: Any) -> None:
    """
    Enqueue the newest payload, evicting stale pending frames if necessary.

    This keeps slow subscribers biased toward current state instead of backlog.
    """
    while True:
        try:
            q.put_nowait(payload)
            return
        except asyncio.QueueFull:
            try:
                q.get_nowait()
            except asyncio.QueueEmpty:
                return


def sse_response(stream) -> StreamingResponse:
    """Wrap an async generator as a no-buffering SSE response."""
    return StreamingResponse(
        stream,
        media_type="text/event-stream",
        headers=dict(SSE_HEADERS),
    )


async def queue_stream(
    subscribers: list[asyncio.Queue],
    subscribers_lock: asyncio.Lock,
    max_frames: Optional[int] = None,
    queue_maxsize: int = 64,
):
    """
    Yield SSE frames from a dedicated subscriber queue.

    The queue is registered for the lifetime of the generator and removed on
    exit, so callers only need to manage fan-out.
    """
    q: asyncio.Queue = asyncio.Queue(maxsize=queue_maxsize)

    async with subscribers_lock:
        subscribers.append(q)

    frame = 0
    try:
        while max_frames is None or frame < max_frames:
            payload = await q.get()
            yield encode_sse(payload)
            frame += 1
    except asyncio.CancelledError:
        return
    finally:
        async with subscribers_lock:
            try:
                subscribers.remove(q)
            except ValueError:
                pass
