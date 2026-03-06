from collections import deque

from app.renders.h10_ecg_bridge import ECG_SWEEP_PLOT_ID, update_ecg_sweep


class _FakeSession:
    def __init__(self) -> None:
        self.messages: list[tuple[str, dict]] = []

    def send_custom_message(self, name: str, payload: dict) -> None:
        self.messages.append((name, payload))


def test_update_ecg_sweep_resets_on_first_ecg_frame() -> None:
    session = _FakeSession()
    state = {"chart": None, "stream": None, "tpl": None, "sent_total": 0}

    update_ecg_sweep(
        session,
        state,
        chart="ecg",
        stream_key="11:strap-a",
        template="plotly_dark",
        ecg_meta={"sample_rate_hz": 130, "total_samples": 6},
        ecg_samples=deque([10, 20, 30, 40, 50, 60]),
        ecg_chunks=deque(),
        title="ECG (µV)",
    )

    assert len(session.messages) == 1
    name, payload = session.messages[0]
    assert name == "ecg-sweep"
    assert payload["plot_id"] == ECG_SWEEP_PLOT_ID
    assert payload["op"] == "reset"
    assert payload["samples"] == [10, 20, 30, 40, 50, 60]
    assert payload["sample_rate_hz"] == 130
    assert payload["fps"] == 30.0
    assert payload["max_points"] == 1300
    assert payload["max_pending_points"] == 130
    assert payload["gap_points"] == 13.0
    assert payload["title"] == "ECG (µV)"
    assert payload["template"] == "plotly_dark"
    assert isinstance(payload["template_config"], dict)
    assert payload["y_title"] == "Amplitude (µV)"
    assert payload["line_color"] is None
    assert payload["cursor_color"] is None
    assert payload["line_width"] == 2
    assert payload["y_range"] == [-2000.0, 2500.0]
    assert state == {
        "chart": "ecg",
        "stream": "11:strap-a",
        "tpl": "plotly_dark",
        "sent_total": 6,
    }


def test_update_ecg_sweep_appends_only_new_chunks() -> None:
    session = _FakeSession()
    state = {
        "chart": "ecg",
        "stream": "11:strap-a",
        "tpl": "plotly_dark",
        "sent_total": 6,
    }

    update_ecg_sweep(
        session,
        state,
        chart="ecg",
        stream_key="11:strap-a",
        template="plotly_dark",
        ecg_meta={"sample_rate_hz": 130, "total_samples": 8},
        ecg_samples=deque([10, 20, 30, 40, 50, 60, 70, 80]),
        ecg_chunks=deque(
            [
                {"samples_uv": [10, 20], "sample_rate_hz": 130, "total_samples": 2},
                {"samples_uv": [70, 80], "sample_rate_hz": 130, "total_samples": 8},
            ]
        ),
        title="ECG (µV)",
    )

    assert len(session.messages) == 1
    name, payload = session.messages[0]
    assert name == "ecg-sweep"
    assert payload["plot_id"] == ECG_SWEEP_PLOT_ID
    assert payload["op"] == "append"
    assert payload["samples"] == [70, 80]
    assert payload["sample_rate_hz"] == 130
    assert state["sent_total"] == 8


def test_update_ecg_sweep_clears_when_leaving_ecg_chart() -> None:
    session = _FakeSession()
    state = {
        "chart": "ecg",
        "stream": "11:strap-a",
        "tpl": "plotly_dark",
        "sent_total": 6,
    }

    update_ecg_sweep(
        session,
        state,
        chart="bpm",
        stream_key="11:strap-a",
        template="plotly_dark",
        ecg_meta=None,
        ecg_samples=deque(),
        ecg_chunks=deque(),
        title="ECG (µV)",
    )

    assert session.messages == [
        ("ecg-sweep", {"plot_id": ECG_SWEEP_PLOT_ID, "op": "clear"})
    ]
    assert state == {
        "chart": "bpm",
        "stream": "11:strap-a",
        "tpl": "plotly_dark",
        "sent_total": 0,
    }
