"""Process-global SSE ingest state and startup for the Pi-Pulse app."""

import asyncio
import logging
import math
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone

from shiny import reactive

from app.config import (
    DEVICES,
    GPS_DEVICES,
    H10_ACC_DYNAMIC_WINDOW_S,
    H10_DEVICES,
    PACER_ACC_DYNAMIC_WINDOW_S,
    PACER_DEVICES,
    PACER_MOTION_SUBWINDOW_S,
    SEN66_DEVICES,
)
from app.streams.consumer import stream_consumer

log = logging.getLogger(__name__)


def _first_numeric(data: dict, *keys: str, default: float = 0.0) -> float:
    for key in keys:
        value = data.get(key)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return float(value)
    return default


def _rr_intervals_ms(data: dict) -> list[float]:
    for key in ("rr_intervals_ms", "rr_ms", "rr_intervals", "rr"):
        value = data.get(key)
        if isinstance(value, (list, tuple)):
            return [
                float(item)
                for item in value
                if isinstance(item, (int, float)) and not isinstance(item, bool)
            ]
    return []


def normalize_h10_sample(data: dict) -> dict:
    sample = dict(data)
    rr_intervals = _rr_intervals_ms(sample)
    rr_last_fallback = rr_intervals[-1] if rr_intervals else 0.0
    rr_avg_fallback = sum(rr_intervals) / len(rr_intervals) if rr_intervals else 0.0

    sample["heart_rate_bpm"] = _first_numeric(
        sample,
        "heart_rate_bpm",
        "heart_rate",
        "hr",
        "bpm",
    )
    sample["rr_intervals_ms"] = rr_intervals
    sample["rr_last_ms"] = _first_numeric(
        sample,
        "rr_last_ms",
        "latest_rr_ms",
        "last_rr_ms",
        default=rr_last_fallback,
    )
    sample["rr_avg_ms"] = _first_numeric(
        sample,
        "rr_avg_ms",
        "avg_rr_ms",
        "average_rr_ms",
        default=rr_avg_fallback,
    )
    sample["rr_count"] = int(
        _first_numeric(sample, "rr_count", default=float(len(rr_intervals)))
    )
    return sample


def normalize_h10_ecg_chunk(data: dict) -> dict:
    sample_rate = data.get("sample_rate_hz", 130)
    if (
        not isinstance(sample_rate, int)
        or isinstance(sample_rate, bool)
        or sample_rate <= 0
    ):
        sample_rate = 130

    samples = data.get("samples_uv", [])
    if not isinstance(samples, list):
        samples = []

    return {
        "samples_uv": [
            int(sample)
            for sample in samples
            if isinstance(sample, (int, float)) and not isinstance(sample, bool)
        ],
        "sample_rate_hz": sample_rate,
    }


def normalize_h10_acc_chunk(data: dict) -> dict:
    sample_rate = data.get("sample_rate_hz", 200)
    if (
        not isinstance(sample_rate, int)
        or isinstance(sample_rate, bool)
        or sample_rate <= 0
    ):
        sample_rate = 200

    samples = data.get("samples_mg", [])
    if not isinstance(samples, list):
        samples = []

    normalized_samples = []
    for sample in samples:
        if not isinstance(sample, dict):
            continue
        x_mg = sample.get("x_mg")
        y_mg = sample.get("y_mg")
        z_mg = sample.get("z_mg")
        if any(
            not isinstance(value, (int, float)) or isinstance(value, bool)
            for value in (x_mg, y_mg, z_mg)
        ):
            continue
        normalized_samples.append(
            {
                "x_mg": float(x_mg),
                "y_mg": float(y_mg),
                "z_mg": float(z_mg),
            }
        )

    return {
        "samples_mg": normalized_samples,
        "sample_rate_hz": sample_rate,
    }


