from shared.streams import (
    DEFAULT_INSTANCE,
    DEFAULT_STREAM,
    SYSTEM_STREAMS,
    ingest_path,
    is_multi_instance,
    is_valid_stream,
    stream_key,
    stream_path,
    system_streams,
)


def test_registry_is_just_system_to_stream_names():
    assert SYSTEM_STREAMS == {
        "pulse": (DEFAULT_STREAM,),
        "sen66": (DEFAULT_STREAM, "number_concentration"),
        "gps": (DEFAULT_STREAM,),
        "h10": (DEFAULT_STREAM, "ecg", "acc"),
        "pacer": ("hr", "acc", "ppi"),
    }


def test_single_instance_paths_use_main():
    assert is_multi_instance("pulse") is False
    assert ingest_path("pulse", "10") == "/ingest/10/pulse/main/default"
    assert stream_path("pulse", "10") == "/10/pulse/main/default"
    assert stream_key("pulse", "10") == "10/pulse/main/default"


def test_multi_instance_paths_require_instance_id():
    assert is_multi_instance("h10") is True
    assert ingest_path("h10", "11", "ecg", instance_id="6FFF5628") == (
        "/ingest/11/h10/6FFF5628/ecg"
    )
    assert stream_path("h10", "11", "ecg", instance_id="6FFF5628") == (
        "/11/h10/6FFF5628/ecg"
    )
    assert stream_key("h10", "11", "ecg", instance_id="6FFF5628") == (
        "11/h10/6FFF5628/ecg"
    )
    assert is_multi_instance("pacer") is True
    assert ingest_path("pacer", "pixel-7", "hr", instance_id="DA2E2324") == (
        "/ingest/pixel-7/pacer/DA2E2324/hr"
    )
    assert stream_path("pacer", "pixel-7", "acc", instance_id="DA2E2324") == (
        "/pixel-7/pacer/DA2E2324/acc"
    )
    assert stream_key("pacer", "pixel-7", "ppi", instance_id="DA2E2324") == (
        "pixel-7/pacer/DA2E2324/ppi"
    )


def test_number_concentration_stays_underscored_everywhere():
    assert "number_concentration" in system_streams("sen66")
    assert is_valid_stream("sen66", "number_concentration") is True
    assert ingest_path("sen66", "11", "number_concentration") == (
        "/ingest/11/sen66/main/number_concentration"
    )


def test_single_instance_systems_ignore_instance_argument():
    assert stream_path("gps", "11", instance_id=DEFAULT_INSTANCE) == (
        "/11/gps/main/default"
    )
