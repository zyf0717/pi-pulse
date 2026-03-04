"""sandbox/ecg_test.py — Standalone ECG streaming test against the real H10 stream.

Architecture
────────────────────────────────────────────────────────────────────
- Python / Plotly   builds the FigureWidget (trace config, axes, theme).
- shinywidgets      renders and owns the chart div; bundles Plotly.js.
- JS               queue + setInterval update loop only; no Plotly init in JS.

Smooth-render design
────────────────────────────────────────────────────────────────────
  SSE packets (73 samples, ~1.78 Hz) → server forwards immediately
  Browser: playback queue absorbs bursts; setInterval drains ≈5 samples/frame
  Result: smooth 26 fps scroll at 130 Hz equivalent speed

Queue safety
────────────────────────────────────────────────────────────────────
  - Visible tab  : hard cap at 2× window; oldest trimmed on each push.
  - Hidden tab   : visibilitychange + per-packet guard keep queue at ≤1 packet.
    (browsers throttle setInterval to ~1 Hz when hidden; without this the
     queue would grow at 125 samples/s and cause catch-up lag on return.)

Run
────────────────────────────────────────────────────────────────────
  shiny run sandbox/ecg_test.py --port 8010 --reload
"""

from __future__ import annotations

import asyncio
import json
import logging

import httpx
import plotly.graph_objects as go
from shiny import App, ui
from shinywidgets import output_widget, render_widget

# ── constants ────────────────────────────────────────────────────────────────
ECG_URL = "http://192.168.121.11:8003/h10/6FFF5628/ecg-stream"
SAMPLE_RATE_HZ = 130
WINDOW_SAMPLES = SAMPLE_RATE_HZ * 5  # 650 — 5-second rolling window
RENDER_FPS = 26  # ≈ 38.5 ms / frame
SPF = SAMPLE_RATE_HZ / RENDER_FPS  # ≈ 5 samples drained per frame
_OUTPUT_ID = "ecg_graph"

# Fixed x-axis values — computed once, passed into each session's FigureWidget.
_x_axis = [i / SAMPLE_RATE_HZ for i in range(WINDOW_SAMPLES)]


# ── per-session SSE consumer ─────────────────────────────────────────────────
class _SessionEcg:
    """Reads the H10 ECG SSE stream and forwards each packet to the browser."""

    def __init__(self, on_samples) -> None:
        self._on_samples = on_samples  # async (y_vals: list[float]) -> None
        self._task: asyncio.Task | None = None

    async def _consume(self) -> None:
        backoff = 1
        while True:
            try:
                async with httpx.AsyncClient(timeout=None) as client:
                    async with client.stream("GET", ECG_URL) as resp:
                        resp.raise_for_status()
                        backoff = 1
                        async for line in resp.aiter_lines():
                            if not line.startswith("data: "):
                                continue
                            try:
                                data = json.loads(line[6:])
                            except json.JSONDecodeError:
                                continue
                            raw = data.get("samples_uv", [])
                            if not isinstance(raw, list) or not raw:
                                continue
                            y = [
                                float(s)
                                for s in raw
                                if isinstance(s, (int, float))
                                and not isinstance(s, bool)
                            ]
                            if y:
                                await self._on_samples(y)
            except asyncio.CancelledError:
                return
            except Exception as exc:
                logging.warning(
                    "ECG stream error (%s: %s); reconnecting in %ds…",
                    type(exc).__name__,
                    exc,
                    backoff,
                )
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 30)

    def start(self) -> None:
        self._task = asyncio.create_task(self._consume())

    def stop(self) -> None:
        if self._task:
            self._task.cancel()