def normalize_gps_sample(data: dict) -> dict:
    sample = dict(data)
    sample["latitude"] = _first_numeric(sample, "latitude")
    sample["longitude"] = _first_numeric(sample, "longitude")
    sample["accuracy"] = _first_numeric(sample, "accuracy")
    sample["altitude"] = _first_numeric(sample, "altitude")
    sample["speed"] = _first_numeric(sample, "speed")
    sample["timestamp"] = str(sample.get("timestamp") or "")
    return sample


def normalize_pacer_hr_sample(data: dict) -> dict:
    return normalize_h10_sample(data)


def normalize_pacer_ppi_chunk(data: dict) -> dict:
    sample_rows = data.get("samples", [])
    if not isinstance(sample_rows, list):
        sample_rows = []

    normalized_samples = []
    for sample in sample_rows:
        if not isinstance(sample, dict):
            continue
        ppi_ms = sample.get("ppi_ms")
        if not isinstance(ppi_ms, (int, float)) or isinstance(ppi_ms, bool):
            continue
        error_estimate_ms = sample.get("error_estimate_ms", 0.0)
        if not isinstance(error_estimate_ms, (int, float)) or isinstance(
            error_estimate_ms, bool
        ):
            error_estimate_ms = 0.0
        timestamp_ns = sample.get("timestamp_ns")
        if not isinstance(timestamp_ns, int) or isinstance(timestamp_ns, bool):
            timestamp_ns = 0
        normalized_samples.append(
            {
                "ppi_ms": float(ppi_ms),
                "error_estimate_ms": float(error_estimate_ms),
                "heart_rate_bpm": _first_numeric(sample, "heart_rate_bpm", "heart_rate", "hr"),
                "blocker_bit": bool(sample.get("blocker_bit", False)),
                "skin_contact_status": bool(sample.get("skin_contact_status", False)),
                "skin_contact_supported": bool(
                    sample.get("skin_contact_supported", False)
                ),
                "timestamp_ns": timestamp_ns,
            }
        )

    return {
        "samples": normalized_samples,
        "timestamp": str(data.get("timestamp") or ""),
    }


def _mean_dynamic_acceleration_mg(samples_mg: list[dict]) -> float:
    if not samples_mg:
        return 0.0

    sample_count = len(samples_mg)
    mean_x = sum(sample["x_mg"] for sample in samples_mg) / sample_count
    mean_y = sum(sample["y_mg"] for sample in samples_mg) / sample_count
    mean_z = sum(sample["z_mg"] for sample in samples_mg) / sample_count

    dynamic_magnitudes = [
        math.sqrt(
            (sample["x_mg"] - mean_x) ** 2
            + (sample["y_mg"] - mean_y) ** 2
            + (sample["z_mg"] - mean_z) ** 2
        )
        for sample in samples_mg
    ]
    return sum(dynamic_magnitudes) / sample_count


def _mean_xyz_mg(samples_mg: list[dict]) -> tuple[float, float, float]:
    if not samples_mg:
        return 0.0, 0.0, 0.0

    sample_count = len(samples_mg)
    return (
        sum(sample["x_mg"] for sample in samples_mg) / sample_count,
        sum(sample["y_mg"] for sample in samples_mg) / sample_count,
        sum(sample["z_mg"] for sample in samples_mg) / sample_count,
    )


def _motion_subwindows(
    samples_mg: list[dict],
    sample_rate_hz: int,
    window_s: float,
) -> list[list[dict]]:
    if not samples_mg:
        return []
    window_size = max(1, int(round(max(sample_rate_hz, 1) * window_s)))
    return [
        samples_mg[start : start + window_size]
        for start in range(0, len(samples_mg), window_size)
    ]


def _payload_timestamp(data: dict) -> datetime | None:
    timestamp = data.get("timestamp")
    if not isinstance(timestamp, str) or not timestamp:
        return None
    try:
        parsed = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(timezone.utc).replace(tzinfo=None)
    return parsed


def _history_datetime_from_packet(data: dict) -> datetime:
    return _payload_timestamp(data) or datetime.now()


def _reactive_values(keys) -> dict[str, reactive.Value]:
    return {key: reactive.Value({}) for key in keys}


