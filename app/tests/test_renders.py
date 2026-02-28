from collections import deque
import importlib.util
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace


APP_ROOT = Path(__file__).resolve().parents[1]


class _Registry:
    def __init__(self) -> None:
        self.text: dict[str, object] = {}
        self.ui: dict[str, object] = {}
        self.effects: dict[str, object] = {}
        self.widgets: dict[str, object] = {}


class _FakeRender:
    def __init__(self, registry: _Registry) -> None:
        self._registry = registry

    def text(self, fn):
        self._registry.text[fn.__name__] = fn
        return fn

    def ui(self, fn):
        self._registry.ui[fn.__name__] = fn
        return fn


class _FakeReactive:
    class Value:
        def __init__(self, initial):
            self._value = initial

        def __call__(self):
            return self._value

        def set(self, value) -> None:
            self._value = value

    def __init__(self, registry: _Registry) -> None:
        self._registry = registry

    def Effect(self, fn):
        self._registry.effects[fn.__name__] = fn
        return fn


class _FakeValue:
    def __init__(self, value):
        self._value = value

    def __call__(self):
        return self._value


class _FakeInput:
    def __init__(self, *, device: str, pulse_chart: str = "temp", sen66_chart: str = "co2"):
        self._device = device
        self._pulse_chart = pulse_chart
        self._sen66_chart = sen66_chart

    def device(self) -> str:
        return self._device

    def pulse_chart(self) -> str:
        return self._pulse_chart

    def sen66_chart(self) -> str:
        return self._sen66_chart


class _BatchUpdate:
    def __enter__(self):
        return None

    def __exit__(self, exc_type, exc, tb):
        return False


class _FakeFigureWidget:
    def __init__(self, layout=None):
        self.data = []
        self.layout = SimpleNamespace(
            annotations=[],
            template=None,
            margin=None,
            yaxis=SimpleNamespace(title=None),
            yaxis2=SimpleNamespace(title=None),
            legend=None,
            autosize=None if layout is None else layout.get("autosize"),
        )

    def batch_update(self):
        return _BatchUpdate()

    def add_scatter(self, **kwargs) -> None:
        self.data.append(SimpleNamespace(**kwargs))


def _load_render_module(monkeypatch, filename: str, config_attrs: dict):
    registry = _Registry()

    fake_shiny = ModuleType("shiny")
    fake_shiny.reactive = _FakeReactive(registry)
    fake_shiny.render = _FakeRender(registry)
    fake_shiny.ui = SimpleNamespace(HTML=lambda value: value)

    fake_shinywidgets = ModuleType("shinywidgets")

    def render_widget(fn):
        registry.widgets[fn.__name__] = fn
        return fn

    fake_shinywidgets.render_widget = render_widget

    fake_plotly = ModuleType("plotly")
    fake_graph_objects = ModuleType("plotly.graph_objects")
    fake_graph_objects.FigureWidget = _FakeFigureWidget
    fake_plotly.graph_objects = fake_graph_objects

    fake_app = ModuleType("app")
    fake_app.__path__ = []
    fake_app_renders = ModuleType("app.renders")
    fake_app_renders.__path__ = []

    fake_config = ModuleType("app.config")
    for key, value in config_attrs.items():
        setattr(fake_config, key, value)

    fake_sparkline = ModuleType("app.sparkline")

    def sparkline(values, fmt=None):
        rendered = [fmt(value) for value in values] if fmt else list(values)
        return f"SPARK:{rendered}"

    fake_sparkline.sparkline = sparkline

    fake_render_utils = ModuleType("app.renders.render_utils")

    def metric_value(device, devices, latest, field, formatter):
        if device not in devices:
            return "N/A"
        return formatter(latest[device]().get(field, 0.0))

    def sparkline_values(device, devices, latest, history, field, *, scale=1.0):
        if device not in devices:
            return None
        latest[device]()
        return [data.get(field, 0.0) * scale for _, data in history[device]]

    def reset_chart_state(state):
        state.update({"chart": None, "dev": None, "tpl": None})

    def needs_chart_rebuild(state, chart, dev, tpl):
        return state["chart"] != chart or state["dev"] != dev or state["tpl"] != tpl

    fake_render_utils.metric_value = metric_value
    fake_render_utils.sparkline_values = sparkline_values
    fake_render_utils.reset_chart_state = reset_chart_state
    fake_render_utils.needs_chart_rebuild = needs_chart_rebuild

    monkeypatch.setitem(sys.modules, "shiny", fake_shiny)
    monkeypatch.setitem(sys.modules, "shinywidgets", fake_shinywidgets)
    monkeypatch.setitem(sys.modules, "plotly", fake_plotly)
    monkeypatch.setitem(sys.modules, "plotly.graph_objects", fake_graph_objects)
    monkeypatch.setitem(sys.modules, "app", fake_app)
    monkeypatch.setitem(sys.modules, "app.renders", fake_app_renders)
    monkeypatch.setitem(sys.modules, "app.config", fake_config)
    monkeypatch.setitem(sys.modules, "app.sparkline", fake_sparkline)
    monkeypatch.setitem(sys.modules, "app.renders.render_utils", fake_render_utils)

    module_name = f"app.renders.{Path(filename).stem}_under_test"
    sys.modules.pop(module_name, None)
    spec = importlib.util.spec_from_file_location(module_name, APP_ROOT / "renders" / filename)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module, registry


