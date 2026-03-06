"""Pi-Pulse application package."""

try:
    import ipywidgets.widgets.widget as _ipy_widget_mod
except Exception:
    _ipy_widget_mod = None

if _ipy_widget_mod is not None:
    # shinywidgets still reads Widget.widgets at import time, but ipywidgets 8
    # marks that attribute deprecated. Point it at the underlying registry
    # before shinywidgets imports through the app package.
    _ipy_widget_mod.Widget.widgets = _ipy_widget_mod._instances
