# BSS Parking Signage System - Implementation Summary

## Overview

Replaced the Vala-based signage apps (`pw-signage` and `pw-signage-gateout`) with a modern web-based system using API-Trafix as the backend.

## Architecture

```
┌─────────────────────────┐     ┌──────────────────────────┐     ┌─────────────────────────┐
│  Raspberry Pi           │     │  API-Trafix Server       │     │  Browser (Signage)      │
│  (GPIO Bridge)          │────▶│  (FastAPI Backend)       │────▶│  (Fullscreen Display)   │
│                         │     │                          │     │                         │
│  - GPIO vehicle detect  │     │  - /api/signage/*        │     │  - SSE real-time        │
│  - Help button          │     │  - MQTT bus              │     │  - Plate display        │
│  - MQTT (legacy)        │     │  - Redis pub/sub         │     │  - Welcome/Thanks       │
└─────────────────────────┘     └──────────────────────────┘     │  - Ads playlist         │
                                                                │  - Audio playback       │
                                                                └─────────────────────────┘
```

## Components

### 1. GPIO Bridge Service (`scripts/gpio-bridge/`)

**File:** `gpio_bridge.py`

Runs on Raspberry Pi, replaces the Vala app's GPIO handling:

- Reads GPIO pin 17 for vehicle detection (loop sensor)
- Reads GPIO pin 27 for help button (intercom)
- Calls API-Trafix endpoints when events occur
- Publishes MQTT messages for backward compatibility
- Configurable debounce to prevent multiple triggers

**Installation:**
```bash
pip install requests paho-mqtt RPi.GPIO
sudo cp gpio-bridge.service /etc/systemd/system/
sudo systemctl enable gpio-bridge
```

### 2. Signage Display Service (`services/signage_display.py`)

Manages signage state and pushes updates via Redis pub/sub:

- `SignageState`: Current state of a signage display
- `SignageDisplayService`: Manages state and pushes updates
- Redis channels for SSE subscribers
- MQTT backward compatibility

### 3. Signage API Endpoints (`routes/signage_display.py`)

| Endpoint | Method | Purpose |
|---|---|---|
| `/api/signage/vehicle-detected` | POST | GPIO bridge callback |
| `/api/signage/help-button` | POST | GPIO bridge callback |
| `/api/signage/status/{gate}` | GET | Get current status |
| `/api/signage/status/{gate}` | POST | Update status manually |
| `/api/signage/stream/{gate}` | GET | SSE stream for displays |
| `/api/signage/content/sync` | POST | Trigger content sync |

### 4. Web-based Signage Display (`static/signage/index.html`)

Fullscreen kiosk mode display with:

- Real-time updates via SSE
- Welcome/Thanks status display
- Plate number display
- Transaction code display
- Ads slideshow (scrolling)
- Idle background image
- Audio playback (welcome, thanks sounds)
- Clock display
- Connection status indicator
- Fullscreen on click

**Usage:**
```
http://192.168.1.13:8000/signage/?gate=1
```

### 5. Display Startup Script (`scripts/signage-display/`)

**File:** `start.sh`

Launches Chromium in kiosk mode on Raspberry Pi:

```bash
./start.sh 1 http://192.168.1.13:8000
```

**Installation:**
```bash
sudo cp signage-display.service /etc/systemd/system/
sudo systemctl enable signage-display
```

## Data Flow

### Vehicle Entry

1. Vehicle on arrival loop → GPIO pin 17 goes LOW
2. GPIO bridge calls `POST /api/signage/vehicle-detected`
3. API updates signage state to "welcome"
4. Redis publishes to `signage:text` channel
5. SSE stream pushes update to browser display
6. Browser shows "Selamat Datang" + plays welcome sound

### Ticket Button Press

1. Driver presses ticket button → MQTT `inputInfo` message
2. Orchestrator processes ticket request
3. Orchestrator calls `_signage_status(gate, "thanks")`
4. Signage publisher sends to MQTT topics + signage display service
5. Browser shows "Terima Kasih" + plate number + plays thanks sound

### Help Button

1. Driver presses help button → GPIO pin 27 goes LOW
2. GPIO bridge calls `POST /api/signage/help-button`
3. API logs event and publishes system event
4. (Future: trigger intercom call)

## Files Created/Modified

### New Files

