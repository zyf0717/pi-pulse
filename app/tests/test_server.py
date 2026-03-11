from pathlib import Path
from types import ModuleType, SimpleNamespace
import importlib.util
import sys


APP_ROOT = Path(__file__).resolve().parents[1]


class _FakeFigureWidget:
    def __init__(self, layout=None):
        self.layout = layout


def _load_server_module(monkeypatch):
    calls = {
        "theme_picker_server": 0,
        "ensure_ingest_started": 0,
        "pulse_register": [],
        "sen66_register": [],
        "gps_register": [],
        "h10_register": [],
        "pacer_register": [],
    }

    fake_shinyswatch = ModuleType("shinyswatch")

    def theme_picker_server() -> None:
        calls["theme_picker_server"] += 1

    fake_shinyswatch.theme_picker_server = theme_picker_server

    fake_shiny = ModuleType("shiny")

    class _Reactive:
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

    fake_ingest = ModuleType("app.ingest")
    fake_ingest.GLOBAL_INGEST = SimpleNamespace(
        pulse_latest={"10": object()},
        pulse_temp_history={"10": []},
        sen66_latest={"11": object()},
        sen66_nc_latest={"11": object()},
        sen66_history={"11": []},
        sen66_nc_history={"11": []},
        gps_latest={"pixel-7": object()},
        gps_history={"pixel-7": []},
        h10_latest={"11:6FFF5628": object()},
        h10_history={"11:6FFF5628": []},
        h10_ecg_latest={"11:6FFF5628": object()},
        h10_ecg_samples={"11:6FFF5628": []},
        h10_ecg_chunks={"11:6FFF5628": []},
        h10_acc_latest={"11:6FFF5628": object()},
        h10_acc_history={"11:6FFF5628": []},
        h10_motion_latest={"11:6FFF5628": object()},
        pacer_hr_latest={"pixel-7:DA2E2324": object()},
        pacer_hr_history={"pixel-7:DA2E2324": []},
        pacer_acc_latest={"pixel-7:DA2E2324": object()},
        pacer_acc_history={"pixel-7:DA2E2324": []},
        pacer_motion_latest={"pixel-7:DA2E2324": object()},
        pacer_ppi_latest={"pixel-7:DA2E2324": object()},
        pacer_ppi_history={"pixel-7:DA2E2324": []},
    )

    def ensure_global_ingest_started():
        calls["ensure_ingest_started"] += 1
        return fake_ingest.GLOBAL_INGEST

    fake_ingest.ensure_global_ingest_started = ensure_global_ingest_started

    fake_pulse = ModuleType("app.renders.pulse")

    def register_pulse_renders(*args) -> None:
        calls["pulse_register"].append(args)

    fake_pulse.register_pulse_renders = register_pulse_renders

    fake_sen66 = ModuleType("app.renders.sen66")

    def register_sen66_renders(*args) -> None:
        calls["sen66_register"].append(args)

    fake_sen66.register_sen66_renders = register_sen66_renders

    fake_h10 = ModuleType("app.renders.h10")
    fake_gps = ModuleType("app.renders.gps")
    fake_pacer = ModuleType("app.renders.pacer")

    def register_h10_renders(*args) -> None:
        calls["h10_register"].append(args)

    fake_h10.register_h10_renders = register_h10_renders

    def register_gps_renders(*args) -> None:
        calls["gps_register"].append(args)

    fake_gps.register_gps_renders = register_gps_renders

    def register_pacer_renders(*args) -> None:
        calls["pacer_register"].append(args)

    fake_pacer.register_pacer_renders = register_pacer_renders

    monkeypatch.setitem(sys.modules, "app", fake_app)
    monkeypatch.setitem(sys.modules, "app.ingest", fake_ingest)
    monkeypatch.setitem(sys.modules, "shinyswatch", fake_shinyswatch)
    monkeypatch.setitem(sys.modules, "shiny", fake_shiny)
    monkeypatch.setitem(sys.modules, "plotly", fake_plotly)
    monkeypatch.setitem(sys.modules, "plotly.graph_objects", fake_graph_objects)
    monkeypatch.setitem(sys.modules, "app.renders", fake_app_renders)
    monkeypatch.setitem(sys.modules, "app.renders.gps", fake_gps)
    monkeypatch.setitem(sys.modules, "app.renders.pulse", fake_pulse)
    monkeypatch.setitem(sys.modules, "app.renders.sen66", fake_sen66)
    monkeypatch.setitem(sys.modules, "app.renders.h10", fake_h10)
    monkeypatch.setitem(sys.modules, "app.renders.pacer", fake_pacer)

    module_name = "app.server_under_test"
    sys.modules.pop(module_name, None)
    spec = importlib.util.spec_from_file_location(module_name, APP_ROOT / "server.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module, calls, fake_ingest.GLOBAL_INGEST


class _FakeInput:
    def chart_style(self) -> str:
        return "plotly_dark"


def test_server_starts_global_ingest_and_registers_renders(monkeypatch) -> None:
    server_module, calls, _ = _load_server_module(monkeypatch)

    server_module.server(_FakeInput(), output=None, session=object())

    assert calls["theme_picker_server"] == 1
    assert calls["ensure_ingest_started"] == 1
    assert len(calls["pulse_register"]) == 1
    assert len(calls["sen66_register"]) == 1
    assert len(calls["gps_register"]) == 1
    assert len(calls["h10_register"]) == 1
    assert len(calls["pacer_register"]) == 1


def test_server_passes_shared_ingest_state_to_render_registration(monkeypatch) -> None:
    server_module, calls, ingest_state = _load_server_module(monkeypatch)
    session = object()

    server_module.server(_FakeInput(), output=None, session=session)

    pulse_args = calls["pulse_register"][0]
    sen66_args = calls["sen66_register"][0]
    gps_args = calls["gps_register"][0]
    h10_args = calls["h10_register"][0]
    pacer_args = calls["pacer_register"][0]

    assert pulse_args[1] is ingest_state.pulse_latest
    assert pulse_args[2] is ingest_state.pulse_temp_history
    assert isinstance(pulse_args[4], _FakeFigureWidget)
    assert pulse_args[5] == {"chart": None, "dev": None, "tpl": None}

    assert sen66_args[1] is ingest_state.sen66_latest
    assert sen66_args[2] is ingest_state.sen66_nc_latest
    assert sen66_args[3] is ingest_state.sen66_history
    assert sen66_args[4] is ingest_state.sen66_nc_history
    assert isinstance(sen66_args[6], _FakeFigureWidget)
    assert sen66_args[7] == {"chart": None, "dev": None, "tpl": None}

    assert gps_args[1] is ingest_state.gps_latest
    assert gps_args[2] is ingest_state.gps_history

    assert h10_args[1] is ingest_state.h10_latest
    assert h10_args[2] is ingest_state.h10_history
    assert h10_args[3] is ingest_state.h10_ecg_latest
    assert h10_args[4] is ingest_state.h10_ecg_samples
    assert h10_args[5] is ingest_state.h10_ecg_chunks
    assert h10_args[6] is ingest_state.h10_acc_latest
    assert h10_args[7] is ingest_state.h10_acc_history
    assert h10_args[8] is ingest_state.h10_motion_latest
    assert isinstance(h10_args[10], _FakeFigureWidget)
    assert h10_args[11] == {"chart": None, "dev": None, "tpl": None}
    assert h10_args[12] is session

    assert pacer_args[1] is ingest_state.pacer_hr_latest
    assert pacer_args[2] is ingest_state.pacer_hr_history
    assert pacer_args[3] is ingest_state.pacer_acc_latest
    assert pacer_args[4] is ingest_state.pacer_acc_history
    assert pacer_args[5] is ingest_state.pacer_motion_latest
    assert pacer_args[6] is ingest_state.pacer_ppi_latest
    assert pacer_args[7] is ingest_state.pacer_ppi_history
    assert isinstance(pacer_args[9], _FakeFigureWidget)
    assert pacer_args[10] == {"chart": None, "dev": None, "tpl": None}


def test_server_plotly_template_calc_reads_chart_style(monkeypatch) -> None:
    server_module, calls, _ = _load_server_module(monkeypatch)

    server_module.server(_FakeInput(), output=None, session=object())

    pulse_args = calls["pulse_register"][0]
    sen66_args = calls["sen66_register"][0]
    gps_args = calls["gps_register"][0]
    h10_args = calls["h10_register"][0]
    pacer_args = calls["pacer_register"][0]

    assert pulse_args[0].chart_style() == "plotly_dark"
    assert sen66_args[0].chart_style() == "plotly_dark"
    assert gps_args[0].chart_style() == "plotly_dark"
    assert h10_args[0].chart_style() == "plotly_dark"
    assert pacer_args[0].chart_style() == "plotly_dark"
