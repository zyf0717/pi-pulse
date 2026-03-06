from pathlib import Path


APP_ROOT = Path(__file__).resolve().parents[1]
WWW_DIR = APP_ROOT / "www"


def test_card_click_asset_contains_card_trigger_behavior() -> None:
    script = (WWW_DIR / "card-click.js").read_text(encoding="utf-8")

    assert 'classList.contains("metric-card-trigger")' in script
    assert 'getAttribute("data-chart-target")' in script
    assert 'dispatchEvent(new Event("change", { bubbles: true }))' in script


def test_keepalive_asset_handles_disconnect_reload() -> None:
    script = (WWW_DIR / "keepalive.js").read_text(encoding="utf-8")

    assert 'document.addEventListener("shiny:disconnected"' in script
    assert 'fetch(window.location.href, { method: "HEAD", cache: "no-store" })' in script


def test_ecg_sweep_asset_registers_custom_message_handler() -> None:
    script = (WWW_DIR / "ecg-sweep.js").read_text(encoding="utf-8")

    assert 'window.Shiny.addCustomMessageHandler("ecg-sweep"' in script
    assert 'window.Plotly.newPlot(' in script
    assert 'window.Plotly.restyle(' in script
