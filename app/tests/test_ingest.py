from pathlib import Path
from types import ModuleType
import importlib.util
import sys


APP_ROOT = Path(__file__).resolve().parents[1]


class _FakeTask:
    def __init__(self, payload):
        self.payload = payload
        self._done = False
        self._cancelled = False
        self._exception = None
        self._callbacks = []
        self.cancel_calls = 0

    def add_done_callback(self, callback) -> None:
        self._callbacks.append(callback)

    def done(self) -> bool:
        return self._done

    def cancelled(self) -> bool:
        return self._cancelled

    def cancel(self) -> None:
        self.cancel_calls += 1
        self._cancelled = True
        self._done = True

    def exception(self):
        return self._exception

    def finish(self, exception=None) -> None:
        self._exception = exception
        self._done = True
        for callback in list(self._callbacks):
            callback(self)


def _load_ingest_module(monkeypatch):
    calls = {"stream_consumer": [], "create_task": []}

    fake_config = ModuleType("app.config")
    fake_config.DEVICES = {
        "10": {"label": "10 (192.168.121.10)", "url": "http://pulse-10"}
    }
    fake_config.SEN66_DEVICES = {
        "11": {
            "label": "11 (192.168.121.11)",
            "stream": "http://sen66-11",
            "nc_stream": "http://sen66-11/nc",
        }
    }
    fake_config.H10_DEVICES = {
        "11:6FFF5628": {
            "label": "6FFF5628",
            "device": "11",
            "h10_id": "6FFF5628",
            "stream": "http://h10-11",
            "ecg_stream": "http://h10-11/ecg",
            "acc_stream": "http://h10-11/acc",
        }
    }
    fake_config.H10_ACC_DYNAMIC_WINDOW_S = 0.5

    fake_shiny = ModuleType("shiny")

    class _Reactive:
        class Value:
            def __init__(self, initial):
                self._value = initial

            def __call__(self):
                return self._value

            def set(self, value) -> None:
                self._value = value

    fake_shiny.reactive = _Reactive()

    fake_consumer = ModuleType("app.streams.consumer")

    def stream_consumer(label, url, on_data):
        payload = {"label": label, "url": url, "on_data": on_data}
        calls["stream_consumer"].append(payload)
        return payload

    fake_consumer.stream_consumer = stream_consumer

    fake_app = ModuleType("app")
    fake_app.__path__ = []
    fake_app_streams = ModuleType("app.streams")
    fake_app_streams.__path__ = []

    monkeypatch.setitem(sys.modules, "app", fake_app)
    monkeypatch.setitem(sys.modules, "app.config", fake_config)
    monkeypatch.setitem(sys.modules, "shiny", fake_shiny)
    monkeypatch.setitem(sys.modules, "app.streams", fake_app_streams)
    monkeypatch.setitem(sys.modules, "app.streams.consumer", fake_consumer)

    module_name = "app.ingest_under_test"
    sys.modules.pop(module_name, None)
    spec = importlib.util.spec_from_file_location(module_name, APP_ROOT / "ingest.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)

    def create_task(payload):
        if hasattr(payload, "close"):
            payload.close()
        task = _FakeTask(payload)
        calls["create_task"].append(task)
        return task

    monkeypatch.setattr(module.asyncio, "create_task", create_task)
    return module, calls


def test_ensure_global_ingest_started_starts_consumers_once(monkeypatch) -> None:
    ingest_module, calls = _load_ingest_module(monkeypatch)
    state = ingest_module.build_ingest_state()

    ingest_module.ensure_global_ingest_started(state)
    ingest_module.ensure_global_ingest_started(state)

    assert state.started is True
    assert len(state.tasks) == 6
    assert len(calls["stream_consumer"]) == 6
    assert [call["label"] for call in calls["stream_consumer"]] == [
        "pulse-10",
        "sen66-11",
        "sen66-nc-11",
        "h10-11:6FFF5628",
        "h10-ecg-11:6FFF5628",
        "h10-acc-11:6FFF5628",
    ]
    assert [call["url"] for call in calls["stream_consumer"]] == [
        "http://pulse-10",
        "http://sen66-11",
        "http://sen66-11/nc",
        "http://h10-11",
        "http://h10-11/ecg",
        "http://h10-11/acc",
    ]
    assert len(calls["create_task"]) == 6


def test_dead_consumer_invalidates_task_set_and_next_ensure_restarts(monkeypatch) -> None:
    ingest_module, calls = _load_ingest_module(monkeypatch)
    state = ingest_module.build_ingest_state()

    ingest_module.ensure_global_ingest_started(state)
    first_generation = list(state.tasks)

    first_generation[0].finish(RuntimeError("boom"))

    assert state.started is False
    assert state.tasks == []
    assert all(task.cancel_calls == 1 for task in first_generation[1:])

    ingest_module.ensure_global_ingest_started(state)

    assert state.started is True
    assert len(state.tasks) == 6
    assert state.tasks != first_generation
    assert len(calls["create_task"]) == 12


def test_normalize_h10_sample_handles_common_ble_field_names(monkeypatch) -> None:
    ingest_module, _ = _load_ingest_module(monkeypatch)

    normalized = ingest_module.normalize_h10_sample(
        {"bpm": 72, "rr": [824, 840], "battery_pct": 95}
    )

    assert normalized["heart_rate_bpm"] == 72.0
    assert normalized["rr_intervals_ms"] == [824.0, 840.0]
    assert normalized["rr_last_ms"] == 840.0
    assert normalized["rr_avg_ms"] == 832.0
    assert normalized["rr_count"] == 2
    assert normalized["battery_pct"] == 95


def test_normalize_h10_ecg_chunk_filters_samples_and_defaults_rate(monkeypatch) -> None:
    ingest_module, _ = _load_ingest_module(monkeypatch)

    normalized = ingest_module.normalize_h10_ecg_chunk(
        {"samples_uv": [10, 11.9, "bad", True, -5], "sample_rate_hz": 0}
    )

    assert normalized == {
        "samples_uv": [10, 11, -5],
        "sample_rate_hz": 130,
    }


def test_normalize_h10_acc_chunk_filters_invalid_samples_and_defaults_rate(
    monkeypatch,
) -> None:
    ingest_module, _ = _load_ingest_module(monkeypatch)

    normalized = ingest_module.normalize_h10_acc_chunk(
        {
            "samples_mg": [
                {"x_mg": -10, "y_mg": 5.5, "z_mg": 2},
                {"x_mg": 1, "y_mg": "bad", "z_mg": 3},
                {"x_mg": True, "y_mg": 1, "z_mg": 3},
            ],
            "sample_rate_hz": 0,
        }
    )

    assert normalized == {
        "samples_mg": [{"x_mg": -10.0, "y_mg": 5.5, "z_mg": 2.0}],
        "sample_rate_hz": 200,
    }


def test_mean_dynamic_acceleration_uses_window_mean_as_static_component(
    monkeypatch,
) -> None:
    ingest_module, _ = _load_ingest_module(monkeypatch)

    mean_dynamic = ingest_module._mean_dynamic_acceleration_mg(
        [
            {"x_mg": 0.0, "y_mg": 0.0, "z_mg": 0.0},
            {"x_mg": 2.0, "y_mg": 0.0, "z_mg": 0.0},
        ]
    )

    assert mean_dynamic == 1.0
