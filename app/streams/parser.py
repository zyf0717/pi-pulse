"""Legacy SSE parsing helpers for the dashboard's current stream format."""

import json


def extract_sse_payload(line: str) -> str | None:
    if not line.startswith("data: "):
        return None
    return line[len("data: ") :]


def parse_payload(payload: str) -> dict:
    return json.loads(payload)


def parse_sse_json(line: str) -> dict | None:
    payload = extract_sse_payload(line)
    if payload is None:
        return None
    return parse_payload(payload)
