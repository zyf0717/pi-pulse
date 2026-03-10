from app.renders.render_utils import metric_value, sparkline_values


class _FakeValue:
    def __init__(self, value):
        self._value = value

    def __call__(self):
        return self._value


def test_metric_value_returns_na_for_blank_string_payloads() -> None:
    value = metric_value(
        "10",
        {"10": {"label": "Pi 10"}},
        {"10": _FakeValue({"temp": "   "})},
        "temp",
        lambda item: f"{item:.1f}°C",
    )

    assert value == "N/A"


def test_metric_value_passes_through_string_payloads() -> None:
    value = metric_value(
        "10",
        {"10": {"label": "Pi 10"}},
        {"10": _FakeValue({"temp": "N/A"})},
        "temp",
        lambda item: f"{item:.1f}°C",
    )

    assert value == "N/A"


def test_metric_value_returns_na_for_missing_fields() -> None:
    value = metric_value(
        "10",
        {"10": {"label": "Pi 10"}},
        {"10": _FakeValue({})},
        "cpu",
        lambda item: f"{item:.1f}%",
    )

    assert value == "N/A"


def test_sparkline_values_filters_non_numeric_history_entries() -> None:
    values = sparkline_values(
        "10",
        {"10": {"label": "Pi 10"}},
        {"10": _FakeValue({"temp": "N/A"})},
        {
            "10": [
                ("t1", {"temp": 21.5}),
                ("t2", {"temp": "N/A"}),
                ("t3", {"temp": 22.0}),
            ]
        },
        "temp",
    )

    assert values == [21.5, 22.0]


def test_sparkline_values_returns_none_when_no_numeric_history_exists() -> None:
    values = sparkline_values(
        "10",
        {"10": {"label": "Pi 10"}},
        {"10": _FakeValue({"temp": "N/A"})},
        {"10": [("t1", {"temp": "N/A"})]},
        "temp",
    )

    assert values is None
