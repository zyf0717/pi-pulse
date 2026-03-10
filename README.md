# Pi-Pulse

Real-time monitoring for Raspberry Pi nodes, SEN66 environmental sensors, and Polar H10 straps.

The repo has three main runtime parts:

- `app/`: the Shiny for Python dashboard
- `relay/`: the local push-to-pull relay on the dashboard host
- `rpi4/`: Raspberry Pi sensor workers that push sensor payloads to the relay
- `shared/`: the stream contract shared by all three runtime parts

## Components

- System metrics dashboard for one or more Pi nodes
- SEN66 dashboard for temperature, humidity, CO2, VOC, NOx, PM mass, and PM number concentration
- H10 dashboard for heart rate, RR intervals, ECG, and acceleration
- Multi-H10 support per Pi node
- relay-backed SSE ingestion throughout

## Architecture

Pi-Pulse is split by responsibility:

- `rpi4/` acquires sensor data and pushes JSON payloads upstream to the relay
- `relay/` accepts Pi pushes and exposes app-compatible SSE pull endpoints
- `app/` consumes those SSE streams from the relay, holds short in-memory histories, and renders the dashboard
- `shared/streams.py` defines the canonical families, channels, route segments, and config fields

High-level flow:

1. Each Raspberry Pi node runs one or more workers from `rpi4/`.
2. Those workers push JSON payloads to the relay host on `:8010`.
3. The relay exposes app-compatible GET SSE endpoints on `127.0.0.1:8010`.
4. The dashboard loads [app/config.yaml](app/config.yaml) and opens one SSE consumer per configured relay stream.
5. The app normalizes incoming data into bounded reactive state and short FIFO histories.
6. The UI renders cards and charts from that state.
7. ECG is the special case: the app forwards raw ECG chunks to the browser, and the browser draws the sweep client-side with Plotly.

## Shared Stream Contract

Route, path, and config naming now come from [shared/streams.py](shared/streams.py).

The current registry defines:

- systems: `pulse`, `sen66`, `h10`, `gps`
- devices: Pi node IDs such as `10` or `11`
- instances: `main` for singleton systems, or a concrete H10 strap ID
- streams: `default`, `number_concentration`, `ecg`, `acc`
- standardized route order: `device/system/instance/stream`

That contract is used by:

- `rpi4/` to build relay ingest paths
- `relay/` to generate POST and GET routes
- `app/` to validate and normalize configured stream URLs

## Repo Layout

```text
.
├── app/
│   ├── README.md
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
├── relay/
│   ├── server.py
│   ├── config.py
│   ├── config.yaml
│   └── tests/
├── rpi4/
│   ├── README.md
│   ├── h10.py
│   ├── h10_protocol.py
│   ├── pulse.py
│   ├── sen66.py
│   ├── sse.py
│   ├── *.service
│   └── tests/
├── shared/
│   ├── __init__.py
│   └── streams.py
├── environment.yml
└── README.md
```

## Documentation

- [app/README.md](app/README.md): dashboard config, runtime, and tests
- [rpi4/README.md](rpi4/README.md): Raspberry Pi setup, permissions, relay push config, local H10 config, and systemd install

## Install

```bash
conda env create -f environment.yml
conda activate pi-pulse
```

## Configuration

Dashboard config lives in [app/config.yaml](app/config.yaml).

Current shape:

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

- each top-level key is one node, such as `"10"` or `"11"` or `"pixel-7"`
- relay URIs are standardized as `/{device_id}/{system}/{instance}/{stream}` for SSE and `/ingest/{device_id}/{system}/{instance}/{stream}` for ingest
- singleton systems use `main` as the instance segment
- `h10` uses the strap ID as the instance segment, so multiple H10 straps can hang off one node
- a node can have one `pulse`, one `sen66`, one `gps`, and multiple `h10` instances
- the app derives URLs from `relay_base_url` and the shared stream contract instead of storing full URLs in config
- the dashboard device selector works at the node level
- if a node has multiple H10 straps, the H10 tab shows an additional instance selector
- stream names come from [shared/streams.py](shared/streams.py)

## Runtime Model

`app/config.yaml` is node-centric. The main selector works at the node level, and the H10 tab adds an H10-specific selector when a node has multiple straps.

On the app side:

- [app/streams/consumer.py](app/streams/consumer.py) manages SSE reconnect/backoff
- [app/server.py](app/server.py) owns normalization and bounded in-memory histories
- [app/layout.py](app/layout.py) defines the page structure and includes JS/CSS assets
- [app/renders/](app/renders) contains sensor-specific render logic
- [app/www/ecg-sweep.js](app/www/ecg-sweep.js) owns ECG sweep buffering and display timing in the browser

On the Pi side:

- [rpi4/pulse.py](rpi4/pulse.py) pushes system metrics
- [rpi4/sen66.py](rpi4/sen66.py) pushes environmental metrics
- [rpi4/h10.py](rpi4/h10.py) pushes multi-H10 HR, ECG, and ACC payloads

The relay converts those pushes back into GET SSE endpoints from the shared registry. Expected payload shapes are documented in [app/README.md](app/README.md).

## Run

Dashboard:

```bash
python -m relay.server
python -m app.pi_pulse
```

This starts the relay on `127.0.0.1:8010` and the Shiny app on `127.0.0.1:8009`.

Pi-side services are documented in [rpi4/README.md](rpi4/README.md).

## Tests

Run the full repo test suite:

```bash
pytest
```