def _history_map(keys, *, maxlen: int) -> dict[str, deque]:
    return {key: deque(maxlen=maxlen) for key in keys}


@dataclass
class IngestState:
    pulse_latest: dict[str, reactive.Value]
    pulse_temp_history: dict[str, deque]
    sen66_latest: dict[str, reactive.Value]
    sen66_nc_latest: dict[str, reactive.Value]
    sen66_history: dict[str, deque]
    sen66_nc_history: dict[str, deque]
    gps_latest: dict[str, reactive.Value]
    gps_history: dict[str, deque]
    h10_latest: dict[str, reactive.Value]
    h10_history: dict[str, deque]
    h10_ecg_latest: dict[str, reactive.Value]
    h10_ecg_samples: dict[str, deque]
    h10_ecg_chunks: dict[str, deque]
    h10_ecg_total_samples: dict[str, int]
    h10_acc_latest: dict[str, reactive.Value]
    h10_acc_history: dict[str, deque]
    h10_acc_pending: dict[str, deque]
    h10_acc_sample_rate: dict[str, int]
    h10_motion_latest: dict[str, reactive.Value]
    h10_motion_trail: dict[str, deque]
    h10_motion_gravity: dict[str, tuple[float, float, float]]
    h10_motion_last_time: dict[str, float | None]
    pacer_hr_latest: dict[str, reactive.Value]
    pacer_hr_history: dict[str, deque]
    pacer_ppi_latest: dict[str, reactive.Value]
    pacer_ppi_history: dict[str, deque]
    pacer_acc_latest: dict[str, reactive.Value]
    pacer_acc_history: dict[str, deque]
    pacer_acc_pending: dict[str, deque]
    pacer_acc_sample_rate: dict[str, int]
    pacer_motion_latest: dict[str, reactive.Value]
    pacer_motion_trail: dict[str, deque]
    pacer_motion_gravity: dict[str, tuple[float, float, float]]
    started: bool = False
    tasks: list = field(default_factory=list)
    start_lock: threading.Lock = field(default_factory=threading.Lock)


def build_ingest_state() -> IngestState:
    h10_ecg_display_samples = 1300
    motion_trail_len = max(6, int(round(30 * H10_ACC_DYNAMIC_WINDOW_S)))

    return IngestState(
        pulse_latest=_reactive_values(DEVICES),
        pulse_temp_history=_history_map(DEVICES, maxlen=60),
        sen66_latest=_reactive_values(SEN66_DEVICES),
        sen66_nc_latest=_reactive_values(SEN66_DEVICES),
        sen66_history=_history_map(SEN66_DEVICES, maxlen=60),
        sen66_nc_history=_history_map(SEN66_DEVICES, maxlen=60),
        gps_latest=_reactive_values(GPS_DEVICES),
        gps_history=_history_map(GPS_DEVICES, maxlen=60),
        h10_latest=_reactive_values(H10_DEVICES),
        h10_history=_history_map(H10_DEVICES, maxlen=60),
        h10_ecg_latest=_reactive_values(H10_DEVICES),
        h10_ecg_samples={
            k: deque(maxlen=h10_ecg_display_samples) for k in H10_DEVICES
        },
        h10_ecg_chunks={k: deque(maxlen=64) for k in H10_DEVICES},
        h10_ecg_total_samples={k: 0 for k in H10_DEVICES},
        h10_acc_latest=_reactive_values(H10_DEVICES),
        h10_acc_history=_history_map(H10_DEVICES, maxlen=60),
        h10_acc_pending={k: deque() for k in H10_DEVICES},
        h10_acc_sample_rate={k: 200 for k in H10_DEVICES},
        h10_motion_latest=_reactive_values(H10_DEVICES),
        h10_motion_trail={k: deque(maxlen=motion_trail_len) for k in H10_DEVICES},
        h10_motion_gravity={k: (0.0, 0.0, 1000.0) for k in H10_DEVICES},
        h10_motion_last_time={k: None for k in H10_DEVICES},
        pacer_hr_latest=_reactive_values(PACER_DEVICES),
        pacer_hr_history=_history_map(PACER_DEVICES, maxlen=60),
        pacer_ppi_latest=_reactive_values(PACER_DEVICES),
        pacer_ppi_history=_history_map(PACER_DEVICES, maxlen=180),
        pacer_acc_latest=_reactive_values(PACER_DEVICES),
        pacer_acc_history=_history_map(PACER_DEVICES, maxlen=60),
        pacer_acc_pending={k: deque() for k in PACER_DEVICES},
        pacer_acc_sample_rate={k: 50 for k in PACER_DEVICES},
        pacer_motion_latest=_reactive_values(PACER_DEVICES),
        pacer_motion_trail={k: deque(maxlen=motion_trail_len) for k in PACER_DEVICES},
        pacer_motion_gravity={k: (0.0, 0.0, 1000.0) for k in PACER_DEVICES},
    )


