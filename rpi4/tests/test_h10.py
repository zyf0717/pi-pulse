"""Tests for rpi4/h10.py."""

import importlib.util
import struct
from pathlib import Path

RPI4_DIR = Path(__file__).resolve().parents[1]


def _load_h10():
    spec = importlib.util.spec_from_file_location("rpi4_h10_fresh", RPI4_DIR / "h10.py")
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


def _build_packet(
    bpm: int, rr_raw: list[int] = (), uint16_hr: bool = False, rr_present: bool = False
) -> bytes:
    flags = 0
    if uint16_hr:
        flags |= 0x01
    if rr_present:
        flags |= 0x10
    parts = [bytes([flags])]
    if uint16_hr:
        parts.append(struct.pack("<H", bpm))
    else:
        parts.append(bytes([bpm]))
    for rr in rr_raw:
        parts.append(struct.pack("<H", rr))
    return b"".join(parts)


def _build_ecg_packet(
    samples_uv: list[int], meas_type: int = 0x00, frame_type_byte: int = 0x00
) -> bytes:
    header = bytes([meas_type]) + b"\x00" * 8 + bytes([frame_type_byte])
    payload = b""
    for uv in samples_uv:
        unsigned = uv & 0xFFFFFF
        payload += bytes(
            [unsigned & 0xFF, (unsigned >> 8) & 0xFF, (unsigned >> 16) & 0xFF]
        )
    return header + payload


def _build_acc_packet(
    samples_xyz_mg: list[tuple[int, int, int]],
    meas_type: int = 0x02,
    frame_type_byte: int = 0x01,
) -> bytes:
    header = bytes([meas_type]) + b"\x00" * 8 + bytes([frame_type_byte])
    payload = b""
    frame_type = frame_type_byte & 0x7F

    for x_mg, y_mg, z_mg in samples_xyz_mg:
        if frame_type == 0:
            payload += struct.pack("<bbb", x_mg, y_mg, z_mg)
            continue
        if frame_type == 1:
            payload += struct.pack("<hhh", x_mg, y_mg, z_mg)
            continue
        if frame_type == 2:
            for axis in (x_mg, y_mg, z_mg):
                unsigned = axis & 0xFFFFFF
                payload += bytes(
                    [unsigned & 0xFF, (unsigned >> 8) & 0xFF, (unsigned >> 16) & 0xFF]
                )
            continue
        raise ValueError(f"unsupported test frame type {frame_type}")
    return header + payload


def test_parse_hr_uint8_format_no_rr():
    h10 = _load_h10()
    result = h10.parse_hr_measurement(_build_packet(bpm=72))
    assert result == {"bpm": 72, "rr_ms": []}


def test_parse_hr_uint16_and_rr_values():
    h10 = _load_h10()
    result = h10.parse_hr_measurement(
        _build_packet(bpm=200, rr_raw=[512, 1024], uint16_hr=True, rr_present=True)
    )
    assert result["bpm"] == 200
    assert result["rr_ms"] == [500, 1000]


def test_parse_ecg_frame_positive_and_negative_samples():
    h10 = _load_h10()
    samples = [100, -100, -8388608]
    assert h10.parse_ecg_frame(_build_ecg_packet(samples)) == samples


def test_parse_ecg_frame_raises_on_short_frame():
    h10 = _load_h10()
    import pytest

    with pytest.raises(ValueError, match="too short"):
        h10.parse_ecg_frame(b"\x00" * 9)


def test_parse_ecg_frame_raises_on_wrong_measurement_type():
    h10 = _load_h10()
    import pytest

    with pytest.raises(ValueError, match="ECG"):
        h10.parse_ecg_frame(_build_ecg_packet([100], meas_type=h10.PMD_MEAS_TYPE_ACC))


def test_parse_acc_frame_type1_xyz_samples():
    h10 = _load_h10()
    packet = _build_acc_packet([(10, -20, 30), (-1000, 0, 1000)])
    assert h10.parse_acc_frame(packet) == [
        {"x_mg": 10, "y_mg": -20, "z_mg": 30},
        {"x_mg": -1000, "y_mg": 0, "z_mg": 1000},
    ]


def test_parse_acc_frame_type2_xyz_samples():
    h10 = _load_h10()
    packet = _build_acc_packet([(1_000, -2_000, 3_000)], frame_type_byte=0x02)
    assert h10.parse_acc_frame(packet) == [
        {"x_mg": 1_000, "y_mg": -2_000, "z_mg": 3_000}
    ]


def test_parse_acc_frame_raises_on_unsupported_frame_type():
    h10 = _load_h10()
    import pytest

    header = bytes([h10.PMD_MEAS_TYPE_ACC]) + b"\x00" * 8 + bytes([0x03])
    with pytest.raises(ValueError, match="frame type"):
        h10.parse_acc_frame(header + b"\x01\x02\x03")


def test_build_notification_handlers_publish_expected_stream_payloads():
    h10 = _load_h10()
    published = []
    hr_handler, pmd_handler = h10.build_notification_handlers(
        "6FFF5628",
        lambda stream_name, payload: published.append((stream_name, payload)),
    )

    hr_handler(0, bytearray(_build_packet(72, rr_raw=[1024], rr_present=True)))
    pmd_handler(0, bytearray(_build_ecg_packet([100, -200, 300])))
    pmd_handler(0, bytearray(_build_acc_packet([(1, -2, 3)])))

    assert published == [
        ("default", {"bpm": 72, "rr_ms": [1000]}),
        ("ecg", {"samples_uv": [100, -200, 300], "sample_rate_hz": 130}),
        (
            "acc",
            {
                "samples_mg": [{"x_mg": 1, "y_mg": -2, "z_mg": 3}],
                "sample_rate_hz": 200,
                "range_g": 8,
            },
        ),
    ]


def test_build_notification_handlers_drops_invalid_pmd_frames():
    h10 = _load_h10()
    published = []
    _, pmd_handler = h10.build_notification_handlers(
        "6FFF5628",
        lambda stream_name, payload: published.append((stream_name, payload)),
    )

    pmd_handler(0, bytearray(b"\x00" * 9))

    assert published == []
