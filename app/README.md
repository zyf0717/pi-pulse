# App Dashboard

`app/` contains the Shiny for Python dashboard.

It is responsible for:

- loading the node-centric config from [config.yaml](config.yaml)
- opening SSE connections to Pi-side services
- maintaining short reactive histories for cards and charts
- rendering the UI, including the client-driven ECG sweep

Pi-side deployment is documented separately in [../rpi4/README.md](../rpi4/README.md).

## Entry Points

- [pi_pulse.py](pi_pulse.py): app entry point, runs Shiny on `127.0.0.1:8009`
- [layout.py](layout.py): UI structure and static asset inclusion
- [server.py](server.py): reactive state, stream consumers, and render registration
- [config.py](config.py): parses [config.yaml](config.yaml) into app-facing settings

## Config Model

The dashboard is node-centric.

Each top-level key in [config.yaml](config.yaml) is one Pi node:

```yaml
devices:
  "10":
    pulse:
      stream: http://192.168.121.10:8001/stream

  "11":
    pulse:
      stream: http://192.168.121.11:8001/stream
    sen66:
      stream: http://192.168.121.11:8002/stream
      nc-stream: http://192.168.121.11:8002/nc-stream
    h10:
      "6FFF5628":
        stream: http://192.168.121.11:8003/h10/6FFF5628/stream
        ecg-stream: http://192.168.121.11:8003/h10/6FFF5628/ecg-stream
        acc-stream: http://192.168.121.11:8003/h10/6FFF5628/acc-stream
```

Rules:

- one node can have one `pulse`
- one node can have one `sen66`
- one node can have multiple `h10`
- the main dashboard selector chooses the node
- the H10 tab shows a second selector only when that node has H10 streams

## Run

From the repo root:

```bash
conda activate pi-pulse
python -m app.pi_pulse
```

The app binds to `127.0.0.1:8009`.

## How It Works

Runtime flow:

1. [config.py](config.py) loads [config.yaml](config.yaml) and builds `DEVICES`, `SEN66_DEVICES`, `H10_DEVICES`, and selector metadata.
2. [server.py](server.py) starts one SSE consumer per configured upstream stream using [streams/consumer.py](streams/consumer.py).
3. Incoming payloads are normalized and written into small bounded `deque` histories plus `reactive.Value` state.
4. Render modules under `renders/` read from that state and update cards, charts, and motion views.
5. ECG is handled differently: the server forwards raw ECG chunks and the browser paces and draws the sweep client-side.

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
  "heart_rate_bpm": 72,
  "rr_intervals_ms": [824, 840]
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
