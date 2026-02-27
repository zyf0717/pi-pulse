# Pi-Pulse

A real-time monitoring dashboard for Raspberry Pi systems and environmental sensors, built with Posit Shiny for Python and Plotly.

## Features

- **System Metrics Monitoring**: CPU usage, memory usage, temperature, CPU frequency, and network bandwidth for multiple devices
- **Environmental Sensor Data**: Temperature, humidity, CO₂, VOC, NOx, and PM concentration readings from Sensirion SEN66 sensors
  - Temperature & Humidity (SHTC3 sensor)
  - CO₂ (SCD4x NDIR sensor, 400-5000 ppm accurate range)
  - VOC & NOx indices (SGP4x MOX sensor)
  - Particulate Matter: mass (µg/m³) and number concentration (#/cm³) for PM0.5, PM1.0, PM2.5, PM4.0, PM10.0
- **Real-time Streaming**: Live data updates via Server-Sent Events (SSE) with automatic reconnection
- **Interactive Charts**: Plotly-powered visualizations with zoom, pan, and hover capabilities
  - Dual-axis charts for related metrics (e.g., temperature and humidity)
  - Multi-series charts for PM concentration tracking
- **Sparkline History**: Compact 60-point historical trends with min/max values displayed
- **Tooltip Guidance**: Detailed sensor specifications, accuracy, and operating ranges
- **Multi-device Support**: Monitor multiple Raspberry Pi devices and sensors from a single dashboard
- **Theme Switching**: Light and dark theme options with Shinyswatch (defaults to dark theme)
- **Responsive Design**: Works seamlessly across different screen sizes

## Architecture

```
├── pi_pulse.py          # Main application entry point
├── layout.py            # UI layout and components
├── server.py            # Server logic and reactive state
├── config.py            # Configuration loader
├── config.yaml          # Device stream endpoints
├── sparkline.py         # SVG sparkline rendering utility
├── cron.sh              # Production restart script
├── renders/
│   ├── pulse.py         # Pi-pulse metrics renders
│   └── sen66.py         # SEN66 sensor data renders
└── streams/
    └── consumer.py      # SSE stream consumer with backoff
```

## Requirements

- Python 3.12+
- Shiny for Python
- Plotly
- httpx (for async HTTP streaming)
- PyYAML (for configuration)
- pandas
- shinyswatch (theme support)
- faicons (icon support)
- shinywidgets

## Installation

### Using Conda

1. Clone the repository:
   ```bash
   git clone <repository-url>
   cd pi-pulse
   ```

2. Create the conda environment:
   ```bash
   conda env create -f requirements.yml
   ```

3. Activate the environment:
   ```bash
   conda activate pi-pulse
   ```

## Configuration

Configure your devices in [config.yaml](config.yaml):

```yaml
pi-pulse:
  "10":
    stream: http://192.168.121.10:8001/stream
  "11":
    stream: http://192.168.121.11:8001/stream

sen66:
  "11":
    stream: http://192.168.121.11:8002/stream
    nc-stream: http://192.168.121.11:8002/nc-stream
```

**Parameters:**
- **pi-pulse**: Devices providing system metrics (CPU, memory, temperature, etc.)
  - `stream`: URL to the SSE endpoint providing metrics data
- **sen66**: Devices providing environmental sensor data
  - `stream`: URL to the SSE endpoint for main sensor readings
  - `nc-stream`: URL to the SSE endpoint for number concentration data

Each device is keyed by its last octet of the IP address. The dashboard will label devices as `{key} (192.168.121.{key})`.

## Running

```bash
python pi_pulse.py
```

The application will start on `http://127.0.0.1:8009` with WebSocket ping/pong configured for long-running connections.

## Data Stream Format

Devices must provide Server-Sent Events (SSE) endpoints that send JSON data. Each SSE message should follow the standard format:

```
data: {"key1": value1, "key2": value2, ...}
```

### Pi-Pulse Expected Fields

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

### SEN66 Expected Fields

Main stream:
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

Number concentration stream:
```json
{
  "nc_pm0_5_pcm3": 1200.0,
  "nc_pm1_0_pcm3": 950.0,
  "nc_pm2_5_pcm3": 100.0,
  "nc_pm4_0_pcm3": 25.0,
  "nc_pm10_0_pcm3": 5.0
}
```

## Stream Consumer

The [streams/consumer.py](streams/consumer.py) module handles SSE stream consumption with:
- **Automatic reconnection**: Recovers from connection failures
- **Exponential backoff**: Starts at 1s, doubles up to 30s maximum
- **Reactive integration**: Seamlessly updates Shiny reactive values under lock
- **Error handling**: Logs malformed packets and connection errors
- **Graceful shutdown**: Properly cancels tasks when session ends

## WebSocket Keep-Alive

The dashboard includes a Web Worker-based keepalive mechanism to prevent browser tab throttling:
- Web Worker fires a HEAD request every 20 seconds (runs outside throttled page context)
- WebSocket ping interval: 10 seconds
- WebSocket pong timeout: 300 seconds (5 minutes) to handle backgrounded tabs
- Auto-reload: If WebSocket disconnects, page reloads after 2 seconds

## Dashboard Navigation

1. **Device Selector**: Choose which device to monitor from the sidebar
2. **Tabs**: Switch between System (Pi-Pulse) and SEN66 data
3. **Value Boxes**: Real-time metrics with sparkline trends showing the last 60 data points
4. **Chart Selector**: Choose which metric to visualize in detail
5. **Interactive Charts**:
   - Zoom, pan, and hover for detailed insights
   - Auto-refresh with new data (incremental updates, no flash)
   - Single-series: CPU, Memory, Temperature, CPU Frequency, CO₂
   - Multi-series: Network (Download/Upload), VOC/NOx, PM Mass, PM Number Concentration
   - Dual-axis: Temperature & Humidity
6. **Theme Picker**: Toggle between Shinyswatch themes (defaults to Darkly)
7. **Chart Style**: Switch between light and dark chart backgrounds

### Available Charts

**System Tab:**
- CPU Usage (%)
- CPU Frequency (MHz)
- Memory Usage (%)
- Temperature (°C)
- Download & Upload (KB/s)

**SEN66 Tab:**
- Temperature & Humidity (dual-axis)
- CO₂ (ppm)
- VOC & NOx Index
- PM Mass Concentration (µg/m³) - PM1.0, PM2.5, PM4.0, PM10
- PM Number Concentration (#/cm³) - PM0.5, PM1.0, PM2.5, PM4.0, PM10

## Sensor Details

The SEN66 tab includes tooltips for each sensor with detailed specifications:

- **Temperature** (SHTC3): ±0.45°C typical accuracy (15–40°C), range −40 to 125°C, with firmware self-heating correction
- **Humidity** (SHTC3): ±4.5%RH typical accuracy (20–80%RH), range 0–100%RH
- **CO₂** (SCD4x NDIR): ±(50 ppm + 5% of reading) for 400–5000 ppm, range 0–40,000 ppm, requires ~3 min warm-up
- **VOC Index** (SGP4x MOX): Dimensionless 0–500, baseline 100 = typical clean indoor air
- **NOx Index** (SGP4x MOX): Dimensionless 1–500, 1 = cleanest possible air

## Development Notes

- **Reactive programming**: Efficient state management using Shiny's reactive system
- **History buffers**: 60-point deques per device for sparkline rendering
- **Incremental updates**: Charts use batch updates to avoid DOM teardown and flashing
- **Per-device state**: Reactive values and history tracked independently for each device
- **Session lifecycle**: SSE streams are task-based and auto-cancelled on session end
