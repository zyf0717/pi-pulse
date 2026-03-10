# App Dashboard

`app/` contains the Shiny for Python dashboard.

It is responsible for:

- loading the node-centric config from [config.yaml](config.yaml)
- opening SSE connections to the local relay
- maintaining short reactive histories for cards and charts
- rendering the UI, including the client-driven ECG sweep

Pi-side deployment is documented separately in [../rpi4/README.md](../rpi4/README.md).

## Entry Points

- [pi_pulse.py](pi_pulse.py): app entry point, runs Shiny on `127.0.0.1:8009`
- [layout.py](layout.py): UI structure and static asset inclusion
- [server.py](server.py): session-local render registration
- [ingest.py](ingest.py): process-global SSE ingest state, normalization, and startup
- [config.py](config.py): parses [config.yaml](config.yaml) into app-facing settings

The allowed stream keys and route segments are defined centrally in [../shared/streams.py](../shared/streams.py).

## Config Model

The dashboard is node-centric.

Each top-level key in [config.yaml](config.yaml) is one Pi node:

```yaml
relay_base_url: http://127.0.0.1:8010

devices:
  "10":
    pulse: {}

  "11":
    pulse: {}
    sen66: {}
    h10:
      "6FFF5628": {}
```

Rules:

- relay routes follow `/{device_id}/{system}/{instance}/{stream}`
- ingest routes follow `/ingest/{device_id}/{system}/{instance}/{stream}`
- singleton systems use `main` as the instance segment
- one node can have one `pulse`, one `sen66`, one `gps`, and multiple `h10` instances
- the app derives the actual relay URLs from `relay_base_url` plus the shared stream contract
- the main dashboard selector chooses the node
- the H10 tab shows a second selector only when that node has multiple H10 instances
- [config.py](config.py) builds the relay URLs from [../shared/streams.py](../shared/streams.py)

## Run

From the repo root:

```bash
conda activate pi-pulse
python -m app.pi_pulse
```

The app binds to `127.0.0.1:8009`.

## How It Works

Runtime flow:

1. [config.py](config.py) loads [config.yaml](config.yaml), validates configured stream keys against the shared registry, and builds `DEVICES`, `SEN66_DEVICES`, `H10_DEVICES`, and selector metadata.
2. [ingest.py](ingest.py) owns one process-global ingest set and starts one SSE consumer per configured relay stream using [streams/consumer.py](streams/consumer.py).
3. Incoming payloads are normalized and written into small bounded `deque` histories plus `reactive.Value` state shared by all browser sessions in that app process.
4. [server.py](server.py) does not open per-session upstream streams; it only binds the active Shiny session to the shared ingest state and registers renders.
5. Render modules under `renders/` read from that shared state and update cards, charts, and motion views.
6. ECG is handled differently: the app forwards raw ECG chunks to the browser, and the browser paces and draws the sweep client-side.

If the shared ingest task set becomes unhealthy, `ingest.py` invalidates it and recreates the full set on the next startup check instead of trusting a stale `started=True` flag.

## Major Refactors

The current app structure reflects a few deliberate architecture changes:

- Node-centric config:
  `config.yaml` is organized by Pi node, not by sensor type. One node can have one `pulse`, one `sen66`, and multiple `h10` instances under a standardized `device/system/instance/stream` URI model.

- Process-global ingest:
  relay SSE connections are shared per app process. Opening additional browser sessions no longer creates additional upstream streams.

- Client-driven ECG:
  ECG is no longer rendered as repeated Python-side Plotly array replacement. The browser owns the sweep buffer and pacing, and the server only forwards raw ECG chunks.

- Split H10 rendering:
  the H10 render path is separated by concern:
  - [renders/h10.py](renders/h10.py): session render registration and standard H10 charts
  - [renders/h10_motion.py](renders/h10_motion.py): acceleration SVG rendering
  - [renders/h10_ecg_bridge.py](renders/h10_ecg_bridge.py): server-to-browser ECG message bridge
  - [renders/ecg_sweep.py](renders/ecg_sweep.py): ECG sweep message contract

- Extracted frontend assets:
  the main custom browser behaviors live in `app/www/` instead of large inline JS/CSS strings in Python.

## Stream Expectations

All upstream services publish JSON over Server-Sent Events.

Expected payload shapes:

System metrics:

```json
{
  "cpu": 45.2,
  "mem": 62.1,
  "temp": 52.5,
  "cpu_freq_avg_mhz": 1200,
  "net_rx_bps_total": 5242880,
  "net_tx_bps_total": 1048576
}
```

SEN66 main stream:

```json
{
  "temperature_c": 22.5,
  "humidity_rh": 45.3,
  "co2_ppm": 520,
  "voc_index": 35,
  "nox_index": 25,
  "pm1_0_ugm3": 2.1,
  "pm2_5_ugm3": 5.3,
  "pm4_0_ugm3": 8.2,
  "pm10_0_ugm3": 10.5
}
```

SEN66 number-concentration stream:

```json
{
  "nc_pm0_5_pcm3": 1200.0,
  "nc_pm1_0_pcm3": 950.0,
  "nc_pm2_5_pcm3": 100.0,
  "nc_pm4_0_pcm3": 25.0,
  "nc_pm10_0_pcm3": 5.0
}
```

H10 HR stream:

```json
{
  "bpm": 72,
  "rr_ms": [824, 840]
}
```

H10 ECG stream:

```json
{
  "samples_uv": [10, 12, 8, -4],
  "sample_rate_hz": 130
}
```

H10 ACC stream:

```json
{
  "samples_mg": [
    {"x_mg": -10, "y_mg": 5, "z_mg": 998}
  ],
  "sample_rate_hz": 200
}
```

## Frontend Assets

The dashboard includes a small amount of static JS and CSS under `www/`:

- `ecg-sweep.js`: Plotly-based client-side ECG sweep renderer
- `card-click.js`: card click behavior for chart selection
- `keepalive.js`: browser reconnect/keepalive behavior
- `app.css`: small UI styling overrides

These are included from [layout.py](layout.py).

## Tests

Run the app test suite from the repo root:

```bash
pytest app/tests
```

Coverage includes:

- config shaping
- layout structure
- render behavior
- SSE parsing and consumers
- ECG sweep message contract
- static asset presence and basic behavior
