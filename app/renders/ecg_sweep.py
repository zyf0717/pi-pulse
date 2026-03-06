"""Standalone Plotly sweep helpers for ECG rendering experiments.

This module is intentionally decoupled from the current H10 render path. It
provides:

- a paced frame player that converts raw sample buffers into display frames
- a client-side Plotly sweep renderer driven by Shiny custom messages
- a small message builder so server code only sends new samples
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from time import monotonic
from typing import Generic, Sequence, TypeVar

T = TypeVar("T")

ECG_SWEEP_MESSAGE = "ecg-sweep"
ECG_SWEEP_FPS = 30.0
ECG_SWEEP_WINDOW_SECONDS = 6.0
ECG_SWEEP_GAP_POINTS = 8
ECG_SWEEP_Y_RANGE = (-2000.0, 2500.0)

ECG_SWEEP_JS = """
<script>
(function () {
  var states = new Map();

  function ensureHandler() {
    if (!window.Shiny || !window.Plotly) {
      setTimeout(ensureHandler, 50);
      return;
    }

    window.Shiny.addCustomMessageHandler("ecg-sweep", function (msg) {
      var container = document.getElementById(msg.plot_id);
      if (!container || !window.Plotly) {
        return;
      }

      if (msg.op === "clear") {
        window.Plotly.purge(container);
        container.replaceChildren();
        states.delete(msg.plot_id);
        return;
      }

      var state = states.get(msg.plot_id);
      var shouldReset = msg.op === "reset" || !state;
      if (shouldReset) {
        var maxPoints = msg.max_points;
        var sampleRate = msg.sample_rate_hz;
        var xValues = [];
        for (var i = 0; i < maxPoints; i += 1) {
          xValues.push(i / sampleRate);
        }
        state = {
          sampleRate: sampleRate,
          maxPoints: maxPoints,
          gapPoints: msg.gap_points || 8,
          xValues: xValues,
          yValues: Array(maxPoints).fill(null),
          cursorIndex: 0,
          yRange: msg.y_range || [-2000, 2500]
        };
        states.set(msg.plot_id, state);

        window.Plotly.newPlot(
          container,
          [
            {
              x: state.xValues,
              y: state.yValues,
              mode: "lines",
              type: "scattergl",
              name: msg.title || "ECG",
              line: {
                color: msg.line_color || "#64b5f6",
                width: msg.line_width || 2
              },
              hoverinfo: "skip"
            },
            {
              x: [0, 0],
              y: state.yRange,
              mode: "lines",
              type: "scattergl",
              name: "Cursor",
              line: {
                color: msg.cursor_color || "#f5f5f5",
                width: 1
              },
              hoverinfo: "skip",
              showlegend: false
            }
          ],
          {
            template: msg.template || "plotly_dark",
            margin: { l: 20, r: 20, t: 20, b: 20 },
            showlegend: false,
            uirevision: "ecg-sweep",
            xaxis: {
              title: msg.x_title || "Seconds",
              range: [0, state.xValues[state.xValues.length - 1] || 1],
              fixedrange: true
            },
            yaxis: {
              title: msg.y_title || "uV",
              range: state.yRange,
              fixedrange: true
            }
          },
          {
            displayModeBar: false,
            responsive: true
          }
        );
      }

      if (!msg.samples || !msg.samples.length) {
        return;
      }

      for (var sampleIndex = 0; sampleIndex < msg.samples.length; sampleIndex += 1) {
        state.yValues[state.cursorIndex] = msg.samples[sampleIndex];
        for (var gapOffset = 1; gapOffset <= state.gapPoints; gapOffset += 1) {
          state.yValues[(state.cursorIndex + gapOffset) % state.maxPoints] = null;
        }
        state.cursorIndex = (state.cursorIndex + 1) % state.maxPoints;
      }

      var cursorX = state.xValues[state.cursorIndex] || 0;
      window.Plotly.restyle(
        container,
        {
          x: [state.xValues, [cursorX, cursorX]],
          y: [state.yValues, state.yRange]
        },
        [0, 1]
      );
    });
  }

  ensureHandler();
})();
</script>
"""


@dataclass
class SweepFramePlayer(Generic[T]):
    sample_rate_hz: float
    fps: float = ECG_SWEEP_FPS
    window_seconds: float = ECG_SWEEP_WINDOW_SECONDS
    idle_reset_s: float = 0.25
    _pending: deque[T] = field(default_factory=deque, init=False)
    _carry: float = field(default=0.0, init=False)
    _last_total: int = field(default=0, init=False)
    _last_tick: float | None = field(default=None, init=False)

    @property
    def max_points(self) -> int:
        return max(1, int(round(self.sample_rate_hz * self.window_seconds)))

    @property
    def frame_samples(self) -> float:
        return self.sample_rate_hz / self.fps

    def reset(self) -> None:
        self._pending.clear()
        self._carry = 0.0
        self._last_total = 0
        self._last_tick = None

    def next_frame(
        self,
        source: Sequence[T],
        total_count: int,
        *,
        sample_rate_hz: float | None = None,
        force_reset: bool = False,
    ) -> dict[str, object] | None:
        if (
            sample_rate_hz is not None
            and isinstance(sample_rate_hz, (int, float))
            and not isinstance(sample_rate_hz, bool)
            and sample_rate_hz > 0
            and float(sample_rate_hz) != self.sample_rate_hz
        ):
            self.sample_rate_hz = float(sample_rate_hz)
            force_reset = True

        if total_count < self._last_total:
            force_reset = True

        source_list = list(source)
        delta = max(0, total_count - self._last_total)
        if delta:
            self._pending.extend(source_list[-min(delta, len(source_list)) :])
            self._last_total = total_count

        now = monotonic()
        if self._last_tick is None:
            self._last_tick = now
            force_reset = True

        elapsed = max(0.0, now - self._last_tick) if self._last_tick is not None else 0.0
        self._last_tick = now

        if elapsed >= self.idle_reset_s:
            force_reset = True

        if force_reset:
            self._pending.clear()
            self._carry = 0.0
            tail = source_list[-self.max_points :]
            self._last_total = total_count
            return {"op": "reset", "samples": tail}

        if len(self._pending) > self.max_points:
            self._pending.clear()
            self._carry = 0.0
            tail = source_list[-self.max_points :]
            return {"op": "reset", "samples": tail}

        if not self._pending:
            return None

        due = self.frame_samples + self._carry
        emit_count = int(due)
        self._carry = due - emit_count
        if emit_count <= 0:
            emit_count = 1

        emit_count = min(emit_count, len(self._pending))
        samples = [self._pending.popleft() for _ in range(emit_count)]
        if not samples:
            return None
        return {"op": "append", "samples": samples}


def build_ecg_sweep_message(
    plot_id: str,
    frame: dict[str, object],
    *,
    sample_rate_hz: int,
    title: str = "ECG",
    template: str = "plotly_dark",
    x_title: str = "Seconds",
    y_title: str = "uV",
    window_seconds: float = ECG_SWEEP_WINDOW_SECONDS,
    gap_points: int = ECG_SWEEP_GAP_POINTS,
    line_color: str = "#64b5f6",
    cursor_color: str = "#f5f5f5",
    line_width: int = 2,
    y_range: tuple[float, float] = ECG_SWEEP_Y_RANGE,
) -> dict[str, object]:
    max_points = max(1, int(round(sample_rate_hz * window_seconds)))
    return {
        "plot_id": plot_id,
        "op": frame["op"],
        "samples": frame["samples"],
        "sample_rate_hz": sample_rate_hz,
        "max_points": max_points,
        "gap_points": gap_points,
        "title": title,
        "template": template,
        "x_title": x_title,
        "y_title": y_title,
        "line_color": line_color,
        "cursor_color": cursor_color,
        "line_width": line_width,
        "y_range": [float(y_range[0]), float(y_range[1])],
    }
