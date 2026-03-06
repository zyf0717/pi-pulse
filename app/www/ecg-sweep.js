(function () {
  var states = new Map();

  function compactPending(state) {
    if (
      state.pendingIndex > 1024 &&
      state.pendingIndex >= state.pendingSamples.length / 2
    ) {
      state.pendingSamples = state.pendingSamples.slice(state.pendingIndex);
      state.pendingIndex = 0;
    }
  }

  function applySweepGap(state) {
    for (var gapOffset = 0; gapOffset < state.gapPoints; gapOffset += 1) {
      state.yValues[(state.cursorIndex + gapOffset) % state.maxPoints] = null;
    }
  }

  function drawCurrentState(container, state) {
    var latestIndex = (state.cursorIndex - 1 + state.maxPoints) % state.maxPoints;
    var latestX = state.xValues[latestIndex] || 0;
    var latestY = state.yValues[latestIndex];
    var markerX = latestY == null ? [] : [latestX];
    var markerY = latestY == null ? [] : [latestY];

    window.Plotly.restyle(
      container,
      {
        x: [state.xValues, markerX],
        y: [state.yValues, markerY],
      },
      [0, 1]
    );
  }

  function ensureHandler() {
    if (!window.Shiny || !window.Plotly) {
      setTimeout(ensureHandler, 50);
      return;
    }

    function templateLayout(templateConfig) {
      if (!templateConfig || typeof templateConfig !== "object") {
        return {};
      }
      return templateConfig.layout && typeof templateConfig.layout === "object"
        ? templateConfig.layout
        : {};
    }

    function themeColorway(templateConfig) {
      var layout = templateLayout(templateConfig);
      return Array.isArray(layout.colorway) ? layout.colorway : [];
    }

    window.Shiny.addCustomMessageHandler("ecg-sweep", function (msg) {
      var container = document.getElementById(msg.plot_id);
      if (!container || !window.Plotly) {
        return;
      }

      if (msg.op === "clear") {
        var previousState = states.get(msg.plot_id);
        if (previousState && previousState.timerId !== null) {
          window.clearInterval(previousState.timerId);
        }
        window.Plotly.purge(container);
        container.replaceChildren();
        states.delete(msg.plot_id);
        return;
      }

      var state = states.get(msg.plot_id);
      var shouldReset = msg.op === "reset" || !state;

      if (shouldReset) {
        if (state && state.timerId !== null) {
          window.clearInterval(state.timerId);
        }

        var templateConfig = msg.template_config || msg.template || "plotly_dark";
        var colorway = themeColorway(msg.template_config);
        var lineColor = msg.line_color || colorway[0] || "#636efa";
        var cursorColor = msg.cursor_color || lineColor;
        var maxPoints = msg.max_points;
        var sampleRate = msg.sample_rate_hz;
        var fps = msg.fps || 30;
        var xValues = [];

        for (var i = 0; i < maxPoints; i += 1) {
          xValues.push(i / sampleRate);
        }

        state = {
          sampleRate: sampleRate,
          fps: fps,
          frameSamples: sampleRate / fps,
          maxPoints: maxPoints,
          maxPendingPoints: msg.max_pending_points || maxPoints * 2,
          gapPoints: msg.gap_points || 8,
          xValues: xValues,
          yValues: Array(maxPoints).fill(null),
          cursorIndex: 0,
          yRange: msg.y_range || [-2000, 2500],
          pendingSamples: [],
          pendingIndex: 0,
          carry: 0.0,
          timerId: null,
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
                color: lineColor,
                width: msg.line_width || 2,
              },
              hoverinfo: "skip",
            },
            {
              x: [],
              y: [],
              mode: "markers",
              type: "scattergl",
              name: "Latest",
              marker: {
                color: cursorColor,
                size: 8,
              },
              hoverinfo: "skip",
              showlegend: false,
            },
          ],
          {
            template: templateConfig,
            margin: { l: 64, r: 20, t: 20, b: 56 },
            showlegend: false,
            uirevision: "ecg-sweep",
            xaxis: {
              range: [0, state.xValues[state.xValues.length - 1] || 1],
              fixedrange: true,
              automargin: true,
            },
            yaxis: {
              title: {
                text: msg.y_title || "Amplitude (\u00b5V)",
                standoff: 12,
              },
              range: state.yRange,
              fixedrange: true,
              automargin: true,
            },
          },
          {
            displayModeBar: false,
            responsive: true,
          }
        );

        var initialSamples = Array.isArray(msg.samples) ? msg.samples : [];
        var startIndex = Math.max(0, initialSamples.length - state.maxPoints);

        for (
          var displayIndex = startIndex;
          displayIndex < initialSamples.length;
          displayIndex += 1
        ) {
          state.yValues[state.cursorIndex] = initialSamples[displayIndex];
          state.cursorIndex = (state.cursorIndex + 1) % state.maxPoints;
        }

        applySweepGap(state);
        drawCurrentState(container, state);

        state.timerId = window.setInterval(function () {
          var pendingCount = state.pendingSamples.length - state.pendingIndex;
          if (pendingCount <= 0) {
            return;
          }

          var due = state.frameSamples + state.carry;
          var emitCount = Math.floor(due);
          state.carry = due - emitCount;
          if (emitCount <= 0) {
            emitCount = 1;
          }
          if (emitCount > pendingCount) {
            emitCount = pendingCount;
          }

          for (var sampleOffset = 0; sampleOffset < emitCount; sampleOffset += 1) {
            state.yValues[state.cursorIndex] =
              state.pendingSamples[state.pendingIndex];
            state.pendingIndex += 1;
            state.cursorIndex = (state.cursorIndex + 1) % state.maxPoints;
            applySweepGap(state);
          }

          compactPending(state);
          drawCurrentState(container, state);
        }, 1000 / state.fps);
        return;
      }

      if (!msg.samples || !msg.samples.length) {
        return;
      }

      for (var sampleIndex = 0; sampleIndex < msg.samples.length; sampleIndex += 1) {
        state.pendingSamples.push(msg.samples[sampleIndex]);
      }

      var pendingCount = state.pendingSamples.length - state.pendingIndex;
      if (pendingCount > state.maxPendingPoints) {
        state.pendingIndex = state.pendingSamples.length - state.maxPendingPoints;
      }
      compactPending(state);
    });
  }

  ensureHandler();
})();
