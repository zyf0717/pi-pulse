"""Minimal shared stream contract for Pi-Pulse."""

DEFAULT_INSTANCE = "main"
DEFAULT_STREAM = "default"

SYSTEM_STREAMS = {
    "pulse": (DEFAULT_STREAM,),
    "sen66": (DEFAULT_STREAM, "number_concentration"),
    "h10": (DEFAULT_STREAM, "ecg", "acc"),
    "gps": (DEFAULT_STREAM,),
}

MULTI_INSTANCE_SYSTEMS = {"h10"}


def system_streams(system_key: str) -> tuple[str, ...]:
    return SYSTEM_STREAMS[system_key]


def is_multi_instance(system_key: str) -> bool:
    return system_key in MULTI_INSTANCE_SYSTEMS


def instance_segment(system_key: str, instance_id: str | None = None) -> str:
    if is_multi_instance(system_key):
        if not instance_id:
            raise ValueError(f"{system_key} requires an instance_id")
        return instance_id
    return DEFAULT_INSTANCE


def is_valid_stream(system_key: str, stream_key: str) -> bool:
    return stream_key in SYSTEM_STREAMS.get(system_key, ())


def ingest_path(
    system_key: str,
    device_id: str,
    stream_key: str = DEFAULT_STREAM,
    *,
    instance_id: str | None = None,
) -> str:
    if not is_valid_stream(system_key, stream_key):
        raise KeyError(stream_key)
    return f"/ingest/{device_id}/{system_key}/{instance_segment(system_key, instance_id)}/{stream_key}"


def stream_path(
    system_key: str,
    device_id: str,
    stream_key: str = DEFAULT_STREAM,
    *,
    instance_id: str | None = None,
) -> str:
    if not is_valid_stream(system_key, stream_key):
        raise KeyError(stream_key)
    return f"/{device_id}/{system_key}/{instance_segment(system_key, instance_id)}/{stream_key}"


def stream_key(
    system_key: str,
    device_id: str,
    stream_key: str = DEFAULT_STREAM,
    *,
    instance_id: str | None = None,
) -> str:
    return stream_path(system_key, device_id, stream_key, instance_id=instance_id)[1:]
