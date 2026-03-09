"""
Polar H10 BLE worker.

Each configured H10 connects locally over BLE and pushes its payloads to the
relay on the dashboard host instead of serving local SSE endpoints.
"""

import asyncio
from collections.abc import Callable

import httpx
from bleak import BleakClient

try:
    from h10_protocol import (
        ACC_RANGE_G,
        ACC_SAMPLE_RATE_HZ,
        ACC_START_CMD,
        ECG_SAMPLE_RATE_HZ,
        ECG_START_CMD,
        H10_ADDRESS,
        HR_MEASUREMENT_UUID,
        PMD_CP_UUID,
        PMD_DATA_UUID,
        PMD_MEAS_TYPE_ACC,
        PMD_MEAS_TYPE_ECG,
        ble_connect_loop,
        parse_acc_frame,
        parse_ecg_frame,
        parse_hr_measurement,
    )
    from relay_push import log_post_failure, post_payload, relay_timeout
except ImportError:
    from rpi4.h10_protocol import (
        ACC_RANGE_G,
        ACC_SAMPLE_RATE_HZ,
        ACC_START_CMD,
        ECG_SAMPLE_RATE_HZ,
        ECG_START_CMD,
        H10_ADDRESS,
        HR_MEASUREMENT_UUID,
        PMD_CP_UUID,
        PMD_DATA_UUID,
        PMD_MEAS_TYPE_ACC,
        PMD_MEAS_TYPE_ECG,
        ble_connect_loop,
        parse_acc_frame,
        parse_ecg_frame,
        parse_hr_measurement,
    )
    from rpi4.relay_push import log_post_failure, post_payload, relay_timeout


def _schedule_push(pending: set[asyncio.Task], coro) -> None:
    task = asyncio.create_task(coro)
    pending.add(task)
    task.add_done_callback(pending.discard)


def build_notification_handlers(
    device_id: str,
    publish: Callable[[str, dict], None],
):
    def handle_hr_notification(_: int, data: bytearray) -> None:
        publish("stream", parse_hr_measurement(bytes(data)))

    def handle_pmd_notification(_: int, data: bytearray) -> None:
        packet = bytes(data)
        if not packet:
            return

        meas_type = packet[0]
        if meas_type == PMD_MEAS_TYPE_ECG:
            try:
                samples = parse_ecg_frame(packet)
            except ValueError:
                return
            publish(
                "ecg-stream",
                {"samples_uv": samples, "sample_rate_hz": ECG_SAMPLE_RATE_HZ},
            )
            return

        if meas_type == PMD_MEAS_TYPE_ACC:
            try:
                samples = parse_acc_frame(packet)
            except ValueError:
                return
            publish(
                "acc-stream",
                {
                    "samples_mg": samples,
                    "sample_rate_hz": ACC_SAMPLE_RATE_HZ,
                    "range_g": ACC_RANGE_G,
                },
            )

    return handle_hr_notification, handle_pmd_notification


async def ble_loop(device_id: str, address: str, stop_event: asyncio.Event) -> None:
    """Connect to one H10 and push HR/ECG/ACC payloads to the relay."""
    pending_pushes: set[asyncio.Task] = set()

    async with httpx.AsyncClient(timeout=relay_timeout()) as client:
        def publish(stream_name: str, payload: dict) -> None:
            path = f"ingest/h10/{device_id}/{stream_name}"

            async def _push() -> None:
                try:
                    await post_payload(client, path, payload)
                except Exception as exc:
                    log_post_failure(f"h10-{device_id}-{stream_name}", exc)

            _schedule_push(pending_pushes, _push())

        handle_hr_notification, handle_pmd_notification = build_notification_handlers(
            device_id, publish
        )

        async def on_connect(client: BleakClient) -> None:
            await client.start_notify(HR_MEASUREMENT_UUID, handle_hr_notification)

            await client.start_notify(PMD_CP_UUID, lambda _h, _d: None)
            await client.start_notify(PMD_DATA_UUID, handle_pmd_notification)

            await client.write_gatt_char(PMD_CP_UUID, ECG_START_CMD, response=True)
            await asyncio.sleep(0.5)
            try:
                await client.write_gatt_char(PMD_CP_UUID, ACC_START_CMD, response=True)
            except Exception as exc:
                print(f"[h10] ACC stream unavailable for {device_id}: {exc}")

        try:
            await ble_connect_loop(address, stop_event, on_connect)
        finally:
            if pending_pushes:
                await asyncio.gather(*pending_pushes, return_exceptions=True)


async def main() -> None:
    stop_event = asyncio.Event()
    tasks = [
        asyncio.create_task(ble_loop(device_id, address, stop_event))
        for device_id, address in H10_ADDRESS.items()
    ]
    try:
        await asyncio.gather(*tasks)
    except asyncio.CancelledError:
        stop_event.set()
        for task in tasks:
            task.cancel()
        raise
    finally:
        stop_event.set()
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)


if __name__ == "__main__":
    asyncio.run(main())
