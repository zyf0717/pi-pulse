"""Standalone Plotly sweep helpers for ECG rendering."""

import plotly.io as pio

ECG_SWEEP_MESSAGE = "ecg-sweep"
ECG_SWEEP_FPS = 30.0
ECG_SWEEP_WINDOW_SECONDS = 10.0
ECG_SWEEP_GAP_POINTS = 13.0
ECG_SWEEP_MAX_PENDING_SECONDS = 1.0
ECG_SWEEP_Y_RANGE = (-2000.0, 2500.0)

def build_ecg_sweep_message(
    plot_id: str,
    *,
    op: str,
    samples: list[int],
    sample_rate_hz: int,
    title: str = "ECG",
    template: str = "plotly_dark",
    x_title: str = "",
    y_title: str = "Amplitude (\u00b5V)",
    window_seconds: float = ECG_SWEEP_WINDOW_SECONDS,
    gap_points: int = ECG_SWEEP_GAP_POINTS,
    fps: float = ECG_SWEEP_FPS,
    max_pending_seconds: float = ECG_SWEEP_MAX_PENDING_SECONDS,
    line_color: str | None = None,
    cursor_color: str | None = None,
    line_width: int = 2,
    y_range: tuple[float, float] = ECG_SWEEP_Y_RANGE,
) -> dict[str, object]:
    max_points = max(1, int(round(sample_rate_hz * window_seconds)))
    max_pending_points = max(1, int(round(sample_rate_hz * max_pending_seconds)))
    template_config = pio.templates[template].to_plotly_json()
    return {
        "plot_id": plot_id,
        "op": op,
        "samples": samples,
        "sample_rate_hz": sample_rate_hz,
        "fps": fps,
        "max_points": max_points,
        "max_pending_points": max_pending_points,
        "gap_points": gap_points,
        "title": title,
        "template": template,
        "template_config": template_config,
        "x_title": x_title,
        "y_title": y_title,
        "line_color": line_color,
        "cursor_color": cursor_color,
        "line_width": line_width,
        "y_range": [float(y_range[0]), float(y_range[1])],
    }