GLOBAL_INGEST = build_ingest_state()


async def _on_pulse(state: IngestState, key: str, data: dict) -> None:
    state.pulse_temp_history[key].append((datetime.now(), data))
    state.pulse_latest[key].set(data)


async def _on_sen66(state: IngestState, key: str, data: dict) -> None:
    state.sen66_history[key].append((datetime.now(), data))
    state.sen66_latest[key].set(data)


async def _on_sen66_nc(state: IngestState, key: str, data: dict) -> None:
    state.sen66_nc_history[key].append((datetime.now(), data))
    state.sen66_nc_latest[key].set(data)


async def _on_gps(state: IngestState, key: str, data: dict) -> None:
    normalized = normalize_gps_sample(data)
    state.gps_history[key].append((_history_datetime_from_packet(normalized), normalized))
    state.gps_latest[key].set(normalized)


async def _on_h10(state: IngestState, key: str, data: dict) -> None:
    normalized = normalize_h10_sample(data)
    state.h10_history[key].append((_history_datetime_from_packet(normalized), normalized))
    state.h10_latest[key].set(normalized)


async def _on_h10_ecg(state: IngestState, key: str, data: dict) -> None:
    normalized = normalize_h10_ecg_chunk(data)
    if not normalized["samples_uv"]:
        return
    state.h10_ecg_samples[key].extend(normalized["samples_uv"])
    state.h10_ecg_total_samples[key] += len(normalized["samples_uv"])
    latest = {
        "samples_uv": list(normalized["samples_uv"]),
        "sample_rate_hz": normalized["sample_rate_hz"],
        "total_samples": state.h10_ecg_total_samples[key],
    }
    state.h10_ecg_chunks[key].append(latest)
    state.h10_ecg_latest[key].set(latest)


async def _on_h10_acc(state: IngestState, key: str, data: dict) -> None:
    normalized = normalize_h10_acc_chunk(data)
    if not normalized["samples_mg"]:
        return

    samples_mg = normalized["samples_mg"]
    state.h10_acc_sample_rate[key] = normalized["sample_rate_hz"]

    state.h10_acc_pending[key].extend(samples_mg)
    window_size = max(
        1, int(round(state.h10_acc_sample_rate[key] * H10_ACC_DYNAMIC_WINDOW_S))
    )
    while len(state.h10_acc_pending[key]) >= window_size:
        window_samples = [
            state.h10_acc_pending[key].popleft() for _ in range(window_size)
        ]
        aggregated = {
            "mean_dynamic_accel_mg": _mean_dynamic_acceleration_mg(window_samples),
            "sample_rate_hz": state.h10_acc_sample_rate[key],
        }
        state.h10_acc_history[key].append((_history_datetime_from_packet(data), aggregated))
        state.h10_acc_latest[key].set(aggregated)

    now = time.monotonic()
    last = state.h10_motion_last_time[key]
    dt = (
        (now - last)
        if last is not None
        else len(samples_mg) / max(state.h10_acc_sample_rate[key], 1)
    )
    state.h10_motion_last_time[key] = now
    mean_x, mean_y, mean_z = _mean_xyz_mg(samples_mg)
    gravity_x, gravity_y, gravity_z = state.h10_motion_gravity[key]
    gravity_alpha = min(1.0, dt / max(H10_ACC_DYNAMIC_WINDOW_S, 0.001))
    next_gravity = (
        gravity_x + ((mean_x - gravity_x) * gravity_alpha),
        gravity_y + ((mean_y - gravity_y) * gravity_alpha),
        gravity_z + ((mean_z - gravity_z) * gravity_alpha),
    )
    state.h10_motion_gravity[key] = next_gravity
    state.h10_motion_trail[key].append(next_gravity)
    state.h10_motion_latest[key].set(
        {"trail_points": list(state.h10_motion_trail[key])}
    )


