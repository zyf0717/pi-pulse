import asyncio
import json
import time
from typing import Any, Dict, Optional, Tuple

import psutil
from fastapi import FastAPI
from fastapi.responses import StreamingResponse

app = FastAPI(title="Pi-Pulse Metrics")


def read_soc_temp_c() -> Optional[float]:
    """
    Raspberry Pi SoC temp is usually exposed at:
      /sys/class/thermal/thermal_zone0/temp  (millidegrees C)
    Fallback to psutil sensors if available.
    """
    sysfs_paths = [
        "/sys/class/thermal/thermal_zone0/temp",
        "/sys/devices/virtual/thermal/thermal_zone0/temp",
    ]
    for p in sysfs_paths:
        try:
            with open(p, "r") as f:
                v = f.read().strip()
            if v:
                mc = int(v)
                return round(mc / 1000.0, 1)
        except Exception:
            pass

    # Fallback (may or may not exist depending on config)
    try:
        temps = psutil.sensors_temperatures(fahrenheit=False) or {}
        # Common Pi key is cpu_thermal; keep it generic if present
        if "cpu_thermal" in temps and temps["cpu_thermal"]:
            return round(float(temps["cpu_thermal"][0].current), 1)
        # Otherwise try any first available sensor
        for entries in temps.values():
            if entries:
                return round(float(entries[0].current), 1)
    except Exception:
        pass

    return None


def get_net_totals(pernic: Dict[str, Any]) -> Dict[str, int]:
    """
    Sum RX/TX bytes across non-loopback, "up" interfaces when possible.
    """
    if_stats: Dict[str, Any] = {}
    try:
        if_stats = psutil.net_if_stats() or {}
    except Exception:
        if_stats = {}

    rx = 0
    tx = 0
    for nic, io in pernic.items():
        if nic == "lo":
            continue
        st = if_stats.get(nic)
        if st is not None and not st.isup:
            continue
        rx += int(io.bytes_recv)
        tx += int(io.bytes_sent)
    return {"rx_bytes": rx, "tx_bytes": tx}


def collect_metrics(
    last_ts: float, last_net: Dict[str, int]
) -> Tuple[Dict[str, Any], float, Dict[str, int]]:
    """Collect one metrics snapshot.

    Returns (stats_dict, new_timestamp, new_net_totals).
    Pure synchronous function — directly unit-testable without async machinery.
    """
    now = time.monotonic()
    dt = max(now - last_ts, 1e-6)

    # CPU utilization (non-blocking, computed since last call)
    cpu_total = psutil.cpu_percent(interval=None)
    cpu_per_core = psutil.cpu_percent(interval=None, percpu=True)

    # CPU frequency
    # On Pi, psutil.cpu_freq(percpu=True) may return per-core or None depending on kernel/config.
    freq_info = psutil.cpu_freq(percpu=True)
    if freq_info:
        freq_per_core_mhz = [round(f.current, 1) if f else None for f in freq_info]
        cur = [f.current for f in freq_info if f and f.current is not None]
        freq_avg_mhz = round(sum(cur) / len(cur), 1) if cur else None
    else:
        f = psutil.cpu_freq()
        freq_per_core_mhz = None
        freq_avg_mhz = round(f.current, 1) if f and f.current is not None else None

    # Memory
    vm = psutil.virtual_memory()

    # SoC temperature
    soc_temp_c = read_soc_temp_c()

    # Network throughput (total); clamp to 0 to handle counter resets / rollovers.
    raw_net = psutil.net_io_counters(pernic=True) or {}
    net_now = get_net_totals(raw_net)
    rx_bps = max(0, (net_now["rx_bytes"] - last_net["rx_bytes"]) / dt)
    tx_bps = max(0, (net_now["tx_bytes"] - last_net["tx_bytes"]) / dt)

    stats: Dict[str, Any] = {
        "cpu_total_pct": cpu_total,
        "cpu_per_core_pct": cpu_per_core,
        "cpu_freq_avg_mhz": freq_avg_mhz,
        "cpu_freq_per_core_mhz": freq_per_core_mhz,
        "mem_pct": vm.percent,
        "mem_used_bytes": int(vm.used),
        "mem_available_bytes": int(vm.available),
        "soc_temp_c": soc_temp_c if soc_temp_c is not None else "N/A",
        "net_rx_bps_total": int(rx_bps),
        "net_tx_bps_total": int(tx_bps),
        # Backward-compatible aliases for legacy consumers
        "cpu": cpu_total,
        "mem": vm.percent,
        "temp": soc_temp_c if soc_temp_c is not None else "N/A",
    }

    return stats, now, net_now


async def metric_stream(sample_period_s: float = 1.0, max_frames: Optional[int] = None):
    """Async generator yielding SSE-formatted system metric frames.

    Args:
        sample_period_s: Seconds between frames (default 1.0).
        max_frames: Terminate after this many frames. ``None`` (default) runs
                    forever (production). Pass ``1`` in tests to get a single
                    frame and have the generator exit naturally — no patching or
                    cancellation required.
    """
    # Prime psutil's non-blocking CPU% counters.
    psutil.cpu_percent(interval=None)
    psutil.cpu_percent(interval=None, percpu=True)

    last_ts = time.monotonic()
    raw_net = psutil.net_io_counters(pernic=True) or {}
    last_net = get_net_totals(raw_net)

    frame = 0
    try:
        while max_frames is None or frame < max_frames:
            stats, last_ts, last_net = collect_metrics(last_ts, last_net)
            yield f"data: {json.dumps(stats)}\n\n"
            frame += 1
            # Skip the sleep after the final frame so the generator exits cleanly.
            if max_frames is None or frame < max_frames:
                await asyncio.sleep(sample_period_s)
    except asyncio.CancelledError:
        return


@app.get("/health")
async def health():
    return {"status": "pulsing"}


@app.get("/stream")
async def stream():
    headers = {
        "Cache-Control": "no-cache",
        "X-Accel-Buffering": "no",
    }
    return StreamingResponse(
        metric_stream(), media_type="text/event-stream", headers=headers
    )
