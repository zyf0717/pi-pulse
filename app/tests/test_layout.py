import importlib.util
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

APP_ROOT = Path(__file__).resolve().parents[1]


def _tag_factory(name: str):
    def _tag(*args, **kwargs):
        return {"tag": name, "args": args, "kwargs": kwargs}

    return _tag


def _load_layout_module(monkeypatch):
    fake_ui = SimpleNamespace(
        page_sidebar=_tag_factory("page_sidebar"),
        head_content=_tag_factory("head_content"),
        sidebar=_tag_factory("sidebar"),
        include_css=_tag_factory("include_css"),
        include_js=_tag_factory("include_js"),
        input_select=_tag_factory("input_select"),
        hr=_tag_factory("hr"),
        input_radio_buttons=_tag_factory("input_radio_buttons"),
        navset_tab=_tag_factory("navset_tab"),
        nav_panel=_tag_factory("nav_panel"),
        br=_tag_factory("br"),
        layout_column_wrap=_tag_factory("layout_column_wrap"),
        card=_tag_factory("card"),
        card_header=_tag_factory("card_header"),
        div=_tag_factory("div"),
        output_text=_tag_factory("output_text"),
        output_ui=_tag_factory("output_ui"),
        span=_tag_factory("span"),
        tooltip=_tag_factory("tooltip"),
        tags=SimpleNamespace(br=_tag_factory("tags.br")),
    )

    fake_shiny = ModuleType("shiny")
    fake_shiny.ui = fake_ui

    fake_shinyswatch = ModuleType("shinyswatch")
    fake_shinyswatch.theme_picker_ui = _tag_factory("theme_picker_ui")
    fake_shinyswatch.theme = SimpleNamespace(darkly="darkly")

    fake_faicons = ModuleType("faicons")
    fake_faicons.icon_svg = lambda *args, **kwargs: {
        "tag": "icon_svg",
        "args": args,
        "kwargs": kwargs,
    }

    fake_shinywidgets = ModuleType("shinywidgets")
    fake_shinywidgets.output_widget = _tag_factory("output_widget")

    fake_app = ModuleType("app")
    fake_app.__path__ = []
    fake_app_renders = ModuleType("app.renders")
    fake_app_renders.__path__ = []
    fake_config = ModuleType("app.config")
    fake_config.ALL_DEVICES = {"10": "10 (192.168.121.10)", "11": "11 (192.168.121.11)"}
    fake_config.ALL_DEVICES_DEFAULT = "11"
    fake_config.H10_ACC_DYNAMIC_WINDOW_S = 0.5
    fake_config.PULSE_CHARTS = {
        "cpu": "CPU Usage (%)",
        "cpu_freq": "CPU Frequency (MHz)",
        "mem": "Memory Usage (%)",
        "temp": "Temperature (°C)",
        "net": "Download & Upload (KB/s)",
    }
    fake_config.SEN66_CHARTS = {
        "temp_hum": "Temperature & Humidity",
        "co2": "CO₂",
        "voc_nox": "VOC & NOx",
        "pm_mass": "PM Mass Concentration (µg/m³)",
        "pm_nc": "PM Number Concentration (#/cm³)",
    }
    fake_config.H10_CHARTS = {
        "bpm": "Heart Rate (BPM)",
        "rr": "Last RR Interval (ms)",
        "ecg": "ECG (µV)",
        "acc_dyn": "Mean Dynamic Acceleration",
        "motion": "Acceleration Axes",
    }

    monkeypatch.setitem(sys.modules, "shiny", fake_shiny)
    monkeypatch.setitem(sys.modules, "shinyswatch", fake_shinyswatch)
    monkeypatch.setitem(sys.modules, "faicons", fake_faicons)
    monkeypatch.setitem(sys.modules, "shinywidgets", fake_shinywidgets)
    monkeypatch.setitem(sys.modules, "app", fake_app)
    monkeypatch.setitem(sys.modules, "app.renders", fake_app_renders)
    monkeypatch.setitem(sys.modules, "app.config", fake_config)

    module_name = "app.layout_under_test"
    sys.modules.pop(module_name, None)
    spec = importlib.util.spec_from_file_location(module_name, APP_ROOT / "layout.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_metric_card_sets_click_metadata(monkeypatch) -> None:
    module = _load_layout_module(monkeypatch)

    card = module._metric_card(
        "CPU Usage",
        "cpu_val",
        "cpu_spark",
        chart_target="pulse_chart",
        chart_value="cpu",
    )

    assert card["tag"] == "div"
    assert card["kwargs"]["class"] == module._CARD_ATTRS_CLASS
    assert card["kwargs"]["data-chart-target"] == "pulse_chart"
    assert card["kwargs"]["data-chart-value"] == "cpu"
    inner_card = card["args"][0]
    assert inner_card["tag"] == "card"


def test_pulse_cards_match_chart_mapping(monkeypatch) -> None:
    module = _load_layout_module(monkeypatch)

    cards = module._pulse_cards()

    assert len(cards) == 6
    assert [card["kwargs"]["data-chart-target"] for card in cards] == [
        "pulse_chart"
    ] * 6
    assert [card["kwargs"]["data-chart-value"] for card in cards] == [
        "cpu",
        "cpu_freq",
        "mem",
        "temp",
        "net",
        "net",
    ]


def test_sen66_cards_match_chart_mapping(monkeypatch) -> None:
    module = _load_layout_module(monkeypatch)

    cards = module._sen66_cards()

    assert len(cards) == 5
    assert [card["kwargs"]["data-chart-target"] for card in cards] == [
        "sen66_chart"
    ] * 5
    assert [card["kwargs"]["data-chart-value"] for card in cards] == [
        "temp_hum",
        "temp_hum",
        "co2",
        "voc_nox",
        "voc_nox",
    ]


def test_h10_cards_match_chart_mapping(monkeypatch) -> None:
    module = _load_layout_module(monkeypatch)

    cards = module._h10_cards()

    assert len(cards) == 5
    assert [card["kwargs"]["data-chart-target"] for card in cards] == ["h10_chart"] * 5
    assert [card["kwargs"]["data-chart-value"] for card in cards] == [
        "bpm",
        "rr",
        "ecg",
        "acc_dyn",
        "motion",
    ]
    first_header = cards[0]["args"][0]["args"][0]
    assert first_header["tag"] == "card_header"
    assert first_header["args"][0] == "Heart Rate"
    accel_header = cards[3]["args"][0]["args"][0]
    assert accel_header["args"][0]["tag"] == "tooltip"
    assert "Average movement over the last 0.5 s." in accel_header["args"][0]["args"]
    assert "Baseline tilt/gravity is removed first." in accel_header["args"][0]["args"]
    assert "Higher values mean more motion during that window." in accel_header["args"][0]["args"]
    tilt_header = cards[4]["args"][0]["args"][0]
    assert tilt_header["args"][0]["tag"] == "tooltip"
    assert tilt_header["args"][0]["args"][0]["tag"] == "span"
    assert tilt_header["args"][0]["args"][0]["args"][0] == "Acceleration Axes "
    assert (
        "At rest, the combined X/Y/Z acceleration is usually ~1000 mg because of gravity (1g ≈ 9.81 m/s²)."
        in tilt_header["args"][0]["args"]
    )


def test_h10_panel_includes_stream_selector_placeholder(monkeypatch) -> None:
    module = _load_layout_module(monkeypatch)

    panel = module._h10_panel()
    control_row = next(
        item
        for item in panel["args"]
        if isinstance(item, dict)
        and item["tag"] == "div"
        and item["kwargs"].get("class_")
        == "d-flex flex-wrap align-items-end gap-3 justify-content-start"
    )

    assert panel["tag"] == "nav_panel"
    assert any(
        item["tag"] == "output_ui" and item["args"] == ("h10_device_selector",)
        for item in control_row["args"]
        if isinstance(item, dict)
    )


def test_app_ui_includes_static_assets(monkeypatch) -> None:
    module = _load_layout_module(monkeypatch)

    head = module.app_ui["args"][1]

    assert head["tag"] == "head_content"
    asset_tags = [item["tag"] for item in head["args"] if isinstance(item, dict)]
    assert asset_tags == ["include_css", "include_js", "include_js", "include_js"]
    assert str(head["args"][0]["args"][0]).endswith("app/www/app.css")
    assert str(head["args"][1]["args"][0]).endswith("app/www/keepalive.js")
    assert str(head["args"][2]["args"][0]).endswith("app/www/card-click.js")
    assert str(head["args"][3]["args"][0]).endswith("app/www/ecg-sweep.js")
