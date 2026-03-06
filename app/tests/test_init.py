import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import ipywidgets.widgets.widget as ipy_widget_mod


APP_ROOT = Path(__file__).resolve().parents[1]


def test_app_init_patches_widget_registry_for_shinywidgets_compat() -> None:
    import app  # noqa: F401

    assert ipy_widget_mod.Widget.widgets is ipy_widget_mod._instances


def test_app_init_tolerates_missing_ipywidgets(monkeypatch) -> None:
    monkeypatch.delitem(sys.modules, "ipywidgets", raising=False)
    monkeypatch.delitem(sys.modules, "ipywidgets.widgets", raising=False)
    monkeypatch.delitem(sys.modules, "ipywidgets.widgets.widget", raising=False)

    real_import = __import__

    def _raising_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "ipywidgets.widgets.widget":
            raise ImportError("ipywidgets unavailable")
        return real_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr("builtins.__import__", _raising_import)

    module_name = "app_init_missing_ipywidgets_under_test"
    sys.modules.pop(module_name, None)
    spec = importlib.util.spec_from_file_location(module_name, APP_ROOT / "__init__.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)

    assert module.__doc__ == "Pi-Pulse application package."
