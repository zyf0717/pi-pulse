from app.renders.ecg_sweep import (
    ECG_SWEEP_FPS,
    ECG_SWEEP_GAP_POINTS,
    ECG_SWEEP_Y_RANGE,
    SweepFramePlayer,
    build_ecg_sweep_message,
)


def test_sweep_frame_player_distributes_130hz_over_30fps() -> None:
    player = SweepFramePlayer(sample_rate_hz=130.0, fps=ECG_SWEEP_FPS)
    initial_source = list(range(20))
    full_source = list(range(40))

    first = player.next_frame(initial_source, len(initial_source))
    second = player.next_frame(full_source, len(full_source))
    third = player.next_frame(full_source, len(full_source))
    fourth = player.next_frame(full_source, len(full_source))
    fifth = player.next_frame(full_source, len(full_source))

    assert first == {"op": "reset", "samples": initial_source}
    assert second == {"op": "append", "samples": [20, 21, 22, 23]}
    assert third == {"op": "append", "samples": [24, 25, 26, 27]}
    assert fourth == {"op": "append", "samples": [28, 29, 30, 31]}
    assert fifth == {"op": "append", "samples": [32, 33, 34, 35, 36]}


def test_sweep_frame_player_resets_on_backlog_growth() -> None:
    player = SweepFramePlayer(sample_rate_hz=130.0, fps=30.0, window_seconds=1.0)
    first_source = list(range(10))
    second_source = list(range(260))

    first = player.next_frame(first_source, len(first_source))
    second = player.next_frame(second_source, len(second_source))

    assert first == {"op": "reset", "samples": first_source}
    assert second == {"op": "reset", "samples": second_source[-130:]}


def test_build_ecg_sweep_message_uses_fixed_window_contract() -> None:
    message = build_ecg_sweep_message(
        "plot-a",
        {"op": "append", "samples": [1, 2, 3, 4]},
        sample_rate_hz=130,
    )

    assert message["plot_id"] == "plot-a"
    assert message["op"] == "append"
    assert message["samples"] == [1, 2, 3, 4]
    assert message["sample_rate_hz"] == 130
    assert message["max_points"] == 780
    assert message["gap_points"] == ECG_SWEEP_GAP_POINTS
    assert message["y_range"] == [ECG_SWEEP_Y_RANGE[0], ECG_SWEEP_Y_RANGE[1]]
