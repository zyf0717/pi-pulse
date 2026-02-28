import json

from app.streams.parser import extract_sse_payload, parse_payload, parse_sse_json


def test_extract_sse_payload_accepts_only_legacy_data_prefix() -> None:
    assert extract_sse_payload('data: {"cpu": 1}') == '{"cpu": 1}'
    assert extract_sse_payload('data:{"cpu": 1}') is None
    assert extract_sse_payload("event: ignored") is None


def test_parse_payload_decodes_json() -> None:
    assert parse_payload('{"cpu": 1}') == {"cpu": 1}


def test_parse_sse_json_returns_none_for_non_data_lines() -> None:
    assert parse_sse_json("event: ignored") is None


def test_parse_sse_json_raises_for_malformed_legacy_data() -> None:
    try:
        parse_sse_json('data: {"cpu": ')
    except json.JSONDecodeError:
        pass
    else:
        raise AssertionError("Expected JSONDecodeError for malformed payload")
