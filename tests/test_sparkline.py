import sparkline as sparkline_module


def _passthrough_html(monkeypatch) -> None:
    monkeypatch.setattr(sparkline_module.ui, "HTML", lambda value: value)


def test_sparkline_returns_empty_string_for_short_series(monkeypatch) -> None:
    _passthrough_html(monkeypatch)

    html = sparkline_module.sparkline([1.0])

    assert html == ""


def test_sparkline_renders_single_stat_for_flat_series(monkeypatch) -> None:
    _passthrough_html(monkeypatch)

    html = sparkline_module.sparkline([2.0, 2.0], fmt=lambda value: f"{value:.0f}x")

    assert "justify-content:flex-end" in html
    assert html.count("<div>2x</div>") == 1


def test_sparkline_renders_min_max_with_custom_formatter(monkeypatch) -> None:
    _passthrough_html(monkeypatch)

    html = sparkline_module.sparkline(
        [1.0, 3.5, 2.0],
        fmt=lambda value: f"[{value:.1f}]",
    )

    assert "<div>[3.5]</div><div>[1.0]</div>" in html
    assert 'stroke="#64b5f6"' in html
