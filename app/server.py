import asyncio
import math
import time
from collections import deque
from datetime import datetime

import plotly.graph_objects as go
import shinyswatch
from shiny import reactive

from app.config import DEVICES, H10_ACC_DYNAMIC_WINDOW_S, H10_DEVICES, SEN66_DEVICES
from app.renders.h10 import register_h10_renders
from app.renders.pulse import register_pulse_renders
from app.renders.sen66 import register_sen66_renders
from app.streams.consumer import stream_consumer


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


def _normalize_h10_sample(data: dict) -> dict:
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


def _normalize_h10_ecg_chunk(data: dict) -> dict:
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


def _normalize_h10_acc_chunk(data: dict) -> dict:
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


def server(input, output, session):
    shinyswatch.theme_picker_server()

    # ── Plotly template (tracks chart_style input) ────────────────────────────
    @reactive.calc
    def plotly_tpl() -> str:
        return input.chart_style()

    # ── Pi-pulse state ────────────────────────────────────────────────────────
    _pulse_default = {
        "cpu": 0.0,
        "mem": 0.0,
        "temp": 0.0,
        "cpu_freq_avg_mhz": 0.0,
        "net_rx_bps_total": 0,
        "net_tx_bps_total": 0,
    }
    pulse_latest: dict[str, reactive.Value] = {
        k: reactive.Value(dict(_pulse_default)) for k in DEVICES
    }
    pulse_temp_history: dict[str, deque] = {k: deque(maxlen=60) for k in DEVICES}

    # ── SEN66 state ───────────────────────────────────────────────────────────
    _sen66_default = {
        "temperature_c": 0.0,
        "humidity_rh": 0.0,
        "co2_ppm": 0,
        "voc_index": 0.0,
        "nox_index": 0.0,
        "pm1_0_ugm3": 0.0,
        "pm2_5_ugm3": 0.0,
        "pm4_0_ugm3": 0.0,
        "pm10_0_ugm3": 0.0,
    }
    _sen66_nc_default = {
        "nc_pm0_5_pcm3": 0.0,
        "nc_pm1_0_pcm3": 0.0,
        "nc_pm2_5_pcm3": 0.0,
        "nc_pm4_0_pcm3": 0.0,
        "nc_pm10_0_pcm3": 0.0,
    }
    sen66_latest: dict[str, reactive.Value] = {
        k: reactive.Value(dict(_sen66_default)) for k in SEN66_DEVICES
    }
    sen66_nc_latest: dict[str, reactive.Value] = {
        k: reactive.Value(dict(_sen66_nc_default)) for k in SEN66_DEVICES
    }
    sen66_history: dict[str, deque] = {k: deque(maxlen=60) for k in SEN66_DEVICES}
    sen66_nc_history: dict[str, deque] = {k: deque(maxlen=60) for k in SEN66_DEVICES}

    # ── H10 state ─────────────────────────────────────────────────────────────
    _h10_default = {
        "heart_rate_bpm": 0.0,
        "rr_avg_ms": 0.0,
        "rr_last_ms": 0.0,
        "rr_count": 0,
        "rr_intervals_ms": [],
    }
    h10_latest: dict[str, reactive.Value] = {
        k: reactive.Value(dict(_h10_default)) for k in H10_DEVICES
    }
    h10_history: dict[str, deque] = {k: deque(maxlen=60) for k in H10_DEVICES}
    _h10_ecg_default = {
        "samples_uv": [],
        "sample_rate_hz": 130,
    }
    h10_ecg_latest: dict[str, reactive.Value] = {
        k: reactive.Value(dict(_h10_ecg_default)) for k in H10_DEVICES
    }
    _h10_ecg_display_samples = 260  # 2 s at 130 Hz
    h10_ecg_samples: dict[str, deque] = {
        k: deque(maxlen=_h10_ecg_display_samples) for k in H10_DEVICES
    }
    h10_ecg_sample_rate: dict[str, int] = {k: 130 for k in H10_DEVICES}
    _h10_acc_default = {
        "mean_dynamic_accel_mg": 0.0,
        "sample_rate_hz": 200,
    }
    h10_acc_latest: dict[str, reactive.Value] = {
        k: reactive.Value(dict(_h10_acc_default)) for k in H10_DEVICES
    }
    h10_acc_history: dict[str, deque] = {k: deque(maxlen=60) for k in H10_DEVICES}
    h10_acc_pending: dict[str, deque] = {k: deque() for k in H10_DEVICES}
    h10_acc_sample_rate: dict[str, int] = {k: 200 for k in H10_DEVICES}
    _h10_motion_default = {"trail_points": []}
    h10_motion_latest: dict[str, reactive.Value] = {
        k: reactive.Value(dict(_h10_motion_default)) for k in H10_DEVICES
    }
    motion_trail_len = max(6, int(round(30 * H10_ACC_DYNAMIC_WINDOW_S)))
    h10_motion_trail: dict[str, deque] = {
        k: deque(maxlen=motion_trail_len) for k in H10_DEVICES
    }
    h10_motion_gravity: dict[str, tuple[float, float, float]] = {
        k: (0.0, 0.0, 1000.0) for k in H10_DEVICES
    }
    h10_motion_last_time: dict[str, float | None] = {k: None for k in H10_DEVICES}

    # ── SSE callbacks ─────────────────────────────────────────────────────────
    async def on_pulse(key: str, data: dict):
        pulse_temp_history[key].append((datetime.now(), data))
        pulse_latest[key].set(data)

    async def on_sen66(key: str, data: dict):
        sen66_history[key].append((datetime.now(), data))
        sen66_latest[key].set(data)

    async def on_sen66_nc(key: str, data: dict):
        sen66_nc_history[key].append((datetime.now(), data))
        sen66_nc_latest[key].set(data)

    async def on_h10(key: str, data: dict):
        normalized = _normalize_h10_sample(data)
        h10_history[key].append((datetime.now(), normalized))
        h10_latest[key].set(normalized)

    async def on_h10_ecg(key: str, data: dict):
        normalized = _normalize_h10_ecg_chunk(data)
        if not normalized["samples_uv"]:
            return
        h10_ecg_samples[key].extend(normalized["samples_uv"])
        h10_ecg_sample_rate[key] = normalized["sample_rate_hz"]
        h10_ecg_latest[key].set({
            "samples_uv": list(h10_ecg_samples[key]),
            "sample_rate_hz": h10_ecg_sample_rate[key],
        })

    async def on_h10_acc(key: str, data: dict):
        normalized = _normalize_h10_acc_chunk(data)
        if not normalized["samples_mg"]:
            return
        samples_mg = normalized["samples_mg"]
        h10_acc_sample_rate[key] = normalized["sample_rate_hz"]

        # ── Dynamic acceleration ───────────────────────────────────────────────
        h10_acc_pending[key].extend(samples_mg)
        window_size = max(
            1, int(round(h10_acc_sample_rate[key] * H10_ACC_DYNAMIC_WINDOW_S))
        )
        while len(h10_acc_pending[key]) >= window_size:
            second_samples = [
                h10_acc_pending[key].popleft() for _ in range(window_size)
            ]
            aggregated = {
                "mean_dynamic_accel_mg": _mean_dynamic_acceleration_mg(second_samples),
                "sample_rate_hz": h10_acc_sample_rate[key],
            }
            h10_acc_history[key].append((datetime.now(), aggregated))
            h10_acc_latest[key].set(aggregated)

        # ── Gravity / motion trail ─────────────────────────────────────────────
        now = time.monotonic()
        last = h10_motion_last_time[key]
        dt = (
            (now - last)
            if last is not None
            else len(samples_mg) / max(h10_acc_sample_rate[key], 1)
        )
        h10_motion_last_time[key] = now
        mean_x, mean_y, mean_z = _mean_xyz_mg(samples_mg)
        gravity_x, gravity_y, gravity_z = h10_motion_gravity[key]
        gravity_alpha = min(1.0, dt / max(H10_ACC_DYNAMIC_WINDOW_S, 0.001))
        next_gravity = (
            gravity_x + ((mean_x - gravity_x) * gravity_alpha),
            gravity_y + ((mean_y - gravity_y) * gravity_alpha),
            gravity_z + ((mean_z - gravity_z) * gravity_alpha),
        )
        h10_motion_gravity[key] = next_gravity
        h10_motion_trail[key].append(next_gravity)
        h10_motion_latest[key].set({"trail_points": list(h10_motion_trail[key])})

    # ── Start all streams at session open ─────────────────────────────────────
    tasks = (
        [
            asyncio.create_task(
                stream_consumer(f"pulse-{k}", v["url"], lambda d, k=k: on_pulse(k, d))
            )
            for k, v in DEVICES.items()
        ]
        + [
            asyncio.create_task(
                stream_consumer(
                    f"sen66-{k}", v["stream"], lambda d, k=k: on_sen66(k, d)
                )
            )
            for k, v in SEN66_DEVICES.items()
        ]
        + [
            asyncio.create_task(
                stream_consumer(
                    f"sen66-nc-{k}", v["nc_stream"], lambda d, k=k: on_sen66_nc(k, d)
                )
            )
            for k, v in SEN66_DEVICES.items()
        ]
        + [
            asyncio.create_task(
                stream_consumer(f"h10-{k}", v["stream"], lambda d, k=k: on_h10(k, d))
            )
            for k, v in H10_DEVICES.items()
        ]
        + [
            asyncio.create_task(
                stream_consumer(
                    f"h10-ecg-{k}",
                    v["ecg_stream"],
                    lambda d, k=k: on_h10_ecg(k, d),
                )
            )
            for k, v in H10_DEVICES.items()
            if v.get("ecg_stream")
        ]
        + [
            asyncio.create_task(
                stream_consumer(
                    f"h10-acc-{k}",
                    v["acc_stream"],
                    lambda d, k=k: on_h10_acc(k, d),
                )
            )
            for k, v in H10_DEVICES.items()
            if v.get("acc_stream")
        ]
    )
    session.on_ended(lambda: [t.cancel() for t in tasks])

    # ── Register renders ──────────────────────────────────────────────────────
    pulse_widget = go.FigureWidget(layout=dict(autosize=True, height=400))
    pulse_state: dict = {"chart": None, "dev": None, "tpl": None}
    register_pulse_renders(
        input, pulse_latest, pulse_temp_history, plotly_tpl, pulse_widget, pulse_state
    )

    sen66_widget = go.FigureWidget(layout=dict(autosize=True, height=400))
    sen66_state: dict = {"chart": None, "dev": None, "tpl": None}
    register_sen66_renders(
        input,
        sen66_latest,
        sen66_nc_latest,
        sen66_history,
        sen66_nc_history,
        plotly_tpl,
        sen66_widget,
        sen66_state,
    )

    h10_widget = go.FigureWidget(layout=dict(autosize=True, height=400))
    h10_state: dict = {"chart": None, "dev": None, "tpl": None}
    register_h10_renders(
        input,
        h10_latest,
        h10_history,
        h10_ecg_latest,
        h10_ecg_samples,
        h10_acc_latest,
        h10_acc_history,
        h10_motion_latest,
        plotly_tpl,
        h10_widget,
        h10_state,
    )
