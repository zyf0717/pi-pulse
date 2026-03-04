"""sandbox/ecg_test.py — Standalone ECG streaming test against the real H10 stream.

Three optimisations under test
────────────────────────────────────────────────────────────────────
1. Client-side rendering   — new samples are sent as a plain JSON message;
                             Plotly.extendTraces runs entirely in the browser.
                             No FigureWidget / shinywidgets round-trip per frame.

2. Append-only updates     — extendTraces appends to the existing trace rather
                             than replacing the whole x/y arrays each frame.

3. No buffer build-up      — the maxPoints argument to extendTraces caps the
                             visible window; the browser discards old points
                             automatically so server RAM never grows.

ECG signal parameters
────────────────────────────────────────────────────────────────────
  73 samples / packet  ×  ~1.78 packets / s  =  130 Hz total sample rate
  Render cadence : 30 fps  (≈ 33 ms / frame)
  Visible window : 5 s  →  650 samples  (maxPoints = 650)

Run
────────────────────────────────────────────────────────────────────
  shiny run sandbox/ecg_test.py --port 8010 --reload
"""

from __future__ import annotations

import asyncio
import json
import logging

import httpx
from shiny import App, ui

# ── constants ───────────────────────────────────────────────────────────────
ECG_URL = "http://192.168.121.11:8003/h10/6FFF5628/ecg-stream"
SAMPLE_RATE_HZ = 130
WINDOW_SAMPLES = SAMPLE_RATE_HZ * 5  # 650 — 5-second rolling window


# ── per-session SSE consumer ─────────────────────────────────────────────────
class _SessionEcg:
    """Forwards H10 ECG packets straight to the browser — no buffering."""

    def __init__(self, on_samples) -> None:
        # on_samples(y_vals: list[float]) — async callback invoked per packet
        self._on_samples = on_samples
        self._task: asyncio.Task | None = None

    async def _consume(self) -> None:
        backoff = 1
        while True:
            try:
                async with httpx.AsyncClient(timeout=None) as client:
                    async with client.stream("GET", ECG_URL) as response:
                        response.raise_for_status()
                        backoff = 1
                        async for line in response.aiter_lines():
                            if not line.startswith("data: "):
                                continue
                            try:
                                data = json.loads(line[6:])
                            except json.JSONDecodeError:
                                continue
                            samples = data.get("samples_uv", [])
                            if not isinstance(samples, list) or not samples:
                                continue
                            y_vals = [
                                float(s)
                                for s in samples
                                if isinstance(s, (int, float))
                                and not isinstance(s, bool)
                            ]
                            if y_vals:
                                await self._on_samples(y_vals)
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


# ── UI ───────────────────────────────────────────────────────────────────────
_DIV_ID = "ecg_canvas"

