import asyncio
import json
from contextlib import asynccontextmanager
from typing import Dict, Optional

from fastapi import FastAPI
from fastapi.responses import StreamingResponse
from sensirion_driver_adapters.i2c_adapter.i2c_channel import I2cChannel

# Official Sensirion hardware imports (modern channel-based API)
from sensirion_i2c_driver import CrcCalculator, I2cConnection, LinuxI2cTransceiver
from sensirion_i2c_sen66.device import Sen66Device

# Global sensor instance shared across all requests
sensor = None


def _safe(signal):
    """Return the scaled float value of a Sensirion Signal object, or None on error."""
    try:
        v = signal.value
        # Driver returns None or a sentinel (0x7FFF / 0xFFFF scaled) when unavailable
        return round(v, 3) if v is not None else None
    except Exception:
        return None


def read_environmental(snsr) -> Dict:
    """Read one environmental snapshot from the sensor.

    Pure synchronous function — directly unit-testable without async machinery
    or a live I2C device.  Returns a ready-to-serialise payload dict; on error
    returns ``{"error": "<message>"}``.

    Args:
        snsr: A Sen66Device instance (or compatible mock).
    """
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
            "voc_index": _safe(voc_index),  # 0–500 dimensionless
            "nox_index": _safe(nox_index),  # 0–500 dimensionless
            "pm1_0_ugm3": _safe(pm1p0),
            "pm2_5_ugm3": _safe(pm2p5),
            "pm4_0_ugm3": _safe(pm4p0),
            "pm10_0_ugm3": _safe(pm10p0),
        }
    except Exception as e:
        return {"error": str(e)}


def read_number_concentration(snsr) -> Dict:
    """Read one particle number-concentration snapshot from the sensor.

    Pure synchronous function — directly unit-testable without async machinery
    or a live I2C device.  Returns a ready-to-serialise payload dict; on error
    returns ``{"error": "<message>"}``.

    Args:
        snsr: A Sen66Device instance (or compatible mock).
    """
    try:
        (
            nc0p5,
            nc1p0,
            nc2p5,
            nc4p0,
            nc10p0,
        ) = snsr.read_number_concentration_values()

        return {
            "nc_pm0_5_pcm3": _safe(nc0p5),
            "nc_pm1_0_pcm3": _safe(nc1p0),
            "nc_pm2_5_pcm3": _safe(nc2p5),
            "nc_pm4_0_pcm3": _safe(nc4p0),
            "nc_pm10_0_pcm3": _safe(nc10p0),
        }
    except Exception as e:
        return {"error": str(e)}


@asynccontextmanager
async def lifespan(app: FastAPI):
    global sensor
    # Open the I2C bus and keep it open for the entire server lifespan
    with LinuxI2cTransceiver("/dev/i2c-1") as transceiver:
        channel = I2cChannel(
            I2cConnection(transceiver),
            slave_address=0x6B,
            crc=CrcCalculator(8, 0x31, 0xFF, 0x0),
        )
        sensor = Sen66Device(channel)
        sensor.device_reset()
        await asyncio.sleep(1.2)  # mandatory post-reset settle time
        sensor.start_continuous_measurement()
        await asyncio.sleep(1.1)  # first reading not ready until ~1.1 s

        yield  # server handles requests here

        sensor.stop_measurement()
        sensor = None


app = FastAPI(title="Pi-Pulse — SEN66 Air Quality", lifespan=lifespan)


@app.get("/health")
async def health():
    return {"status": "pulsing", "sensor": "SEN66"}


async def environmental_stream(
    sample_period_s: float = 1.0, max_frames: Optional[int] = None
):
    """SSE: mass concentrations, gas indices, CO2, temperature, humidity.

    Args:
        sample_period_s: Seconds between frames (default 1.0).
        max_frames: Terminate after this many frames. ``None`` (default) runs
                    forever (production). Pass ``1`` in tests to get a single
                    frame and have the generator exit naturally.
    """
    frame = 0
    while max_frames is None or frame < max_frames:
        payload = read_environmental(sensor)
        yield f"data: {json.dumps(payload)}\n\n"
        frame += 1
        if max_frames is None or frame < max_frames:
            await asyncio.sleep(sample_period_s)


async def number_concentration_stream(
    sample_period_s: float = 1.0, max_frames: Optional[int] = None
):
    """SSE: particle number concentrations (particles/cm³).

    Adds PM0.5 which is not available in the mass-concentration read.

    Args:
        sample_period_s: Seconds between frames (default 1.0).
        max_frames: Terminate after this many frames. ``None`` (default) runs
                    forever (production). Pass ``1`` in tests to get a single
                    frame and have the generator exit naturally.
    """
    frame = 0
    while max_frames is None or frame < max_frames:
        payload = read_number_concentration(sensor)
        yield f"data: {json.dumps(payload)}\n\n"
        frame += 1
        if max_frames is None or frame < max_frames:
            await asyncio.sleep(sample_period_s)


@app.get("/stream")
async def stream_environmental():
    """SSE stream: temp, RH, CO2, VOC, NOx, PM mass concentrations."""
    return StreamingResponse(environmental_stream(), media_type="text/event-stream")


@app.get("/nc-stream")
async def stream_number_concentration():
    """SSE stream: PM number concentrations per cm³ incl. PM0.5."""
    return StreamingResponse(
        number_concentration_stream(), media_type="text/event-stream"
    )
