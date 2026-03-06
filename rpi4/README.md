# Raspberry Pi Services

`rpi4/` contains the Pi-side FastAPI services that publish Server-Sent Events for the dashboard.

Services:

- `pulse.py`: Pi health metrics on port `8001`
- `sen66.py`: SEN66 environmental data on port `8002`
- `h10.py`: Polar H10 BLE data on port `8003`

The dashboard consumes these endpoints through [app/config.yaml](../app/config.yaml).

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

H10 straps are configured in [h10_protocol.py](h10_protocol.py):

```python
H10_ADDRESS: dict[str, str] = {
    "6FFF5628": "A0:9E:1A:6F:FF:56",
}
```

Rules:

- key: stable `device_id` used in the HTTP routes
- value: BLE MAC address for that strap
- one Pi can expose multiple H10 straps

Endpoints per configured H10:

- `/h10/{device_id}/health`
- `/h10/{device_id}/stream`
- `/h10/{device_id}/ecg-stream`
- `/h10/{device_id}/acc-stream`

## Run Locally

From `rpi4/`:

```bash
conda activate pi-pulse
cd rpi4
uvicorn pulse:app --host 0.0.0.0 --port 8001
uvicorn sen66:app --host 0.0.0.0 --port 8002
uvicorn h10:app --host 0.0.0.0 --port 8003
```

Useful endpoints:

- pulse:
  - `GET /health`
  - `GET /stream`
- sen66:
  - `GET /health`
  - `GET /stream`
  - `GET /nc-stream`
- h10:
  - `GET /h10/{device_id}/health`
  - `GET /h10/{device_id}/stream`
  - `GET /h10/{device_id}/ecg-stream`
  - `GET /h10/{device_id}/acc-stream`

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
- `UVICORN_BIN`

Use `sudo -E` so the active `CONDA_PREFIX` is preserved and the correct `uvicorn` is installed into the unit.

## Dashboard Wiring

The dashboard is node-centric. Each top-level key in [app/config.yaml](../app/config.yaml) is one Pi node, for example:

```yaml
devices:
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

One node can have:

- one `pulse`
- one `sen66`
- multiple `h10`

## Tests

Run the Pi-side tests from the repo root:

```bash
pytest rpi4/tests
```