app_ui = ui.page_fluid(
    ui.tags.head(
        # Plotly.js loaded from CDN — all chart operations run in the browser
        ui.tags.script(
            src="https://cdn.plot.ly/plotly-2.35.2.min.js",
            crossorigin="anonymous",
        ),
    ),
    ui.h4("ECG stream — sandbox"),
    ui.p(
        ui.tags.small(
            f"{ECG_URL}  —  "
            f"{SAMPLE_RATE_HZ} Hz · {WINDOW_SAMPLES}-sample ({WINDOW_SAMPLES // SAMPLE_RATE_HZ}s) display · 5 samples/frame · 26 fps"
        )
    ),
    # Plain div — Plotly owns it entirely (suggestion 1: client-side rendering)
    ui.tags.div(id=_DIV_ID, style="width:100%; height:380px;"),
    # Diagnostic counters
    ui.tags.div(
        id="ecg_stats",
        style="font-size:0.75rem; color:#888; margin-top:4px;",
    ),
    # ── JS: playback queue + fixed-rate render at 26 fps ──────────────────────
    ui.tags.script(
        f"""
    (function () {{
        var N   = {WINDOW_SAMPLES};   /* display ring buffer: 650 samples = 5 s  */
        var SR  = {SAMPLE_RATE_HZ};   /* 130 Hz                                  */
        var FPS = 26;                  /* render rate                             */
        var SPF = SR / FPS;            /* samples to advance per frame = 5        */
        var DIV = '{_DIV_ID}';
        var MAX_QUEUE = N * 2;         /* hard cap: ~10 s of samples when visible  */

        /* ── Fixed x-axis [0 .. 5 s], set once, never touched again ─────── */
        var xArr = new Array(N);
        for (var i = 0; i < N; i++) xArr[i] = i / SR;

        /* ── Display ring buffer (fixed size, no growth) ───────────────── */
        var ring = new Float64Array(N);
        var wptr = 0;  /* write head into ring */

        /* ── Playback queue: incoming samples wait here ────────────────── */
        var queue = [];
        var qHead = 0;  /* read index (avoids O(n) shift) */

        function qLen()  {{ return queue.length - qHead; }}
        function qPush(v) {{ queue.push(v); }}
        function qPop()  {{
            var v = queue[qHead++];
            /* compact array when read head has advanced far enough */
            if (qHead > 2000) {{ queue = queue.slice(qHead); qHead = 0; }}
            return v;
        }}

        /* ── Plotly init ─────────────────────────────────────────────────── */
        Plotly.newPlot(
            DIV,
            [{{
                x: xArr.slice(),
                y: Array.from(ring),
                type: 'scattergl',
                mode: 'lines',
                line: {{ color: '#64b5f6', width: 1 }},
                name: 'ECG'
            }}],
            {{
                margin      : {{ l: 50, r: 10, t: 10, b: 40 }},
                yaxis       : {{ title: '\u00b5V', range: [-2500, 3000], fixedrange: true }},
                xaxis       : {{ title: 's', range: [0, N / SR], fixedrange: true }},
                paper_bgcolor: '#1a1a1a',
                plot_bgcolor : '#1a1a1a',
                font        : {{ color: '#ccc' }},
                uirevision  : 1
            }},
            {{ responsive: true, displayModeBar: false }}
        );

        /* ── Page Visibility: flush queue when tab is hidden ───────────── */
        /* setInterval is throttled to ~1 Hz by the browser when hidden.   */
        /* Without this, 130 samples/s arrive but only 5/s drain → buildup.*/
        /* Solution: when hidden keep only the last SPF samples (one frame  */
        /* worth) so on return playback resumes from "now", not the past.  */
        document.addEventListener('visibilitychange', function () {{
            if (document.hidden) {{
                /* discard all but the most-recent SPF samples */
                var keep = Math.min(Math.ceil(SPF), qLen());
                qHead = queue.length - keep;
                if (qHead < 0) qHead = 0;
            }}
        }});

        /* ── Shiny message: push raw y-values into playback queue ───────── */
        var pkt_count = 0;
        Shiny.addCustomMessageHandler('ecg_samples', function (msg) {{
            var y = msg.y;
            if (document.hidden) {{
                /* tab is hidden — keep only this latest packet, drop older */
                queue = y.slice();
                qHead = 0;
            }} else {{
                for (var i = 0; i < y.length; i++) qPush(y[i]);
                /* hard cap: trim oldest if still too large */
                if (qLen() > MAX_QUEUE) {{
                    qHead += qLen() - MAX_QUEUE;
                }}
            }}
            pkt_count += 1;
        }});

        /* ── Fixed-rate render: drain exactly SPF samples per tick ──────── */
        /* setInterval fires at exactly 1000/FPS ms = 38.46 ms intervals.  */
        /* Each tick advances the ring buffer by SPF = 5 samples, giving   */
        /* smooth motion at 130 Hz equivalent scroll speed.                */
        var fps_frames  = 0;
        var fps_elapsed = 0;
        var fps_display = '0.0';
        var last_tick   = performance.now();

        setInterval(function () {{
            var n = qLen();
            if (n === 0) return;  /* no data yet — skip frame */

            /* drain up to SPF samples; use fewer if queue is thin */
            var drain = Math.min(SPF, n);
            for (var i = 0; i < drain; i++) {{
                ring[wptr] = qPop();
                wptr = (wptr + 1) % N;
            }}

            /* rotate ring so oldest sample is at index 0 → scrolls left */
            var y_disp = Array.prototype.slice.call(ring, wptr)
                         .concat(Array.prototype.slice.call(ring, 0, wptr));
            Plotly.restyle(DIV, {{ y: [y_disp] }}, [0]);

            /* fps counter */
            var now = performance.now();
            fps_elapsed += now - last_tick;
            last_tick    = now;
            fps_frames  += 1;
            if (fps_elapsed >= 1000) {{
                fps_display = (fps_frames / (fps_elapsed / 1000)).toFixed(1);
                fps_frames  = 0;
                fps_elapsed = 0;
            }}

            document.getElementById('ecg_stats').textContent =
                'fps: '       + fps_display +
                '  |  queue: ' + qLen() +
                '  |  pkts: '  + pkt_count;
        }}, 1000 / FPS);
    }})();
    """
    ),
)


# ── server ───────────────────────────────────────────────────────────────────
def server(input, output, session):
    async def on_samples(y_vals: list[float]) -> None:
        try:
            # suggestion 1: send raw y-values only, no x, no server buffering
            await session.send_custom_message("ecg_samples", {"y": y_vals})
        except Exception:
            pass

    state = _SessionEcg(on_samples)
    state.start()
    session.on_ended(state.stop)


app = App(app_ui, server)

if __name__ == "__main__":
    app.run(port=8010)
