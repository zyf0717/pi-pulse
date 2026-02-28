"""Generic SSE stream consumer with exponential back-off reconnection."""

import asyncio
import json
import logging

import httpx
from shiny import reactive

from app.streams.parser import extract_sse_payload, parse_payload


async def _handle_packet(label: str, line: str, on_data) -> None:
    payload = extract_sse_payload(line)
    if payload is None:
        return

    try:
        data = parse_payload(payload)
    except json.JSONDecodeError:
        logging.warning(
            "Malformed SSE packet [%s], skipping: %r",
            label,
            payload,
        )
        return

    async with reactive.lock():
        await on_data(data)
        await reactive.flush()


async def stream_consumer(label: str, url: str, on_data):
    """Consume an SSE endpoint; call on_data(parsed_dict) under reactive.lock."""
    backoff = 1
    while True:
        try:
            async with httpx.AsyncClient(timeout=None) as client:
                async with client.stream("GET", url) as response:
                    response.raise_for_status()
                    backoff = 1
                    async for line in response.aiter_lines():
                        await _handle_packet(label, line, on_data)
        except asyncio.CancelledError:
            return
        except Exception as exc:
            logging.warning(
                "Stream error [%s] (%s: %s); reconnecting in %ds…",
                label,
                type(exc).__name__,
                exc,
                backoff,
            )
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 30)
