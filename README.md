# Pi-Pulse

Real-time monitoring for Raspberry Pi nodes, SEN66 environmental sensors, and Polar H10 straps.

The repo has two main runtime parts:

- `app/`: the Shiny for Python dashboard
- `rpi4/`: Raspberry Pi sensor services that publish SSE streams

## Components

- System metrics dashboard for one or more Pi nodes
- SEN66 dashboard for temperature, humidity, CO2, VOC, NOx, PM mass, and PM number concentration
- H10 dashboard for heart rate, RR intervals, ECG, and acceleration
- Multi-H10 support per Pi node
- SSE-based ingestion throughout

## Architecture

Pi-Pulse is split by responsibility:

- `rpi4/` acquires sensor data and exposes it over FastAPI SSE endpoints
- `app/` consumes those SSE streams, holds short in-memory histories, and renders the dashboard

High-level flow:

1. Each Raspberry Pi node runs one or more services from `rpi4/`.
2. Those services publish JSON over SSE:
   - pulse on `8001`
   - SEN66 on `8002`
   - H10 on `8003`
3. The dashboard loads [app/config.yaml](app/config.yaml) and opens one SSE consumer per configured upstream stream.
4. The app normalizes incoming data into bounded reactive state and short FIFO histories.
5. The UI renders cards and charts from that state.
6. ECG is the special case: the app forwards raw ECG chunks to the browser, and the browser draws the sweep client-side with Plotly.

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
├── rpi4/
│   ├── README.md
│   ├── h10.py
│   ├── h10_protocol.py
│   ├── pulse.py
│   ├── sen66.py
│   ├── sse.py
│   ├── *.service
│   └── tests/
├── environment.yml
└── README.md
```

## Documentation

- [app/README.md](app/README.md): dashboard config, runtime, and tests
- [rpi4/README.md](rpi4/README.md): Raspberry Pi setup, permissions, H10 config, and systemd install

## Install

```bash
conda env create -f environment.yml
conda activate pi-pulse
```

## Configuration

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

## Runtime Model

`app/config.yaml` is node-centric. The main selector works at the node level, and the H10 tab adds an H10-specific selector when a node has multiple straps.

On the app side:

- [app/streams/consumer.py](app/streams/consumer.py) manages SSE reconnect/backoff
- [app/server.py](app/server.py) owns normalization and bounded in-memory histories
- [app/layout.py](app/layout.py) defines the page structure and includes JS/CSS assets
- [app/renders/](app/renders) contains sensor-specific render logic
- [app/www/ecg-sweep.js](app/www/ecg-sweep.js) owns ECG sweep buffering and display timing in the browser

On the Pi side:

- [rpi4/pulse.py](rpi4/pulse.py) exposes system metrics
- [rpi4/sen66.py](rpi4/sen66.py) exposes environmental metrics
- [rpi4/h10.py](rpi4/h10.py) exposes multi-H10 HR, ECG, and ACC endpoints

All Pi-side services publish JSON over Server-Sent Events. The expected payload shapes are documented in [app/README.md](app/README.md).

## Run

Dashboard:

```bash
python -m app.pi_pulse
```

This starts the Shiny app on `127.0.0.1:8009`.

Pi-side services are documented in [rpi4/README.md](rpi4/README.md).

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

Pi-side tests are in `rpi4/tests` and can be run with:

```bash
pytest rpi4/tests
```
