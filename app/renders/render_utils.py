"""Shared helpers for Shiny render registration."""

from collections.abc import Mapping


def _numeric_value(value: object) -> float | None:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    return None


def metric_value(
    device: str,
    devices: Mapping[str, object],
    latest: Mapping[str, object],
    field: str,
    formatter,
) -> str:
    if device not in devices:
        return "N/A"
    raw_value = latest[device]().get(field)
    value = _numeric_value(raw_value)
    if value is None:
        if isinstance(raw_value, str) and raw_value.strip():
            return raw_value
        return "N/A"
    try:
        return formatter(value)
    except Exception:
        if isinstance(raw_value, str) and raw_value.strip():
            return raw_value
        return "N/A"


def sparkline_values(
    device: str,
    devices: Mapping[str, object],
    latest: Mapping[str, object],
    history: Mapping[str, object],
    field: str,
    *,
    scale: float = 1.0,
):
    if device not in devices:
        return None
    latest[device]()  # establish reactive dependency
    values = []
    for _, data in history[device]:
        value = _numeric_value(data.get(field, 0.0))
        if value is None:
            continue
        values.append(value * scale)
    return values or None


def reset_chart_state(state: dict) -> None:
    state.update({"chart": None, "dev": None, "tpl": None})


def needs_chart_rebuild(
    state: Mapping[str, object], chart: str, dev: str, tpl: str
) -> bool:
    return state["chart"] != chart or state["dev"] != dev or state["tpl"] != tpl
