# Pi-Pulse

Real-time monitoring for Raspberry Pi nodes, SEN66 environmental sensors, and Polar H10 straps.

The repo has two main parts:

- `app/`: the Shiny for Python dashboard
- `rpi4/`: Raspberry Pi sensor services that publish SSE streams

## Components

- System metrics dashboard for one or more Pi nodes
- SEN66 dashboard for temperature, humidity, CO2, VOC, NOx, PM mass, and PM number concentration
- H10 dashboard for heart rate, RR intervals, ECG, and acceleration
- Multi-H10 support per Pi node
- SSE-based ingestion throughout

## Repo Layout

```text
.
├── app/
│   ├── pi_pulse.py
│   ├── config.py
│   ├── config.yaml
│   ├── layout.py
│   ├── server.py
│   ├── sparkline.py
│   ├── renders/
│   ├── streams/
│   ├── www/
│   └── tests/
├── rpi4/
│   ├── h10.py
│   ├── h10_protocol.py
│   └── sse.py
├── environment.yml
└── cron.sh
```

## Install

```bash
conda env create -f environment.yml
conda activate pi-pulse
```

## Dashboard Config

Dashboard config lives in [app/config.yaml](app/config.yaml).

Current shape:

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

- each top-level key is one Pi node, such as `"10"` or `"11"`
- a node can have:
  - one `pulse`
  - one `sen66`
  - multiple `h10` streams
- the dashboard device selector works at the node level
- if a node has multiple H10 straps, the H10 tab shows an additional stream selector

## Run

Dashboard:

```bash
python -m app.pi_pulse
```

This starts the Shiny app on `127.0.0.1:8009`.

H10 service on a Pi:

```bash
python -m rpi4.h10
```

The H10 service exposes one endpoint set per configured strap:

- `/h10/{device_id}/health`
- `/h10/{device_id}/stream`
- `/h10/{device_id}/ecg-stream`
- `/h10/{device_id}/acc-stream`

## Stream Expectations

All upstream services publish Server-Sent Events with JSON payloads.

Examples:

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

## Notes

- The dashboard consumes SSE with reconnect/backoff logic in [app/streams/consumer.py](app/streams/consumer.py).
- ECG rendering is client-driven via Plotly in [app/www/ecg-sweep.js](app/www/ecg-sweep.js).
- Card click behavior is implemented in [app/www/card-click.js](app/www/card-click.js).
- Browser keepalive/reconnect behavior is implemented in [app/www/keepalive.js](app/www/keepalive.js).

## Tests

Run the app test suite:

```bash
pytest app/tests
```

Current app coverage includes:

- config loading and shaping
- layout structure
- render logic
- SSE consumer/parser behavior
- ECG sweep message contract
- static asset presence/behavior checks
