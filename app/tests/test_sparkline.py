import importlib.util
import sys
from pathlib import Path
from types import ModuleType


APP_ROOT = Path(__file__).resolve().parents[1]


def _load_sparkline_module(monkeypatch):
    fake_shiny = ModuleType("shiny")
    fake_shiny.ui = ModuleType("shiny.ui")
    fake_shiny.ui.HTML = lambda value: value

    monkeypatch.setitem(sys.modules, "shiny", fake_shiny)

    module_name = "app.sparkline_under_test"
    sys.modules.pop(module_name, None)
    spec = importlib.util.spec_from_file_location(module_name, APP_ROOT / "sparkline.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_sparkline_returns_empty_string_for_short_series(monkeypatch) -> None:
    sparkline_module = _load_sparkline_module(monkeypatch)

    html = sparkline_module.sparkline([1.0])

    assert html == ""


def test_sparkline_renders_single_stat_for_flat_series(monkeypatch) -> None:
    sparkline_module = _load_sparkline_module(monkeypatch)

    html = sparkline_module.sparkline([2.0, 2.0], fmt=lambda value: f"{value:.0f}x")

    assert "justify-content:flex-end" in html
    assert html.count("<div>2x</div>") == 1


def test_sparkline_renders_min_max_with_custom_formatter(monkeypatch) -> None:
    sparkline_module = _load_sparkline_module(monkeypatch)

    html = sparkline_module.sparkline(
        [1.0, 3.5, 2.0],
        fmt=lambda value: f"[{value:.1f}]",
    )

    assert "<div>[3.5]</div><div>[1.0]</div>" in html
    assert 'stroke="#64b5f6"' in html