def test_sen66_value_boxes_format_current_snapshot(monkeypatch) -> None:
    module, registry = _load_render_module(
        monkeypatch,
        "sen66.py",
        {
            "SEN66_DEVICES": {
                "11": {
                    "label": "11 (192.168.121.11)",
                    "stream": "http://sen66-11",
                    "nc_stream": "http://sen66-11/nc",
                }
            }
        },
    )
    input_obj = _FakeInput(device="11")
    module.register_sen66_renders(
        input_obj,
        {"11": _FakeValue({"temperature_c": 22.34, "humidity_rh": 45.67, "co2_ppm": 520, "voc_index": 35.2, "nox_index": 1.0})},
        {"11": _FakeValue({"nc_pm0_5_pcm3": 1.0})},
        {"11": deque()},
        {"11": deque()},
        lambda: "plotly_dark",
        _FakeFigureWidget(),
        {"chart": None, "dev": None, "tpl": None},
    )

    assert registry.text["sen66_temp_val"]() == "22.34°C"
    assert registry.text["sen66_hum_val"]() == "45.67%"
    assert registry.text["sen66_co2_val"]() == "520 ppm"
    assert registry.text["sen66_voc_val"]() == "35.2"
    assert registry.text["sen66_nox_val"]() == "1.0"


def test_sen66_invalid_device_returns_na_and_empty_sparklines(monkeypatch) -> None:
    module, registry = _load_render_module(
        monkeypatch,
        "sen66.py",
        {
            "SEN66_DEVICES": {
                "11": {
                    "label": "11 (192.168.121.11)",
                    "stream": "http://sen66-11",
                    "nc_stream": "http://sen66-11/nc",
                }
            }
        },
    )
    input_obj = _FakeInput(device="99")
    module.register_sen66_renders(
        input_obj,
        {"11": _FakeValue({"temperature_c": 22.34})},
        {"11": _FakeValue({"nc_pm0_5_pcm3": 1.0})},
        {"11": deque()},
        {"11": deque()},
        lambda: "plotly_dark",
        _FakeFigureWidget(),
        {"chart": None, "dev": None, "tpl": None},
    )

    assert registry.text["sen66_temp_val"]() == "N/A"
    assert registry.text["sen66_hum_val"]() == "N/A"
    assert registry.text["sen66_co2_val"]() == "N/A"
    assert registry.text["sen66_voc_val"]() == "N/A"
    assert registry.text["sen66_nox_val"]() == "N/A"
    assert registry.ui["sen66_temp_spark"]() == ""
    assert registry.ui["sen66_hum_spark"]() == ""
    assert registry.ui["sen66_co2_spark"]() == ""
    assert registry.ui["sen66_voc_spark"]() == ""
    assert registry.ui["sen66_nox_spark"]() == ""


