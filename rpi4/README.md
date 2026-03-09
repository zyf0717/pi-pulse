# Raspberry Pi Services

`rpi4/` contains the Pi-side workers that read local sensors and push payloads to the relay on the dashboard host.

Workers:

- `pulse.py`: Pi health metrics worker
- `sen66.py`: SEN66 environmental data worker
- `h10.py`: Polar H10 BLE worker

The app then consumes relay endpoints through [app/config.yaml](../app/config.yaml).

## Prerequisites

- Raspberry Pi OS with Python and Conda available
- repo checked out on the Pi
- the `pi-pulse` environment created from the repo root:

```bash
conda env create -f environment.yml
conda activate pi-pulse
```

- for SEN66: I2C enabled and the service user in group `i2c`
- for H10: Bluetooth enabled and the service user in group `bluetooth`

Example group setup:

```bash
sudo usermod -aG i2c "$USER"
sudo usermod -aG bluetooth "$USER"
```

Log out and back in after changing groups.

## Configure H10 Devices

H10 straps are configured in a local untracked file:

- `rpi4/h10_addresses.yaml` on the Pi
- `rpi4/h10_addresses.example.yaml` as the checked-in template

Example local file:

```yaml
6FFF5628: "AA:BB:CC:DD:EE:01"
EA78562C: "AA:BB:CC:DD:EE:02"
```

Rules:

- key: stable `device_id` used in the relay routes
- value: BLE MAC address for that strap
- one Pi can push multiple H10 straps
- keep the real `h10_addresses.yaml` out of version control

## Configure Relay Push Target

Workers push to the relay host with:

- `PI_PULSE_RELAY_URL`
- optional `PI_PULSE_NODE_ID`

Defaults:

```bash
PI_PULSE_RELAY_URL=http://192.168.121.1:8010
```

`pulse.py` and `sen66.py` derive the node id from the local Ethernet IP used to reach the relay. Set `PI_PULSE_NODE_ID` explicitly if that heuristic is not appropriate.

## Run Locally

From `rpi4/`:

```bash
conda activate pi-pulse
cd rpi4
python pulse.py
python sen66.py
python h10.py
```

These workers do not expose HTTP routes themselves. They push into the relay:

- `POST /ingest/pulse/{node_id}/stream`
- `POST /ingest/sen66/{node_id}/stream`
- `POST /ingest/sen66/{node_id}/nc-stream`
- `POST /ingest/h10/{device_id}/stream`
- `POST /ingest/h10/{device_id}/ecg-stream`
- `POST /ingest/h10/{device_id}/acc-stream`

## Expected Output

Each worker pushes the following JSON payloads to the relay.

Examples:

`pulse.py`:

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

`sen66.py` main payload:

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

`sen66.py` number-concentration payload:

```json
{
  "nc_pm0_5_pcm3": 1200.0,
  "nc_pm1_0_pcm3": 950.0,
  "nc_pm2_5_pcm3": 100.0,
  "nc_pm4_0_pcm3": 25.0,
  "nc_pm10_0_pcm3": 5.0
}
```

`h10.py` HR payload:

```json
{
  "bpm": 72,
  "rr_ms": [824, 840]
}
```

`h10.py` ECG payload:

```json
{
  "samples_uv": [10, 12, 8, -4],
  "sample_rate_hz": 130
}
```

`h10.py` ACC payload:

```json
{
  "samples_mg": [
    {"x_mg": -10, "y_mg": 5, "z_mg": 998}
  ],
  "sample_rate_hz": 200
}
```

## Install As Services

The repo includes systemd unit templates:

- [pulse.service](pulse.service)
- [sen66.service](sen66.service)
- [h10.service](h10.service)

Install them with [services.sh](services.sh):

```bash
conda activate pi-pulse
sudo -E ./rpi4/services.sh install
```

Common commands:

```bash
sudo -E ./rpi4/services.sh install pulse sen66 h10
sudo -E ./rpi4/services.sh restart
./rpi4/services.sh status
sudo -E ./rpi4/services.sh remove h10
```

`services.sh` substitutes these values into the unit templates at install time:

- `SERVICE_USER`
- `WORKING_DIR`
- `PYTHON_BIN`

Use `sudo -E` so the active `CONDA_PREFIX` is preserved and the correct `python` is installed into the unit.

## Dashboard Wiring

The dashboard is node-centric. Each top-level key in [app/config.yaml](../app/config.yaml) is one Pi node, for example:

```yaml
devices:
  "11":
    pulse:
      stream: http://127.0.0.1:8010/pulse/11/stream
    sen66:
      stream: http://127.0.0.1:8010/sen66/11/stream
      nc-stream: http://127.0.0.1:8010/sen66/11/nc-stream
    h10:
      "6FFF5628":
        stream: http://127.0.0.1:8010/h10/6FFF5628/stream
        ecg-stream: http://127.0.0.1:8010/h10/6FFF5628/ecg-stream
        acc-stream: http://127.0.0.1:8010/h10/6FFF5628/acc-stream
```

One node can have:

- one `pulse`
- one `sen66`
- multiple `h10`

## Tests

Run the Pi-side tests from the repo root:

```bash
pytest rpi4/tests
```