async def _on_pacer_hr(state: IngestState, key: str, data: dict) -> None:
    normalized = normalize_pacer_hr_sample(data)
    state.pacer_hr_history[key].append((_history_datetime_from_packet(normalized), normalized))
    state.pacer_hr_latest[key].set(normalized)


async def _on_pacer_ppi(state: IngestState, key: str, data: dict) -> None:
    normalized = normalize_pacer_ppi_chunk(data)
    if not normalized["samples"]:
        return

    history_time = _history_datetime_from_packet(normalized)
    for sample in normalized["samples"]:
        state.pacer_ppi_history[key].append((history_time, sample))

    latest = dict(normalized["samples"][-1])
    latest["timestamp"] = normalized["timestamp"]
    state.pacer_ppi_latest[key].set(latest)


async def _on_pacer_acc(state: IngestState, key: str, data: dict) -> None:
    normalized = normalize_h10_acc_chunk(data)
    if not normalized["samples_mg"]:
        return

    samples_mg = normalized["samples_mg"]
    state.pacer_acc_sample_rate[key] = normalized["sample_rate_hz"]
    state.pacer_acc_pending[key].extend(samples_mg)
    window_size = max(
        1, int(round(state.pacer_acc_sample_rate[key] * PACER_ACC_DYNAMIC_WINDOW_S))
    )
    while len(state.pacer_acc_pending[key]) >= window_size:
        window_samples = [
            state.pacer_acc_pending[key].popleft() for _ in range(window_size)
        ]
        aggregated = {
            "mean_dynamic_accel_mg": _mean_dynamic_acceleration_mg(window_samples),
            "sample_rate_hz": state.pacer_acc_sample_rate[key],
        }
        state.pacer_acc_history[key].append((_history_datetime_from_packet(data), aggregated))
        state.pacer_acc_latest[key].set(aggregated)

    gravity_x, gravity_y, gravity_z = state.pacer_motion_gravity[key]
    for subwindow_samples in _motion_subwindows(
        samples_mg,
        state.pacer_acc_sample_rate[key],
        PACER_MOTION_SUBWINDOW_S,
    ):
        dt = len(subwindow_samples) / max(state.pacer_acc_sample_rate[key], 1)
        mean_x, mean_y, mean_z = _mean_xyz_mg(subwindow_samples)
        gravity_alpha = min(1.0, dt / max(PACER_ACC_DYNAMIC_WINDOW_S, 0.001))
        next_gravity = (
            gravity_x + ((mean_x - gravity_x) * gravity_alpha),
            gravity_y + ((mean_y - gravity_y) * gravity_alpha),
            gravity_z + ((mean_z - gravity_z) * gravity_alpha),
        )
        gravity_x, gravity_y, gravity_z = next_gravity
        state.pacer_motion_trail[key].append(next_gravity)

    state.pacer_motion_gravity[key] = (gravity_x, gravity_y, gravity_z)
    state.pacer_motion_latest[key].set(
        {"trail_points": list(state.pacer_motion_trail[key])}
    )