def test_pulse_invalid_device_clears_chart_and_resets_state(monkeypatch) -> None:
    module, registry = _load_render_module(
        monkeypatch,
        "pulse.py",
        {
            "DEVICES": {"10": {"label": "10 (192.168.121.10)", "url": "http://pulse-10"}},
            "PULSE_CHARTS": {
                "cpu": "CPU Usage (%)",
                "cpu_freq": "CPU Frequency (MHz)",
                "mem": "Memory Usage (%)",
                "temp": "Temperature (°C)",
                "net": "Download & Upload (KB/s)",
            },
        },
    )
    widget = _FakeFigureWidget()
    widget.data = ["stale"]
    state = {"chart": "temp", "dev": "10", "tpl": "plotly_dark"}

    module.register_pulse_renders(
        _FakeInput(device="99", pulse_chart="temp"),
        {"10": _FakeValue({"temp": 22.0})},
        {"10": deque()},
        lambda: "plotly_dark",
        widget,
        state,
    )

    registry.effects["_update_pulse_chart"]()

    assert widget.data == []
    assert state == {"chart": None, "dev": None, "tpl": None}


def test_sen66_invalid_device_clears_chart_sets_annotation_and_resets_state(monkeypatch) -> None:
    module, registry = _load_render_module(
        monkeypatch,
        "sen66.py",
        {
            "SEN66_DEVICES": {
                "11": {
                    "label": "11 (192.168.121.11)",
                    "stream": "http://sen66-11",
                    "nc_stream": "http://sen66-11/nc",
                }
            }
        },
    )
    widget = _FakeFigureWidget()
    widget.data = ["stale"]
    widget.layout.annotations = ["old"]
    state = {"chart": "co2", "dev": "11", "tpl": "plotly_dark"}

    module.register_sen66_renders(
        _FakeInput(device="99", sen66_chart="co2"),
        {"11": _FakeValue({"co2_ppm": 520})},
        {"11": _FakeValue({"nc_pm0_5_pcm3": 1.0})},
        {"11": deque()},
        {"11": deque()},
        lambda: "plotly_dark",
        widget,
        state,
    )

    registry.effects["_update_sen66_chart"]()

    assert widget.data == []
    assert widget.layout.annotations == [module._NO_DATA_ANNOTATION]
    assert state == {"chart": None, "dev": None, "tpl": None}


def test_pulse_empty_history_leaves_existing_chart_unchanged(monkeypatch) -> None:
    module, registry = _load_render_module(
        monkeypatch,
        "pulse.py",
        {
            "DEVICES": {"10": {"label": "10 (192.168.121.10)", "url": "http://pulse-10"}},
            "PULSE_CHARTS": {
                "cpu": "CPU Usage (%)",
                "cpu_freq": "CPU Frequency (MHz)",
                "mem": "Memory Usage (%)",
                "temp": "Temperature (°C)",
                "net": "Download & Upload (KB/s)",
            },
        },
    )
    widget = _FakeFigureWidget()
    widget.data = ["stale"]
    state = {"chart": "temp", "dev": "10", "tpl": "plotly_dark"}

    module.register_pulse_renders(
        _FakeInput(device="10", pulse_chart="temp"),
        {"10": _FakeValue({"temp": 22.0})},
        {"10": deque()},
        lambda: "plotly_dark",
        widget,
        state,
    )

    registry.effects["_update_pulse_chart"]()

    assert widget.data == ["stale"]
    assert state == {"chart": "temp", "dev": "10", "tpl": "plotly_dark"}


def test_sen66_empty_history_leaves_existing_chart_unchanged(monkeypatch) -> None:
    module, registry = _load_render_module(
        monkeypatch,
        "sen66.py",
        {
            "SEN66_DEVICES": {
                "11": {
                    "label": "11 (192.168.121.11)",
                    "stream": "http://sen66-11",
                    "nc_stream": "http://sen66-11/nc",
                }
            }
        },
    )
    widget = _FakeFigureWidget()
    widget.data = ["stale"]
    widget.layout.annotations = ["keep"]
    state = {"chart": "co2", "dev": "11", "tpl": "plotly_dark"}

    module.register_sen66_renders(
        _FakeInput(device="11", sen66_chart="co2"),
        {"11": _FakeValue({"co2_ppm": 520})},
        {"11": _FakeValue({"nc_pm0_5_pcm3": 1.0})},
        {"11": deque()},
        {"11": deque()},
        lambda: "plotly_dark",
        widget,
        state,
    )

    registry.effects["_update_sen66_chart"]()

    assert widget.data == ["stale"]
    assert widget.layout.annotations == ["keep"]
    assert state == {"chart": "co2", "dev": "11", "tpl": "plotly_dark"}