# ── UI ────────────────────────────────────────────────────────────────────────
app_ui = ui.page_fluid(
    ui.h4("ECG stream — sandbox"),
    ui.p(
        ui.tags.small(
            f"{ECG_URL}  —  "
            f"{SAMPLE_RATE_HZ} Hz · {WINDOW_SAMPLES // SAMPLE_RATE_HZ}s window · "
            f"{SPF:.0f} samples/frame · {RENDER_FPS} fps"
        )
    ),
    # shinywidgets renders the FigureWidget (bundles Plotly.js — no CDN needed)
    output_widget(_OUTPUT_ID),
    ui.tags.div(id="ecg_stats", style="font-size:0.75rem; color:#888; margin-top:4px;"),
    # ── JS: queue + setInterval update loop only ─────────────────────────────
    # Python/Plotly owns chart init; JS only handles pacing + Plotly.restyle.
    ui.tags.script(
        f"""
    (function () {{
        var N         = {WINDOW_SAMPLES};
        var SR        = {SAMPLE_RATE_HZ};
        var FPS       = {RENDER_FPS};
        var SPF       = SR / FPS;          /* samples to drain per frame ≈ 5   */
        var MAX_QUEUE = N * 2;             /* hard cap: ~10 s when visible      */
        var OUTPUT_ID = '{_OUTPUT_ID}';

        /* ── Ring buffer (fixed size = N, no growth) ── */
        var ring = new Float64Array(N);
        var wptr = 0;

        /* ── Playback queue (FIFO with compacting read head) ── */
        var queue = [], qHead = 0;
        function qLen()   {{ return queue.length - qHead; }}
        function qPush(v) {{ queue.push(v); }}
        function qPop()   {{
            var v = queue[qHead++];
            if (qHead > 2000) {{ queue = queue.slice(qHead); qHead = 0; }}
            return v;
        }}

        /* ── Wait for shinywidgets to mount the Plotly div ── */
        /* output_widget renders asynchronously; poll until .js-plotly-plot
           is present and fully initialised (_fullLayout set by Plotly).   */
        var plotDiv = null;

        function startRenderLoop() {{
            var fps_frames = 0, fps_elapsed = 0, fps_display = '0.0';
            var last_tick  = performance.now();

            setInterval(function () {{
                var n = qLen();
                if (n === 0) return;

                var drain = Math.min(SPF, n);
                for (var i = 0; i < drain; i++) {{
                    ring[wptr] = qPop();
                    wptr = (wptr + 1) % N;
                }}

                /* rotate ring so index 0 = oldest → left-to-right scroll */
                var y_disp = Array.prototype.slice.call(ring, wptr)
                             .concat(Array.prototype.slice.call(ring, 0, wptr));
                Plotly.restyle(plotDiv, {{ y: [y_disp] }}, [0]);

                var now = performance.now();
                fps_elapsed += now - last_tick;
                last_tick    = now;
                fps_frames  += 1;
                if (fps_elapsed >= 1000) {{
                    fps_display = (fps_frames / (fps_elapsed / 1000)).toFixed(1);
                    fps_frames = fps_elapsed = 0;
                }}
                document.getElementById('ecg_stats').textContent =
                    'fps: ' + fps_display +
                    '  |  queue: ' + qLen() +
                    '  |  pkts: '  + pkt_count;
            }}, 1000 / FPS);
        }}

        function waitForWidget() {{
            var container = document.getElementById(OUTPUT_ID);
            if (container) {{
                var el = container.querySelector('.js-plotly-plot');
                if (el && el._fullLayout) {{ plotDiv = el; startRenderLoop(); return; }}
            }}
            setTimeout(waitForWidget, 100);
        }}
        waitForWidget();

        /* ── Page Visibility guard ── */
        document.addEventListener('visibilitychange', function () {{
            if (document.hidden && qLen() > Math.ceil(SPF)) {{
                qHead = queue.length - Math.ceil(SPF);
            }}
        }});

        /* ── Shiny message handler ── */
        var pkt_count = 0;
        Shiny.addCustomMessageHandler('ecg_samples', function (msg) {{
            if (document.hidden) {{
                queue = msg.y.slice(); qHead = 0;
            }} else {{
                for (var i = 0; i < msg.y.length; i++) qPush(msg.y[i]);
                if (qLen() > MAX_QUEUE) qHead += qLen() - MAX_QUEUE;
            }}
            pkt_count += 1;
        }});
    }})();
    """
    ),
)


# ── server ────────────────────────────────────────────────────────────────────
def server(input, output, session):
    @render_widget
    def ecg_graph():
        # FigureWidget must be created inside an active Shiny session.
        return go.FigureWidget(
            data=[
                go.Scattergl(
                    x=_x_axis,
                    y=[0.0] * WINDOW_SAMPLES,
                    mode="lines",
                    line=dict(color="#64b5f6", width=1),
                    name="ECG (µV)",
                )
            ],
            layout=go.Layout(
                margin=dict(l=50, r=10, t=10, b=40),
                yaxis=dict(title="µV", range=[-2500, 3000], fixedrange=True),
                xaxis=dict(
                    title="s",
                    range=[0, WINDOW_SAMPLES / SAMPLE_RATE_HZ],
                    fixedrange=True,
                ),
                paper_bgcolor="#1a1a1a",
                plot_bgcolor="#1a1a1a",
                font=dict(color="#ccc"),
                height=380,
                uirevision=1,
            ),
        )

    async def on_samples(y_vals: list[float]) -> None:
        try:
            await session.send_custom_message("ecg_samples", {"y": y_vals})
        except Exception:
            pass

    state = _SessionEcg(on_samples)
    state.start()
    session.on_ended(state.stop)


app = App(app_ui, server)

if __name__ == "__main__":
    from shiny import run_app

    run_app(app, port=8010)
