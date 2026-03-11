import asyncio
import sys
import time
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

import httpx
import psutil

if __package__ in (None, ""):
    sys.path.append(str(Path(__file__).resolve().parents[1]))

from rpi4.relay_push import (
    detect_node_id,
    log_post_failure,
    now_iso,
    post_payload,
    relay_timeout,
)
from shared.streams import ingest_path


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

    try:
        temps = psutil.sensors_temperatures(fahrenheit=False) or {}
        if "cpu_thermal" in temps and temps["cpu_thermal"]:
            return round(float(temps["cpu_thermal"][0].current), 1)
        for entries in temps.values():
            if entries:
                return round(float(entries[0].current), 1)
    except Exception:
        pass

    return None


def get_net_totals(pernic: Dict[str, Any]) -> Dict[str, int]:
    """Sum RX/TX bytes across non-loopback, up interfaces when possible."""
    try:
        if_stats: Dict[str, Any] = psutil.net_if_stats() or {}
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
    """Collect one metrics snapshot."""
    now = time.monotonic()
    dt = max(now - last_ts, 1e-6)

    cpu_total = psutil.cpu_percent(interval=None)
    cpu_per_core = psutil.cpu_percent(interval=None, percpu=True)

    freq_info = psutil.cpu_freq(percpu=True)
    if freq_info:
        freq_per_core_mhz = [round(f.current, 1) if f else None for f in freq_info]
        cur = [f.current for f in freq_info if f and f.current is not None]
        freq_avg_mhz = round(sum(cur) / len(cur), 1) if cur else None
    else:
        f = psutil.cpu_freq()
        freq_per_core_mhz = None
        freq_avg_mhz = round(f.current, 1) if f and f.current is not None else None

    vm = psutil.virtual_memory()
    soc_temp_c = read_soc_temp_c()

    raw_net = psutil.net_io_counters(pernic=True) or {}
    net_now = get_net_totals(raw_net)
    rx_bps = max(0, (net_now["rx_bytes"] - last_net["rx_bytes"]) / dt)
    tx_bps = max(0, (net_now["tx_bytes"] - last_net["tx_bytes"]) / dt)

    stats: Dict[str, Any] = {
        "timestamp": now_iso(),
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
        "cpu": cpu_total,
        "mem": vm.percent,
        "temp": soc_temp_c if soc_temp_c is not None else "N/A",
    }

    return stats, now, net_now


async def push_metrics_loop(
    *,
    node_id: Optional[str] = None,
    sample_period_s: float = 1.0,
    max_frames: Optional[int] = None,
    client_factory=httpx.AsyncClient,
) -> None:
    """Push Pi metrics snapshots to the relay."""
    node_id = node_id or detect_node_id()
    path = ingest_path("pulse", node_id)

    psutil.cpu_percent(interval=None)
    psutil.cpu_percent(interval=None, percpu=True)

    last_ts = time.monotonic()
    last_net = get_net_totals(psutil.net_io_counters(pernic=True) or {})

    frame = 0
    async with client_factory(timeout=relay_timeout()) as client:
        while max_frames is None or frame < max_frames:
            payload, last_ts, last_net = collect_metrics(last_ts, last_net)
            try:
                await post_payload(client, path, payload)
            except Exception as exc:
                log_post_failure("pulse", exc)
            frame += 1
            if max_frames is None or frame < max_frames:
                await asyncio.sleep(sample_period_s)


async def main() -> None:
    await push_metrics_loop()


if __name__ == "__main__":
    asyncio.run(main())


async def main() -> None:
    await push_metrics_loop()


if __name__ == "__main__":
    asyncio.run(main())
