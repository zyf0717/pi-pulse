from pathlib import Path
from types import ModuleType, SimpleNamespace
import importlib.util
import sys


APP_ROOT = Path(__file__).resolve().parents[1]


class _FakeTask:
    def __init__(self, payload):
        self.payload = payload
        self.cancel_calls = 0

    def cancel(self) -> None:
        self.cancel_calls += 1


class _FakeFigureWidget:
    def __init__(self, layout=None):
        self.layout = layout


def _load_server_module(monkeypatch):
    calls = {
        "theme_picker_server": 0,
        "pulse_register": [],
        "sen66_register": [],
        "stream_consumer": [],
        "create_task": [],
    }

    fake_config = ModuleType("config")
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

    fake_shinyswatch = ModuleType("shinyswatch")

    def theme_picker_server() -> None:
        calls["theme_picker_server"] += 1

    fake_shinyswatch.theme_picker_server = theme_picker_server

    fake_shiny = ModuleType("shiny")

    class _Reactive:
        class Value:
            def __init__(self, initial):
                self._value = initial

            def __call__(self):
                return self._value

            def set(self, value) -> None:
                self._value = value

        @staticmethod
        def calc(fn):
            return fn

    fake_shiny.reactive = _Reactive()

    fake_plotly = ModuleType("plotly")
    fake_graph_objects = ModuleType("plotly.graph_objects")
    fake_graph_objects.FigureWidget = _FakeFigureWidget
    fake_plotly.graph_objects = fake_graph_objects

    fake_app = ModuleType("app")
    fake_app.__path__ = []
    fake_app_renders = ModuleType("app.renders")
    fake_app_renders.__path__ = []
    fake_app_streams = ModuleType("app.streams")
    fake_app_streams.__path__ = []

    fake_renders = ModuleType("renders")
    fake_renders.__path__ = []

    fake_pulse = ModuleType("app.renders.pulse")

    def register_pulse_renders(*args) -> None:
        calls["pulse_register"].append(args)

    fake_pulse.register_pulse_renders = register_pulse_renders

    fake_sen66 = ModuleType("app.renders.sen66")

    def register_sen66_renders(*args) -> None:
        calls["sen66_register"].append(args)

    fake_sen66.register_sen66_renders = register_sen66_renders

    fake_consumer = ModuleType("app.streams.consumer")

    def stream_consumer(label, url, on_data):
        payload = {"label": label, "url": url, "on_data": on_data}
        calls["stream_consumer"].append(payload)
        return payload

    fake_consumer.stream_consumer = stream_consumer

    monkeypatch.setitem(sys.modules, "app", fake_app)
    monkeypatch.setitem(sys.modules, "app.config", fake_config)
    monkeypatch.setitem(sys.modules, "shinyswatch", fake_shinyswatch)
    monkeypatch.setitem(sys.modules, "shiny", fake_shiny)
    monkeypatch.setitem(sys.modules, "plotly", fake_plotly)
    monkeypatch.setitem(sys.modules, "plotly.graph_objects", fake_graph_objects)
    monkeypatch.setitem(sys.modules, "app.renders", fake_app_renders)
    monkeypatch.setitem(sys.modules, "app.renders.pulse", fake_pulse)
    monkeypatch.setitem(sys.modules, "app.renders.sen66", fake_sen66)
    monkeypatch.setitem(sys.modules, "app.streams", fake_app_streams)
    monkeypatch.setitem(sys.modules, "app.streams.consumer", fake_consumer)

    module_name = "app.server_under_test"
    sys.modules.pop(module_name, None)
    spec = importlib.util.spec_from_file_location(module_name, APP_ROOT / "server.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)

    def create_task(payload):
        task = _FakeTask(payload)
        calls["create_task"].append(task)
        return task

    monkeypatch.setattr(module.asyncio, "create_task", create_task)

    return module, calls


class _FakeInput:
    def chart_style(self) -> str:
        return "plotly_dark"


class _FakeSession:
    def __init__(self) -> None:
        self.ended_callback = None

    def on_ended(self, callback) -> None:
        self.ended_callback = callback


def test_server_wires_stream_tasks_and_registers_renders(monkeypatch) -> None:
    server_module, calls = _load_server_module(monkeypatch)
    session = _FakeSession()

    server_module.server(_FakeInput(), output=None, session=session)

    assert calls["theme_picker_server"] == 1
    assert len(calls["stream_consumer"]) == 3
    assert [call["label"] for call in calls["stream_consumer"]] == [
        "pulse-10",
        "sen66-11",
        "sen66-nc-11",
    ]
    assert [call["url"] for call in calls["stream_consumer"]] == [
        "http://pulse-10",
        "http://sen66-11",
        "http://sen66-11/nc",
    ]
    assert len(calls["create_task"]) == 3
    assert len(calls["pulse_register"]) == 1
    assert len(calls["sen66_register"]) == 1


def test_server_registers_session_cleanup_that_cancels_all_tasks(monkeypatch) -> None:
    server_module, calls = _load_server_module(monkeypatch)
    session = _FakeSession()

    server_module.server(_FakeInput(), output=None, session=session)

    assert session.ended_callback is not None

    session.ended_callback()

    assert [task.cancel_calls for task in calls["create_task"]] == [1, 1, 1]


def test_server_initializes_chart_state_for_render_registration(monkeypatch) -> None:
    server_module, calls = _load_server_module(monkeypatch)
    session = _FakeSession()

    server_module.server(_FakeInput(), output=None, session=session)

    pulse_args = calls["pulse_register"][0]
    sen66_args = calls["sen66_register"][0]

    assert isinstance(pulse_args[4], _FakeFigureWidget)
    assert pulse_args[5] == {"chart": None, "dev": None, "tpl": None}
    assert isinstance(sen66_args[6], _FakeFigureWidget)
    assert sen66_args[7] == {"chart": None, "dev": None, "tpl": None}
    assert pulse_args[0].chart_style() == "plotly_dark"
    assert sen66_args[0].chart_style() == "plotly_dark"
