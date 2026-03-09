import asyncio
from contextlib import asynccontextmanager
from typing import Dict, Optional

import httpx
from sensirion_driver_adapters.i2c_adapter.i2c_channel import I2cChannel
from sensirion_i2c_driver import CrcCalculator, I2cConnection, LinuxI2cTransceiver
from sensirion_i2c_sen66.device import Sen66Device

try:
    from relay_push import detect_node_id, log_post_failure, post_payload, relay_timeout
except ImportError:
    from rpi4.relay_push import (
        detect_node_id,
        log_post_failure,
        post_payload,
        relay_timeout,
    )


def _safe(signal):
    """Return the scaled float value of a Sensirion Signal object, or None on error."""
    try:
        v = signal.value
        return round(v, 3) if v is not None else None
    except Exception:
        return None


def read_environmental(snsr) -> Dict:
    """Read one environmental snapshot from the sensor."""
    try:
        (
            pm1p0,
            pm2p5,
            pm4p0,
            pm10p0,
            humidity,
            temperature,
            voc_index,
            nox_index,
            co2,
        ) = snsr.read_measured_values()

        return {
            "temperature_c": _safe(temperature),
            "humidity_rh": _safe(humidity),
            "co2_ppm": _safe(co2),
            "voc_index": _safe(voc_index),
            "nox_index": _safe(nox_index),
            "pm1_0_ugm3": _safe(pm1p0),
            "pm2_5_ugm3": _safe(pm2p5),
            "pm4_0_ugm3": _safe(pm4p0),
            "pm10_0_ugm3": _safe(pm10p0),
        }
    except Exception as exc:
        return {"error": str(exc)}


def read_number_concentration(snsr) -> Dict:
    """Read one particle number-concentration snapshot from the sensor."""
    try:
        nc0p5, nc1p0, nc2p5, nc4p0, nc10p0 = snsr.read_number_concentration_values()
        return {
            "nc_pm0_5_pcm3": _safe(nc0p5),
            "nc_pm1_0_pcm3": _safe(nc1p0),
            "nc_pm2_5_pcm3": _safe(nc2p5),
            "nc_pm4_0_pcm3": _safe(nc4p0),
            "nc_pm10_0_pcm3": _safe(nc10p0),
        }
    except Exception as exc:
        return {"error": str(exc)}


@asynccontextmanager
async def sensor_session():
    with LinuxI2cTransceiver("/dev/i2c-1") as transceiver:
        channel = I2cChannel(
            I2cConnection(transceiver),
            slave_address=0x6B,
            crc=CrcCalculator(8, 0x31, 0xFF, 0x0),
        )
        sensor = Sen66Device(channel)
        sensor.device_reset()
        await asyncio.sleep(1.2)
        sensor.start_continuous_measurement()
        await asyncio.sleep(1.1)
        try:
            yield sensor
        finally:
            sensor.stop_measurement()


async def push_environmental_loop(
    sensor,
    *,
    node_id: Optional[str] = None,
    sample_period_s: float = 1.0,
    max_frames: Optional[int] = None,
    client_factory=httpx.AsyncClient,
) -> None:
    node_id = node_id or detect_node_id()
    path = f"ingest/sen66/{node_id}/stream"
    frame = 0
    async with client_factory(timeout=relay_timeout()) as client:
        while max_frames is None or frame < max_frames:
            payload = read_environmental(sensor)
            try:
                await post_payload(client, path, payload)
            except Exception as exc:
                log_post_failure("sen66-env", exc)
            frame += 1
            if max_frames is None or frame < max_frames:
                await asyncio.sleep(sample_period_s)


async def push_number_concentration_loop(
    sensor,
    *,
    node_id: Optional[str] = None,
    sample_period_s: float = 1.0,
    max_frames: Optional[int] = None,
    client_factory=httpx.AsyncClient,
) -> None:
    node_id = node_id or detect_node_id()
    path = f"ingest/sen66/{node_id}/nc-stream"
    frame = 0
    async with client_factory(timeout=relay_timeout()) as client:
        while max_frames is None or frame < max_frames:
            payload = read_number_concentration(sensor)
            try:
                await post_payload(client, path, payload)
            except Exception as exc:
                log_post_failure("sen66-nc", exc)
            frame += 1
            if max_frames is None or frame < max_frames:
                await asyncio.sleep(sample_period_s)


async def main() -> None:
    node_id = detect_node_id()
    async with sensor_session() as sensor:
        await asyncio.gather(
            push_environmental_loop(sensor, node_id=node_id),
            push_number_concentration_loop(sensor, node_id=node_id),
        )


if __name__ == "__main__":
    asyncio.run(main())
