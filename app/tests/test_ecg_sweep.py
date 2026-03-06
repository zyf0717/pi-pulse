from app.renders.ecg_sweep import (
    ECG_SWEEP_FPS,
    ECG_SWEEP_GAP_POINTS,
    ECG_SWEEP_WINDOW_SECONDS,
    ECG_SWEEP_MAX_PENDING_SECONDS,
    ECG_SWEEP_Y_RANGE,
    build_ecg_sweep_message,
)


def test_build_ecg_sweep_message_uses_fixed_window_contract() -> None:
    message = build_ecg_sweep_message(
        "plot-a",
        op="append",
        samples=[1, 2, 3, 4],
        sample_rate_hz=130,
    )

    assert message["plot_id"] == "plot-a"
    assert message["op"] == "append"
    assert message["samples"] == [1, 2, 3, 4]
    assert message["sample_rate_hz"] == 130
    assert message["fps"] == ECG_SWEEP_FPS
    assert message["max_points"] == int(round(130 * ECG_SWEEP_WINDOW_SECONDS))
    assert message["max_pending_points"] == int(round(130 * ECG_SWEEP_MAX_PENDING_SECONDS))
    assert message["gap_points"] == ECG_SWEEP_GAP_POINTS
    assert message["line_color"] is None
    assert message["cursor_color"] is None
    assert message["y_title"] == "Amplitude (µV)"
    assert message["y_range"] == [ECG_SWEEP_Y_RANGE[0], ECG_SWEEP_Y_RANGE[1]]


def test_build_ecg_sweep_message_supports_reset_frames() -> None:
    message = build_ecg_sweep_message(
        "plot-b",
        op="reset",
        samples=list(range(12)),
        sample_rate_hz=130,
        template="plotly",
    )

    assert message["plot_id"] == "plot-b"
    assert message["op"] == "reset"
    assert message["template"] == "plotly"
    assert message["samples"] == list(range(12))
