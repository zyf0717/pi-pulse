from pathlib import Path
from types import ModuleType, SimpleNamespace
import importlib.util
import sys


ROOT = Path(__file__).resolve().parents[1]


def _tag_factory(name: str):
    def _tag(*args, **kwargs):
        return {"tag": name, "args": args, "kwargs": kwargs}

    return _tag


def _load_layout_module(monkeypatch):
    fake_ui = SimpleNamespace(
        page_sidebar=_tag_factory("page_sidebar"),
        sidebar=_tag_factory("sidebar"),
        input_select=_tag_factory("input_select"),
        hr=_tag_factory("hr"),
        input_radio_buttons=_tag_factory("input_radio_buttons"),
        HTML=_tag_factory("HTML"),
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
    fake_faicons.icon_svg = lambda *args, **kwargs: {"tag": "icon_svg", "args": args, "kwargs": kwargs}

    fake_shinywidgets = ModuleType("shinywidgets")
    fake_shinywidgets.output_widget = _tag_factory("output_widget")

    fake_config = ModuleType("config")
    fake_config.ALL_DEVICES = {"10": "10 (192.168.121.10)", "11": "11 (192.168.121.11)"}
    fake_config.ALL_DEVICES_DEFAULT = "11"
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

    monkeypatch.setitem(sys.modules, "shiny", fake_shiny)
    monkeypatch.setitem(sys.modules, "shinyswatch", fake_shinyswatch)
    monkeypatch.setitem(sys.modules, "faicons", fake_faicons)
    monkeypatch.setitem(sys.modules, "shinywidgets", fake_shinywidgets)
    monkeypatch.setitem(sys.modules, "config", fake_config)

    module_name = "layout_under_test"
    sys.modules.pop(module_name, None)
    spec = importlib.util.spec_from_file_location(module_name, ROOT / "layout.py")
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
    assert [card["kwargs"]["data-chart-target"] for card in cards] == ["pulse_chart"] * 6
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
    assert [card["kwargs"]["data-chart-target"] for card in cards] == ["sen66_chart"] * 5
    assert [card["kwargs"]["data-chart-value"] for card in cards] == [
        "temp_hum",
        "temp_hum",
        "co2",
        "voc_nox",
        "voc_nox",
    ]


def test_card_click_script_updates_existing_selects(monkeypatch) -> None:
    module = _load_layout_module(monkeypatch)

    assert ".metric-card-trigger" in module._CARD_CLICK_JS
    assert 'getAttribute("data-chart-target")' in module._CARD_CLICK_JS
    assert 'dispatchEvent(new Event("change", { bubbles: true }))' in module._CARD_CLICK_JS
