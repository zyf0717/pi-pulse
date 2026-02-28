"""Shared helpers for Shiny render registration."""

from collections.abc import Mapping


def metric_value(
    device: str,
    devices: Mapping[str, object],
    latest: Mapping[str, object],
    field: str,
    formatter,
) -> str:
    if device not in devices:
        return "N/A"
    return formatter(latest[device]().get(field, 0.0))


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
    return [data.get(field, 0.0) * scale for _, data in history[device]]


def reset_chart_state(state: dict) -> None:
    state.update({"chart": None, "dev": None, "tpl": None})


def needs_chart_rebuild(state: Mapping[str, object], chart: str, dev: str, tpl: str) -> bool:
    return state["chart"] != chart or state["dev"] != dev or state["tpl"] != tpl
