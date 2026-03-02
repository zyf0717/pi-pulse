"""
Low-level Polar H10 protocol helpers.

This module keeps the PMD constants, start commands, and binary frame parsers
separate from the FastAPI/BLE service entrypoint in h10.py.
"""

import struct
from typing import List

H10_ADDRESS = "AA:BB:CC:DD:EE:01"

# Standard Bluetooth Heart Rate Measurement characteristic
HR_MEASUREMENT_UUID = "00002a37-0000-1000-8000-00805f9b34fb"

# Polar Measurement Data (PMD) — proprietary ECG/ACC service
PMD_CP_UUID = "FB005C81-02E7-F387-1CAD-8ACD2D8DF0C8"
PMD_DATA_UUID = "FB005C82-02E7-F387-1CAD-8ACD2D8DF0C8"

# Polar PMD measurement types used by this module.
PMD_MEAS_TYPE_ECG = 0x00
PMD_MEAS_TYPE_ACC = 0x02

ECG_SAMPLE_RATE_HZ = 130
ACC_SAMPLE_RATE_HZ = 200
ACC_RANGE_G = 8

# Command: start ECG at 130 Hz / 14-bit resolution
ECG_START_CMD = bytearray(
    [
        0x02,
        PMD_MEAS_TYPE_ECG,  # op=START_MEASUREMENT, type=ECG
        0x00,
        0x01,
        0x82,
        0x00,  # setting SAMPLE_RATE=130 (uint16 LE)
        0x01,
        0x01,
        0x0E,
        0x00,  # setting RESOLUTION=14  (uint16 LE)
    ]
)

# Command: start ACC at 200 Hz / 16-bit resolution / 8G range
ACC_START_CMD = bytearray(
    [
        0x02,
        PMD_MEAS_TYPE_ACC,  # op=START_MEASUREMENT, type=ACC
        0x00,
        0x01,
        0xC8,
        0x00,  # setting SAMPLE_RATE=200 (uint16 LE)
        0x01,
        0x01,
        0x10,
        0x00,  # setting RESOLUTION=16 (uint16 LE)
        0x02,
        0x01,
        0x08,
        0x00,  # setting RANGE=8G (uint16 LE)
    ]
)


def parse_hr_measurement(data: bytes) -> dict:
    """
    Parse a Bluetooth Heart Rate Measurement characteristic packet.

    Flags byte (byte 0):
      bit 0  – HR value format: 0 = UINT8, 1 = UINT16
      bit 4  – RR interval(s) present
    """
    flags = data[0]
    hr_uint16 = bool(flags & 0x01)
    rr_present = bool(flags & 0x10)

    offset = 1
    if hr_uint16:
        bpm = struct.unpack_from("<H", data, offset)[0]
        offset += 2
    else:
        bpm = data[offset]
        offset += 1

    rr_ms: List[int] = []
    if rr_present:
        while offset + 1 < len(data):
            raw = struct.unpack_from("<H", data, offset)[0]
            offset += 2
            rr_ms.append(round(raw * 1000 / 1024))

    return {"bpm": bpm, "rr_ms": rr_ms}


def _sign_extend_24(raw: int) -> int:
    return raw - 0x1000000 if raw >= 0x800000 else raw


def parse_ecg_frame(data: bytes) -> List[int]:
    """
    Parse a Polar PMD Data notification carrying ECG samples.

    Only uncompressed Type 0 ECG frames are supported here.
    """
    if len(data) < 10:
        raise ValueError(f"PMD frame too short: {len(data)} bytes")

    meas_type = data[0]
    if meas_type != PMD_MEAS_TYPE_ECG:
        raise ValueError(
            f"Expected ECG ({PMD_MEAS_TYPE_ECG:#04x}), got measurement type {meas_type:#04x}"
        )

    frame_type_byte = data[9]
    compressed = bool(frame_type_byte & 0x80)
    frame_type = frame_type_byte & 0x7F

    if compressed:
        raise ValueError(
            f"Compressed ECG frames are not supported (frame type byte {frame_type_byte:#04x})"
        )
    if frame_type != 0:
        raise ValueError(
            f"Unsupported ECG frame type {frame_type} (only Type 0 implemented)"
        )

    samples: List[int] = []
    payload = data[10:]
    for i in range(0, len(payload) - 2, 3):
        raw = payload[i] | (payload[i + 1] << 8) | (payload[i + 2] << 16)
        samples.append(_sign_extend_24(raw))

    return samples


def _parse_acc_type0(payload: bytes) -> List[dict]:
    samples: List[dict] = []
    for i in range(0, len(payload) - 2, 3):
        x_mg = struct.unpack_from("<b", payload, i)[0]
        y_mg = struct.unpack_from("<b", payload, i + 1)[0]
        z_mg = struct.unpack_from("<b", payload, i + 2)[0]
        samples.append({"x_mg": x_mg, "y_mg": y_mg, "z_mg": z_mg})
    return samples


def _parse_acc_type1(payload: bytes) -> List[dict]:
    samples: List[dict] = []
    for i in range(0, len(payload) - 5, 6):
        x_mg, y_mg, z_mg = struct.unpack_from("<hhh", payload, i)
        samples.append({"x_mg": x_mg, "y_mg": y_mg, "z_mg": z_mg})
    return samples


def _parse_acc_type2(payload: bytes) -> List[dict]:
    samples: List[dict] = []
    for i in range(0, len(payload) - 8, 9):
        x_mg = _sign_extend_24(
            payload[i] | (payload[i + 1] << 8) | (payload[i + 2] << 16)
        )
        y_mg = _sign_extend_24(
            payload[i + 3] | (payload[i + 4] << 8) | (payload[i + 5] << 16)
        )
        z_mg = _sign_extend_24(
            payload[i + 6] | (payload[i + 7] << 8) | (payload[i + 8] << 16)
        )
        samples.append({"x_mg": x_mg, "y_mg": y_mg, "z_mg": z_mg})
    return samples


def parse_acc_frame(data: bytes) -> List[dict]:
    """
    Parse a Polar PMD Data notification carrying accelerometer samples.

    Supported frame types:
      0 = Type 0 — int8 per axis
      1 = Type 1 — int16 LE per axis
      2 = Type 2 — int24 LE per axis
    """
    if len(data) < 10:
        raise ValueError(f"PMD frame too short: {len(data)} bytes")

    meas_type = data[0]
    if meas_type != PMD_MEAS_TYPE_ACC:
        raise ValueError(
            f"Expected ACC ({PMD_MEAS_TYPE_ACC:#04x}), got measurement type {meas_type:#04x}"
        )

    frame_type_byte = data[9]
    compressed = bool(frame_type_byte & 0x80)
    frame_type = frame_type_byte & 0x7F

    if compressed:
        raise ValueError(
            f"Compressed ACC frames are not supported (frame type byte {frame_type_byte:#04x})"
        )

    payload = data[10:]
    if frame_type == 0:
        return _parse_acc_type0(payload)
    if frame_type == 1:
        return _parse_acc_type1(payload)
    if frame_type == 2:
        return _parse_acc_type2(payload)

    raise ValueError(f"Unsupported ACC frame type {frame_type}")
