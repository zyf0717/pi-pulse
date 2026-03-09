import logging
import os
import socket
import time
from urllib.parse import urlparse

import httpx


log = logging.getLogger(__name__)

RELAY_BASE_URL = os.getenv("PI_PULSE_RELAY_URL", "http://192.168.121.1:8010").rstrip("/")
RELAY_TIMEOUT_S = float(os.getenv("PI_PULSE_RELAY_TIMEOUT_S", "5"))
RELAY_NODE_ID_ENV = "PI_PULSE_NODE_ID"
RELAY_BACKOFF_INITIAL_S = float(os.getenv("PI_PULSE_RELAY_BACKOFF_INITIAL_S", "0.5"))
RELAY_BACKOFF_MAX_S = 5.0

_next_attempt_monotonic = 0.0
_current_backoff_s = 0.0


class RelayBackoffActive(RuntimeError):
    pass


def detect_node_id(relay_base_url: str = RELAY_BASE_URL) -> str:
    node_id = os.getenv(RELAY_NODE_ID_ENV)
    if node_id:
        return node_id

    parsed = urlparse(relay_base_url)
    host = parsed.hostname
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    if not host:
        raise RuntimeError(f"Relay URL has no host: {relay_base_url}")

    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.connect((host, port))
        local_ip = sock.getsockname()[0]

    parts = local_ip.split(".")
    if len(parts) == 4 and parts[-1].isdigit():
        return parts[-1]

    raise RuntimeError(f"Could not derive node id from local IP: {local_ip}")


def ingest_url(path: str, relay_base_url: str = RELAY_BASE_URL) -> str:
    return f"{relay_base_url}/{path.lstrip('/')}"


def relay_timeout() -> httpx.Timeout:
    return httpx.Timeout(RELAY_TIMEOUT_S)


def _reset_backoff_state() -> None:
    global _next_attempt_monotonic, _current_backoff_s
    _next_attempt_monotonic = 0.0
    _current_backoff_s = 0.0


def _increase_backoff() -> float:
    global _current_backoff_s
    if _current_backoff_s <= 0.0:
        _current_backoff_s = RELAY_BACKOFF_INITIAL_S
    else:
        _current_backoff_s = min(_current_backoff_s * 2.0, RELAY_BACKOFF_MAX_S)
    return _current_backoff_s


async def post_payload(
    client: httpx.AsyncClient,
    path: str,
    payload: dict,
    *,
    relay_base_url: str = RELAY_BASE_URL,
) -> None:
    global _next_attempt_monotonic

    now = time.monotonic()
    if now < _next_attempt_monotonic:
        remaining = _next_attempt_monotonic - now
        raise RelayBackoffActive(
            f"relay in backoff for {remaining:.1f}s; discarding stale payload"
        )

    try:
        response = await client.post(ingest_url(path, relay_base_url), json=payload)
        response.raise_for_status()
    except Exception:
        delay_s = _increase_backoff()
        _next_attempt_monotonic = now + delay_s
        # KIV: route dropped payloads to a DLQ when durable buffering is introduced.
        raise
    else:
        _reset_backoff_state()


def log_post_failure(stream_name: str, exc: Exception) -> None:
    log.warning("[%s] relay push failed: %s", stream_name, exc)