def _create_stream_tasks(state: IngestState) -> list:
    tasks = (
        [
            asyncio.create_task(
                stream_consumer(
                    f"pulse-{key}",
                    device["default"],
                    lambda data, key=key: _on_pulse(state, key, data),
                )
            )
            for key, device in DEVICES.items()
        ]
        + [
            asyncio.create_task(
                stream_consumer(
                    f"sen66-{key}",
                    device["default"],
                    lambda data, key=key: _on_sen66(state, key, data),
                )
            )
            for key, device in SEN66_DEVICES.items()
        ]
        + [
            asyncio.create_task(
                stream_consumer(
                    f"sen66-nc-{key}",
                    device["number_concentration"],
                    lambda data, key=key: _on_sen66_nc(state, key, data),
                )
            )
            for key, device in SEN66_DEVICES.items()
        ]
        + [
            asyncio.create_task(
                stream_consumer(
                    f"gps-{key}",
                    device["default"],
                    lambda data, key=key: _on_gps(state, key, data),
                )
            )
            for key, device in GPS_DEVICES.items()
        ]
        + [
            asyncio.create_task(
                stream_consumer(
                    f"h10-{key}",
                    device["default"],
                    lambda data, key=key: _on_h10(state, key, data),
                )
            )
            for key, device in H10_DEVICES.items()
        ]
        + [
            asyncio.create_task(
                stream_consumer(
                    f"h10-ecg-{key}",
                    device["ecg"],
                    lambda data, key=key: _on_h10_ecg(state, key, data),
                )
            )
            for key, device in H10_DEVICES.items()
            if device.get("ecg")
        ]
        + [
            asyncio.create_task(
                stream_consumer(
                    f"h10-acc-{key}",
                    device["acc"],
                    lambda data, key=key: _on_h10_acc(state, key, data),
                )
            )
            for key, device in H10_DEVICES.items()
            if device.get("acc")
        ]
        + [
            asyncio.create_task(
                stream_consumer(
                    f"pacer-hr-{key}",
                    device["hr"],
                    lambda data, key=key: _on_pacer_hr(state, key, data),
                )
            )
            for key, device in PACER_DEVICES.items()
            if device.get("hr")
        ]
        + [
            asyncio.create_task(
                stream_consumer(
                    f"pacer-acc-{key}",
                    device["acc"],
                    lambda data, key=key: _on_pacer_acc(state, key, data),
                )
            )
            for key, device in PACER_DEVICES.items()
            if device.get("acc")
        ]
        + [
            asyncio.create_task(
                stream_consumer(
                    f"pacer-ppi-{key}",
                    device["ppi"],
                    lambda data, key=key: _on_pacer_ppi(state, key, data),
                )
            )
            for key, device in PACER_DEVICES.items()
            if device.get("ppi")
        ]
    )
    for task in tasks:
        task.add_done_callback(lambda task, state=state: _on_consumer_done(state, task))
    return tasks


def _reset_task_set(state: IngestState) -> None:
    for task in state.tasks:
        if not task.done():
            task.cancel()
    state.tasks = []
    state.started = False


def _on_consumer_done(state: IngestState, task) -> None:
    if task.cancelled():
        return

    try:
        exc = task.exception()
    except Exception:
        exc = None

    if exc is not None:
        log.error(
            "Global ingest consumer exited unexpectedly; invalidating task set",
            exc_info=(type(exc), exc, exc.__traceback__),
        )
    else:
        log.warning("Global ingest consumer exited unexpectedly without an exception; invalidating task set")

    with state.start_lock:
        if task not in state.tasks:
            return
        _reset_task_set(state)


def _task_set_is_healthy(state: IngestState) -> bool:
    return state.started and bool(state.tasks) and all(not task.done() for task in state.tasks)


def ensure_global_ingest_started(state: IngestState = GLOBAL_INGEST) -> IngestState:
    if _task_set_is_healthy(state):
        return state

    with state.start_lock:
        if _task_set_is_healthy(state):
            return state
        if state.started or state.tasks:
            log.warning("Restarting global ingest consumer set")
            _reset_task_set(state)
        state.tasks = _create_stream_tasks(state)
        state.started = True
        log.info("Started global ingest consumer set with %d task(s)", len(state.tasks))
        return state
