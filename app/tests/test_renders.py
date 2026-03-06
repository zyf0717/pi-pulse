import importlib.util
import sys
from collections import deque
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
    def __init__(
        self,
        *,
        device: str,
        h10_device: str | None = None,
        pulse_chart: str = "temp",
        sen66_chart: str = "co2",
        h10_chart: str = "bpm",
    ):
        self._device = device
        self._h10_device = h10_device
        self._pulse_chart = pulse_chart
        self._sen66_chart = sen66_chart
        self._h10_chart = h10_chart

    def device(self) -> str:
        return self._device

    def h10_device(self) -> str | None:
        return self._h10_device

    def pulse_chart(self) -> str:
        return self._pulse_chart

    def sen66_chart(self) -> str:
        return self._sen66_chart

    def h10_chart(self) -> str:
        return self._h10_chart


class _FakeSession:
    def __init__(self) -> None:
        self.messages: list[tuple[str, dict]] = []

    def send_custom_message(self, name: str, payload: dict) -> None:
        self.messages.append((name, payload))


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
            xaxis=SimpleNamespace(title=None),
            legend=None,
            autosize=None if layout is None else layout.get("autosize"),
        )

    def batch_update(self):
        return _BatchUpdate()

    def add_scatter(self, **kwargs) -> None:
        self.data.append(SimpleNamespace(**kwargs))


