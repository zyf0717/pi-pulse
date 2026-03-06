"""Session-to-browser bridge for the client-driven H10 ECG sweep."""

import asyncio
import inspect

from app.renders.ecg_sweep import ECG_SWEEP_MESSAGE, build_ecg_sweep_message

ECG_SWEEP_PLOT_ID = "h10_ecg_sweep"


def send_custom_message(session, name: str, payload: dict) -> None:
    if session is None:
        return
    sender = getattr(session, "send_custom_message", None)
    if sender is None:
        return
    result = sender(name, payload)
    if inspect.isawaitable(result):
        asyncio.create_task(result)


def update_ecg_sweep(
    session,
    state: dict[str, str | int | None],
    *,
    chart: str,
    stream_key: str | None,
    template: str,
    ecg_meta: dict | None,
    ecg_samples,
    ecg_chunks,
    title: str,
) -> None:
    if session is None:
        return

    if chart != "ecg" or stream_key is None:
        if state["chart"] == "ecg":
            send_custom_message(
                session,
                ECG_SWEEP_MESSAGE,
                {"plot_id": ECG_SWEEP_PLOT_ID, "op": "clear"},
            )
        state.update(
            {"chart": chart, "stream": stream_key, "tpl": template, "sent_total": 0}
        )
        return

    ecg_meta = ecg_meta or {}
    sample_rate_hz = int(ecg_meta.get("sample_rate_hz", 130) or 130)
    total_samples = int(ecg_meta.get("total_samples", len(ecg_samples)) or 0)
    force_reset = (
        state["chart"] != "ecg"
        or state["stream"] != stream_key
        or state["tpl"] != template
    )

    if total_samples <= 0 or not ecg_samples:
        if force_reset:
            send_custom_message(
                session,
                ECG_SWEEP_MESSAGE,
                {"plot_id": ECG_SWEEP_PLOT_ID, "op": "clear"},
            )
        state.update(
            {"chart": chart, "stream": stream_key, "tpl": template, "sent_total": 0}
        )
        return

    if force_reset:
        send_custom_message(
            session,
            ECG_SWEEP_MESSAGE,
            build_ecg_sweep_message(
                ECG_SWEEP_PLOT_ID,
                op="reset",
                samples=list(ecg_samples),
                sample_rate_hz=sample_rate_hz,
                title=title,
                template=template,
            ),
        )
        state.update(
            {
                "chart": chart,
                "stream": stream_key,
                "tpl": template,
                "sent_total": total_samples,
            }
        )
        return

    sent_total = int(state.get("sent_total", 0) or 0)
    pending_chunks = [
        chunk
        for chunk in ecg_chunks
        if int(chunk.get("total_samples", 0) or 0) > sent_total
    ]
    if not pending_chunks:
        state.update(
            {
                "chart": chart,
                "stream": stream_key,
                "tpl": template,
                "sent_total": sent_total,
            }
        )
        return

    for chunk in pending_chunks:
        chunk_samples = list(chunk.get("samples_uv", []))
        if not chunk_samples:
            continue
        send_custom_message(
            session,
            ECG_SWEEP_MESSAGE,
            build_ecg_sweep_message(
                ECG_SWEEP_PLOT_ID,
                op="append",
                samples=chunk_samples,
                sample_rate_hz=int(chunk.get("sample_rate_hz", sample_rate_hz) or sample_rate_hz),
                title=title,
                template=template,
            ),
        )
        sent_total = int(chunk.get("total_samples", sent_total) or sent_total)

    state.update(
        {
            "chart": chart,
            "stream": stream_key,
            "tpl": template,
            "sent_total": sent_total,
        }
    )