| File | Purpose |
|---|---|
| `scripts/gpio-bridge/gpio_bridge.py` | GPIO bridge service |
| `scripts/gpio-bridge/config.example.json` | Configuration template |
| `scripts/gpio-bridge/gpio-bridge.service` | Systemd service |
| `scripts/gpio-bridge/README.md` | GPIO bridge documentation |
| `services/signage_display.py` | Signage display service |
| `routes/signage_display.py` | Signage API endpoints |
| `static/signage/index.html` | Web-based display |
| `scripts/signage-display/start.sh` | Display startup script |
| `scripts/signage-display/signage-display.service` | Systemd service |
| `scripts/signage-display/README.md` | Display documentation |
| `scripts/test-signage.sh` | Test script |

### Modified Files

| File | Changes |
|---|---|
| `main.py` | Added signage display routes, static files, service initialization |
| `services/orchestrator.py` | Added `signage_display` parameter, publish to signage display service |

## Testing

### Run Test Script

```bash
cd /home/americano/kerja/API-Trafix
./scripts/test-signage.sh
```

### Manual Testing

1. Start API server:
   ```bash
   uv run uvicorn api_trafix.main:app --host 0.0.0.0 --port 8000
   ```

2. Open signage display in browser:
   ```
   http://localhost:8000/signage/?gate=1
   ```

3. Test status update:
   ```bash
   curl -X POST http://localhost:8000/api/signage/status/1 \
     -H "Content-Type: application/json" \
     -d '{"status": "welcome", "plate_number": "B 1234 XYZ"}'
   ```

### On-Site Testing (Raspberry Pi)

1. Install GPIO bridge:
   ```bash
   pip install requests paho-mqtt RPi.GPIO
   cp scripts/gpio-bridge/gpio_bridge.py /opt/gpio-bridge/
   cp scripts/gpio-bridge/config.example.json /opt/gpio-bridge/config.json
   # Edit config.json with your settings
   sudo cp scripts/gpio-bridge/gpio-bridge.service /etc/systemd/system/
   sudo systemctl enable gpio-bridge
   sudo systemctl start gpio-bridge
   ```

2. Install signage display:
   ```bash
   sudo apt-get install chromium-browser unclutter
   cp scripts/signage-display/start.sh /home/pi/signage-display/
   sudo cp scripts/signage-display/signage-display.service /etc/systemd/system/
   sudo systemctl enable signage-display
   sudo systemctl start signage-display
   ```

## Configuration

### GPIO Bridge Config (`config.json`)

```json
{
    "api_base_url": "http://192.168.1.13:8000",
    "gate_code": "1",
    "gpio_pin_vehicle": 17,
    "gpio_pin_help": 27,
    "poll_interval_ms": 100,
    "debounce_seconds": 2.0,
    "help_debounce_seconds": 5.0,
    "mqtt_enabled": true,
    "mqtt_host": "192.168.1.1",
    "mqtt_port": 1883,
    "mqtt_username": "bssparking",
    "mqtt_password": "BCTDev_2025"
}
```

### Environment Variables

| Variable | Default | Description |
|---|---|---|
| `SIGNAGE_PUBLIC_BASE_URL` | `http://192.168.1.13:8000` | Base URL for signage content |
| `SIGNAGE_LEGACY_BROKERS` | `[{...}]` | MQTT brokers for backward compatibility |

## Troubleshooting

### Display not showing

- Check if Chromium is running: `ps aux | grep chromium`
- Check display service: `sudo systemctl status signage-display`

### No updates on display

- Check SSE connection in browser console
- Check API server logs
- Verify signage display service is running

### Audio not playing

- Check audio files exist in `/storage/signage/audio/`
- Check browser audio permissions
- Click anywhere on screen to enable audio

### GPIO not working

- Check GPIO permissions: `sudo raspi-config`
- Verify pin numbers in config.json
- Check GPIO bridge logs: `sudo journalctl -u gpio-bridge`

## Migration from Vala Apps

1. **Install API-Trafix** with signage support
2. **Deploy GPIO bridge** on each Raspberry Pi
3. **Deploy signage display** on each screen
4. **Disable old Vala services:**
   ```bash
   sudo systemctl disable pw-signage
   sudo systemctl disable pw-signage-gateout
   ```
5. **Test end-to-end**
6. **Remove old Vala packages:**
   ```bash
   sudo dpkg -r pw-signage
   sudo dpkg -r pw-signage-gateout
   ```