def _load_render_module(monkeypatch, filename: str, config_attrs: dict):
    registry = _Registry()

    if "H10_DEVICES" in config_attrs:
        h10_devices = config_attrs["H10_DEVICES"]
        if "H10_DEVICE_OPTIONS" not in config_attrs:
            options: dict[str, dict[str, str]] = {}
            defaults: dict[str, str] = {}
            for stream_key, entry in h10_devices.items():
                node_key = entry.get("device")
                if not node_key:
                    node_key = (
                        stream_key.split(":", 1)[0]
                        if ":" in stream_key
                        else str(stream_key)
                    )
                label = entry.get("label", str(stream_key))
                options.setdefault(node_key, {})[stream_key] = label
                defaults.setdefault(node_key, stream_key)
            config_attrs = dict(config_attrs)
            config_attrs["H10_DEVICE_OPTIONS"] = options
            config_attrs["H10_DEFAULTS"] = defaults
        elif "H10_DEFAULTS" not in config_attrs:
            defaults = {
                node_key: next(iter(options), None)
                for node_key, options in config_attrs["H10_DEVICE_OPTIONS"].items()
            }
            config_attrs = dict(config_attrs)
            config_attrs["H10_DEFAULTS"] = defaults

    fake_shiny = ModuleType("shiny")
    fake_shiny.reactive = _FakeReactive(registry)
    fake_shiny.render = _FakeRender(registry)
    fake_shiny.ui = SimpleNamespace(
        HTML=lambda value: value,
        div=lambda *args, **kwargs: {
            "tag": "div",
            "args": args,
            "kwargs": kwargs,
        },
        input_select=lambda *args, **kwargs: {
            "tag": "input_select",
            "args": args,
            "kwargs": kwargs,
        },
    )

    fake_shinywidgets = ModuleType("shinywidgets")

    def render_widget(fn):
        registry.widgets[fn.__name__] = fn
        return fn

    fake_shinywidgets.render_widget = render_widget
    fake_shinywidgets.output_widget = lambda output_id: {
        "tag": "output_widget",
        "id": output_id,
    }

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
    fake_ecg_sweep = ModuleType("app.renders.ecg_sweep")
    fake_h10_motion = ModuleType("app.renders.h10_motion")
    fake_h10_ecg_bridge = ModuleType("app.renders.h10_ecg_bridge")

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

    def build_ecg_sweep_message(plot_id: str, *, op: str, samples, **kwargs):
        payload = {"plot_id": plot_id, "op": op, "samples": list(samples)}
        payload.update(kwargs)
        return payload

    def motion_plane_svg(trail_points, *, axes, axis_names, detail):
        labels = f">{axis_names[0]}<>{axis_names[1]}<"
        polyline = "polyline" if len(trail_points) >= 2 else ""
        detail_labels = (
            "+1500-1500Z: +990 mg"
            if detail and trail_points
            else ""
        )
        preview_labels = "" if detail else labels
        return f"<svg>{polyline}{preview_labels}{detail_labels}</svg>"

    def motion_detail_row_svg(trail_points):
        return "".join(
            motion_plane_svg(
                trail_points,
                axes=axes,
                axis_names=axis_names,
                detail=True,
            )
            for axes, axis_names in (
                ((0, 1), ("X", "Y")),
                ((0, 2), ("X", "Z")),
                ((1, 2), ("Y", "Z")),
            )
        )

    def update_ecg_sweep(
        session,
        state,
        *,
        chart,
        stream_key,
        template,
        ecg_meta,
        ecg_samples,
        ecg_chunks,
        title,
    ):
        if session is None:
            return
        if chart != "ecg" or stream_key is None:
            if state["chart"] == "ecg":
                session.send_custom_message(
                    "ecg-sweep",
                    {"plot_id": "h10_ecg_sweep", "op": "clear"},
                )
            state.update(
                {"chart": chart, "stream": stream_key, "tpl": template, "sent_total": 0}
            )
            return

        total_samples = int(ecg_meta.get("total_samples", len(ecg_samples)) or 0)
        force_reset = (
            state["chart"] != "ecg"
            or state["stream"] != stream_key
            or state["tpl"] != template
        )

        if force_reset:
            session.send_custom_message(
                "ecg-sweep",
                build_ecg_sweep_message(
                    "h10_ecg_sweep",
                    op="reset",
                    samples=list(ecg_samples),
                    sample_rate_hz=int(ecg_meta.get("sample_rate_hz", 130) or 130),
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
        for chunk in ecg_chunks:
            if int(chunk.get("total_samples", 0) or 0) <= sent_total:
                continue
            session.send_custom_message(
                "ecg-sweep",
                build_ecg_sweep_message(
                    "h10_ecg_sweep",
                    op="append",
                    samples=list(chunk.get("samples_uv", [])),
                    sample_rate_hz=int(chunk.get("sample_rate_hz", 130) or 130),
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

    fake_ecg_sweep.ECG_SWEEP_MESSAGE = "ecg-sweep"
    fake_ecg_sweep.build_ecg_sweep_message = build_ecg_sweep_message
    fake_h10_motion.motion_plane_svg = motion_plane_svg
    fake_h10_motion.motion_detail_row_svg = motion_detail_row_svg
    fake_h10_ecg_bridge.ECG_SWEEP_PLOT_ID = "h10_ecg_sweep"
    fake_h10_ecg_bridge.update_ecg_sweep = update_ecg_sweep

    monkeypatch.setitem(sys.modules, "shiny", fake_shiny)
    monkeypatch.setitem(sys.modules, "shinywidgets", fake_shinywidgets)
    monkeypatch.setitem(sys.modules, "plotly", fake_plotly)
    monkeypatch.setitem(sys.modules, "plotly.graph_objects", fake_graph_objects)
    monkeypatch.setitem(sys.modules, "app", fake_app)
    monkeypatch.setitem(sys.modules, "app.renders", fake_app_renders)
    monkeypatch.setitem(sys.modules, "app.config", fake_config)
    monkeypatch.setitem(sys.modules, "app.renders.ecg_sweep", fake_ecg_sweep)
    monkeypatch.setitem(sys.modules, "app.renders.h10_motion", fake_h10_motion)
    monkeypatch.setitem(sys.modules, "app.renders.h10_ecg_bridge", fake_h10_ecg_bridge)
    monkeypatch.setitem(sys.modules, "app.sparkline", fake_sparkline)
    monkeypatch.setitem(sys.modules, "app.renders.render_utils", fake_render_utils)

    module_name = f"app.renders.{Path(filename).stem}_under_test"
    sys.modules.pop(module_name, None)
    spec = importlib.util.spec_from_file_location(
        module_name, APP_ROOT / "renders" / filename
    )
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
        {
            "11": _FakeValue(
                {
                    "temperature_c": 22.34,
                    "humidity_rh": 45.67,
                    "co2_ppm": 520,
                    "voc_index": 35.2,
                    "nox_index": 1.0,
                }
            )
        },
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


def test_h10_value_boxes_format_current_snapshot(monkeypatch) -> None:
    module, registry = _load_render_module(
        monkeypatch,
        "h10.py",
        {
            "H10_DEVICES": {
                "11": {
                    "label": "11 (192.168.121.11)",
                    "stream": "http://h10-11",
                    "ecg_stream": "http://h10-11/ecg",
                    "acc_stream": "http://h10-11/acc",
                }
            },
            "H10_CHARTS": {
                "bpm": "Heart Rate (BPM)",
                "rr": "Last RR Interval (ms)",
                "ecg": "ECG (µV)",
                "acc_dyn": "Mean Dynamic Acceleration",
                "motion": "Acceleration Axes",
            },
        },
    )
    input_obj = _FakeInput(device="11")
    session = _FakeSession()
    module.register_h10_renders(
        input_obj,
        {
            "11": _FakeValue(
                {
                    "heart_rate_bpm": 72.0,
                    "rr_avg_ms": 832.0,
                    "rr_last_ms": 840.0,
                    "rr_count": 2,
                    "rr_intervals_ms": [824.0, 840.0],
                }
            )
        },
        {"11": deque()},
        {"11": _FakeValue({"samples_uv": [1, 2, 3], "sample_rate_hz": 130})},
        {"11": deque([1, 2, 3])},
        {"11": deque([{"samples_uv": [1, 2, 3], "sample_rate_hz": 130, "total_samples": 3}])},
        {"11": _FakeValue({"mean_dynamic_accel_mg": 18.4, "sample_rate_hz": 200})},
        {"11": deque([(None, {"mean_dynamic_accel_mg": 18.4})])},
        {"11": _FakeValue({"trail_points": [(0.0, 0.0, 1000.0), (10.0, -5.0, 980.0)]})},
        lambda: "plotly_dark",
        _FakeFigureWidget(),
        {"chart": None, "dev": None, "tpl": None},
        session,
    )

    assert registry.text["h10_bpm_val"]() == "72 bpm"
    assert registry.text["h10_rr_last_val"]() == "840 ms"
    assert registry.text["h10_ecg_val"]() == "130 Hz"
    assert registry.text["h10_acc_val"]() == "18 mg"
    assert registry.ui["h10_ecg_spark"]() == "SPARK:['1 µV', '2 µV', '3 µV']"
    assert registry.ui["h10_acc_spark"]() == "SPARK:['18 mg']"
    motion_preview = registry.ui["h10_motion_preview"]()
    assert "<svg" in motion_preview
    assert "polyline" in motion_preview
    assert ">X<" in motion_preview
    assert ">Y<" in motion_preview
    assert "+1500" not in motion_preview
    assert "10 mg" not in motion_preview
    assert registry.ui["h10_detail_view"]() == {"tag": "output_widget", "id": "h10_graph"}
    selector = registry.ui["h10_device_selector"]()
    assert selector["tag"] == "input_select"
    assert selector["args"][0] == "h10_device"
    assert selector["args"][2] == {"11": "11 (192.168.121.11)"}


def test_h10_selector_is_rendered_for_nodes_with_multiple_streams(monkeypatch) -> None:
    module, registry = _load_render_module(
        monkeypatch,
        "h10.py",
        {
            "H10_DEVICES": {
                "11:strap-a": {
                    "label": "Chest A",
                    "device": "11",
                    "stream": "http://h10-11/a",
                },
                "11:strap-b": {
                    "label": "Chest B",
                    "device": "11",
                    "stream": "http://h10-11/b",
                },
            },
            "H10_DEVICE_OPTIONS": {
                "11": {
                    "11:strap-a": "Chest A",
                    "11:strap-b": "Chest B",
                }
            },
            "H10_DEFAULTS": {"11": "11:strap-a"},
            "H10_CHARTS": {
                "bpm": "Heart Rate (BPM)",
                "rr": "Last RR Interval (ms)",
                "ecg": "ECG (µV)",
                "acc_dyn": "Mean Dynamic Acceleration",
                "motion": "Acceleration Axes",
            },
        },
    )
    session = _FakeSession()
    module.register_h10_renders(
        _FakeInput(device="11", h10_device="11:strap-b"),
        {
            "11:strap-a": _FakeValue({"heart_rate_bpm": 72.0}),
            "11:strap-b": _FakeValue({"heart_rate_bpm": 81.0}),
        },
        {"11:strap-a": deque(), "11:strap-b": deque()},
        {
            "11:strap-a": _FakeValue({"samples_uv": [], "sample_rate_hz": 130}),
            "11:strap-b": _FakeValue({"samples_uv": [], "sample_rate_hz": 130}),
        },
        {"11:strap-a": deque(), "11:strap-b": deque()},
        {"11:strap-a": deque(), "11:strap-b": deque()},
        {
            "11:strap-a": _FakeValue({"mean_dynamic_accel_mg": 0.0, "sample_rate_hz": 200}),
            "11:strap-b": _FakeValue({"mean_dynamic_accel_mg": 0.0, "sample_rate_hz": 200}),
        },
        {"11:strap-a": deque(), "11:strap-b": deque()},
        {
            "11:strap-a": _FakeValue({"trail_points": []}),
            "11:strap-b": _FakeValue({"trail_points": []}),
        },
        lambda: "plotly_dark",
        _FakeFigureWidget(),
        {"chart": None, "dev": None, "tpl": None},
        session,
    )

    selector = registry.ui["h10_device_selector"]()

    assert selector["tag"] == "input_select"
    assert selector["args"][0] == "h10_device"
    assert selector["args"][1] == ""
    assert selector["args"][2] == {"11:strap-a": "Chest A", "11:strap-b": "Chest B"}
    assert selector["kwargs"]["selected"] == "11:strap-b"
    assert registry.text["h10_bpm_val"]() == "81 bpm"


def test_h10_single_stream_does_not_require_dynamic_selector_input(monkeypatch) -> None:
    module, _ = _load_render_module(
        monkeypatch,
        "h10.py",
        {
            "H10_DEVICES": {
                "11:strap-a": {
                    "label": "Chest A",
                    "device": "11",
                    "stream": "http://h10-11/a",
                }
            },
            "H10_DEVICE_OPTIONS": {
                "11": {
                    "11:strap-a": "Chest A",
                }
            },
            "H10_DEFAULTS": {"11": "11:strap-a"},
            "H10_CHARTS": {
                "bpm": "Heart Rate (BPM)",
                "rr": "Last RR Interval (ms)",
                "ecg": "ECG (µV)",
                "acc_dyn": "Mean Dynamic Acceleration",
                "motion": "Acceleration Axes",
            },
        },
    )

    input_obj = SimpleNamespace(device=lambda: "11")

    assert module._selected_h10_stream(input_obj) == "11:strap-a"


def test_h10_invalid_device_returns_na_and_empty_sparklines(monkeypatch) -> None:
    module, registry = _load_render_module(
        monkeypatch,
        "h10.py",
        {
            "H10_DEVICES": {
                "11": {
                    "label": "11 (192.168.121.11)",
                    "stream": "http://h10-11",
                    "ecg_stream": "http://h10-11/ecg",
                    "acc_stream": "http://h10-11/acc",
                }
            },
            "H10_CHARTS": {
                "bpm": "Heart Rate (BPM)",
                "rr": "Last RR Interval (ms)",
                "ecg": "ECG (µV)",
                "acc_dyn": "Mean Dynamic Acceleration",
                "motion": "Acceleration Axes",
            },
        },
    )
    input_obj = _FakeInput(device="99")
    session = _FakeSession()
    module.register_h10_renders(
        input_obj,
        {"11": _FakeValue({"heart_rate_bpm": 72.0, "rr_last_ms": 840.0})},
        {"11": deque()},
        {"11": _FakeValue({"samples_uv": [1, 2, 3], "sample_rate_hz": 130})},
        {"11": deque([1, 2, 3])},
        {"11": deque([{"samples_uv": [1, 2, 3], "sample_rate_hz": 130, "total_samples": 3}])},
        {"11": _FakeValue({"mean_dynamic_accel_mg": 18.4, "sample_rate_hz": 200})},
        {"11": deque([(None, {"mean_dynamic_accel_mg": 18.4})])},
        {"11": _FakeValue({"trail_points": []})},
        lambda: "plotly_dark",
        _FakeFigureWidget(),
        {"chart": None, "dev": None, "tpl": None},
        session,
    )

    assert registry.text["h10_bpm_val"]() == "N/A"
    assert registry.text["h10_rr_last_val"]() == "N/A"
    assert registry.text["h10_ecg_val"]() == "N/A"
    assert registry.text["h10_acc_val"]() == "N/A"
    assert registry.ui["h10_bpm_spark"]() == ""
    assert registry.ui["h10_rr_last_spark"]() == ""
    assert registry.ui["h10_ecg_spark"]() == ""
    assert registry.ui["h10_acc_spark"]() == ""
    assert registry.ui["h10_motion_preview"]() == ""


def test_pulse_invalid_device_clears_chart_and_resets_state(monkeypatch) -> None:
    module, registry = _load_render_module(
        monkeypatch,
        "pulse.py",
        {
            "DEVICES": {
                "10": {"label": "10 (192.168.121.10)", "url": "http://pulse-10"}
            },
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


def test_sen66_invalid_device_clears_chart_sets_annotation_and_resets_state(
    monkeypatch,
) -> None:
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


def test_h10_invalid_device_clears_chart_sets_annotation_and_resets_state(
    monkeypatch,
) -> None:
    module, registry = _load_render_module(
        monkeypatch,
        "h10.py",
        {
            "H10_DEVICES": {
                "11": {
                    "label": "11 (192.168.121.11)",
                    "stream": "http://h10-11",
                    "ecg_stream": "http://h10-11/ecg",
                    "acc_stream": "http://h10-11/acc",
                }
            },
            "H10_CHARTS": {
                "bpm": "Heart Rate (BPM)",
                "rr": "Last RR Interval (ms)",
                "ecg": "ECG (µV)",
                "acc_dyn": "Mean Dynamic Acceleration",
                "motion": "Acceleration Axes",
            },
        },
    )
    widget = _FakeFigureWidget()
    widget.data = ["stale"]
    widget.layout.annotations = ["old"]
    state = {"chart": "bpm", "dev": "11", "tpl": "plotly_dark"}
    session = _FakeSession()

    module.register_h10_renders(
        _FakeInput(device="99", h10_chart="bpm"),
        {"11": _FakeValue({"heart_rate_bpm": 72.0})},
        {"11": deque()},
        {"11": _FakeValue({"samples_uv": [1, 2, 3], "sample_rate_hz": 130})},
        {"11": deque([1, 2, 3])},
        {"11": deque([{"samples_uv": [1, 2, 3], "sample_rate_hz": 130, "total_samples": 3}])},
        {"11": _FakeValue({"mean_dynamic_accel_mg": 18.4, "sample_rate_hz": 200})},
        {"11": deque([(None, {"mean_dynamic_accel_mg": 18.4})])},
        {"11": _FakeValue({"trail_points": []})},
        lambda: "plotly_dark",
        widget,
        state,
        session,
    )

    registry.effects["_update_h10_chart"]()

    assert widget.data == []
    assert widget.layout.annotations == [module._NO_DATA_ANNOTATION]
    assert state == {"chart": None, "dev": None, "tpl": None}


def test_h10_ecg_chart_streams_sweep_messages(monkeypatch) -> None:
    module, registry = _load_render_module(
        monkeypatch,
        "h10.py",
        {
            "H10_DEVICES": {
                "11": {
                    "label": "11 (192.168.121.11)",
                    "stream": "http://h10-11",
                    "ecg_stream": "http://h10-11/ecg",
                    "acc_stream": "http://h10-11/acc",
                }
            },
            "H10_CHARTS": {
                "bpm": "Heart Rate (BPM)",
                "rr": "Last RR Interval (ms)",
                "ecg": "ECG (µV)",
                "acc_dyn": "Mean Dynamic Acceleration",
                "motion": "Acceleration Axes",
            },
        },
    )
    session = _FakeSession()

    ecg_latest = _FakeValue(
        {"samples_uv": [50, 60], "sample_rate_hz": 130, "total_samples": 6}
    )
    ecg_samples = deque([10, 20, 30, 40, 50, 60])
    ecg_chunks = deque()

    module.register_h10_renders(
        _FakeInput(device="11", h10_chart="ecg"),
        {"11": _FakeValue({"heart_rate_bpm": 72.0, "rr_last_ms": 840.0})},
        {"11": deque()},
        {"11": ecg_latest},
        {"11": ecg_samples},
        {"11": ecg_chunks},
        {"11": _FakeValue({"mean_dynamic_accel_mg": 18.4, "sample_rate_hz": 200})},
        {"11": deque([(None, {"mean_dynamic_accel_mg": 18.4})])},
        {"11": _FakeValue({"trail_points": []})},
        lambda: "plotly_dark",
        _FakeFigureWidget(),
        {"chart": None, "dev": None, "tpl": None},
        session,
    )

    detail = registry.ui["h10_detail_view"]()
    registry.effects["_update_h10_ecg_sweep"]()

    assert detail["tag"] == "div"
    assert detail["kwargs"]["id"] == "h10_ecg_sweep"
    assert session.messages == [
        (
            "ecg-sweep",
            {
                "plot_id": "h10_ecg_sweep",
                "op": "reset",
                "samples": [10, 20, 30, 40, 50, 60],
                "sample_rate_hz": 130,
                "title": "ECG (µV)",
                "template": "plotly_dark",
            },
        ),
    ]

    session.messages.clear()
    ecg_samples.extend([70, 80])
    ecg_chunks.append(
        {"samples_uv": [70, 80], "sample_rate_hz": 130, "total_samples": 8}
    )
    ecg_latest._value = {
        "samples_uv": [70, 80],
        "sample_rate_hz": 130,
        "total_samples": 8,
    }
    registry.effects["_update_h10_ecg_sweep"]()

    assert session.messages == [
        (
            "ecg-sweep",
            {
                "plot_id": "h10_ecg_sweep",
                "op": "append",
                "samples": [70, 80],
                "sample_rate_hz": 130,
                "title": "ECG (µV)",
                "template": "plotly_dark",
            },
        )
    ]


def test_h10_dynamic_accel_chart_uses_per_second_history(monkeypatch) -> None:
    module, registry = _load_render_module(
        monkeypatch,
        "h10.py",
        {
            "H10_DEVICES": {
                "11": {
                    "label": "11 (192.168.121.11)",
                    "stream": "http://h10-11",
                    "ecg_stream": "http://h10-11/ecg",
                    "acc_stream": "http://h10-11/acc",
                }
            },
            "H10_CHARTS": {
                "bpm": "Heart Rate (BPM)",
                "rr": "Last RR Interval (ms)",
                "ecg": "ECG (µV)",
                "acc_dyn": "Mean Dynamic Acceleration",
                "motion": "Acceleration Axes",
            },
        },
    )
    widget = _FakeFigureWidget()
    acc_history = deque(
        [
            ("t1", {"mean_dynamic_accel_mg": 12.0, "sample_rate_hz": 200}),
            ("t2", {"mean_dynamic_accel_mg": 18.0, "sample_rate_hz": 200}),
        ]
    )

    module.register_h10_renders(
        _FakeInput(device="11", h10_chart="acc_dyn"),
        {"11": _FakeValue({"heart_rate_bpm": 72.0, "rr_last_ms": 840.0})},
        {"11": deque()},
        {"11": _FakeValue({"samples_uv": [10, 20, 30], "sample_rate_hz": 130})},
        {"11": deque([10, 20, 30])},
        {"11": deque([{"samples_uv": [10, 20, 30], "sample_rate_hz": 130, "total_samples": 3}])},
        {"11": _FakeValue({"mean_dynamic_accel_mg": 18.0, "sample_rate_hz": 200})},
        {"11": acc_history},
        {"11": _FakeValue({"trail_points": []})},
        lambda: "plotly_dark",
        widget,
        {"chart": None, "dev": None, "tpl": None},
        _FakeSession(),
    )

    registry.effects["_update_h10_chart"]()

    assert len(widget.data) == 1
    assert widget.data[0].y == [12.0, 18.0]
    assert widget.data[0].name == "Mean Dynamic Acceleration"
    assert widget.layout.yaxis["title"] == "mg"


def test_h10_motion_chart_renders_svg_detail_instead_of_plotly(monkeypatch) -> None:
    module, registry = _load_render_module(
        monkeypatch,
        "h10.py",
        {
            "H10_DEVICES": {
                "11": {
                    "label": "11 (192.168.121.11)",
                    "stream": "http://h10-11",
                    "ecg_stream": "http://h10-11/ecg",
                    "acc_stream": "http://h10-11/acc",
                }
            },
            "H10_CHARTS": {
                "bpm": "Heart Rate (BPM)",
                "rr": "Last RR Interval (ms)",
                "ecg": "ECG (µV)",
                "acc_dyn": "Mean Dynamic Acceleration",
                "motion": "Acceleration Axes",
            },
        },
    )
    widget = _FakeFigureWidget()
    widget.data = ["keep"]
    session = _FakeSession()

    module.register_h10_renders(
        _FakeInput(device="11", h10_chart="motion"),
        {"11": _FakeValue({"heart_rate_bpm": 72.0, "rr_last_ms": 840.0})},
        {"11": deque()},
        {"11": _FakeValue({"samples_uv": [10, 20, 30], "sample_rate_hz": 130})},
        {"11": deque([10, 20, 30])},
        {"11": deque([{"samples_uv": [10, 20, 30], "sample_rate_hz": 130, "total_samples": 3}])},
        {"11": _FakeValue({"mean_dynamic_accel_mg": 18.0, "sample_rate_hz": 200})},
        {"11": deque([(None, {"mean_dynamic_accel_mg": 18.0})])},
        {"11": _FakeValue({"trail_points": [(0.0, 0.0, 1000.0), (12.0, -8.0, 990.0)]})},
        lambda: "plotly_dark",
        widget,
        {"chart": "bpm", "dev": "11", "tpl": "plotly_dark"},
        session,
    )

    registry.effects["_update_h10_chart"]()

    detail_html = registry.ui["h10_detail_view"]()
    assert detail_html.count("<svg") == 3
    assert detail_html.count("polyline") == 3
    assert "X-Y" not in detail_html
    assert "X-Z" not in detail_html
    assert "Y-Z" not in detail_html
    assert "+1500" in detail_html
    assert "-1500" in detail_html
    assert "Z: +990 mg" in detail_html
    assert widget.data == ["keep"]


def test_pulse_empty_history_leaves_existing_chart_unchanged(monkeypatch) -> None:
    module, registry = _load_render_module(
        monkeypatch,
        "pulse.py",
        {
            "DEVICES": {
                "10": {"label": "10 (192.168.121.10)", "url": "http://pulse-10"}
            },
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
