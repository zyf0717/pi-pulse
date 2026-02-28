"""Generic SSE stream consumer with exponential back-off reconnection."""

import asyncio
import json
import logging

import httpx
from shiny import reactive


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
                        if line.startswith("data: "):
                            json_str = line[len("data: ") :]
                            try:
                                data = json.loads(json_str)
                            except json.JSONDecodeError:
                                logging.warning(
                                    "Malformed SSE packet [%s], skipping: %r",
                                    label,
                                    json_str,
                                )
                                continue
                            async with reactive.lock():
                                await on_data(data)
                                await reactive.flush()
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
