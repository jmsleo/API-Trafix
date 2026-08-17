# GPIO Bridge for BSS Parking Signage

Replaces the Vala signage app's GPIO handling with a lightweight Python script.

## Features

- Vehicle detection via GPIO pin (input from loop sensor)
- Help button press detection (intercom)
- Calls API-Trafix endpoints for signage updates
- Publishes MQTT messages for backward compatibility
- Configurable debounce to prevent multiple triggers
- Systemd service for auto-start

## Installation (Raspberry Pi)

```bash
# Install dependencies
pip install requests paho-mqtt RPi.GPIO

# Copy files
sudo cp gpio_bridge.py /opt/gpio-bridge/
sudo cp config.example.json /opt/gpio-bridge/config.json

# Edit config
sudo nano /opt/gpio-bridge/config.json

# Install systemd service
sudo cp gpio-bridge.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable gpio-bridge
sudo systemctl start gpio-bridge
```

## Configuration

Edit `config.json`:

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

## GPIO Pinout

| Pin | BCM | Function |
|---|---|---|
| 11 | GPIO17 | Vehicle detection (loop sensor) |
| 13 | GPIO27 | Help button (intercom) |

## API Endpoints Called

| Endpoint | Trigger |
|---|---|
| `POST /api/signage/vehicle-detected` | Vehicle on arrival loop |
| `POST /api/signage/help-button` | Help button pressed |

## MQTT Topics Published

| Topic | Payload |
|---|---|
| `/GATE/IN/{gate}/status` | `{"status":"welcome"}` |
| `gate/text` | `{"status":"welcome"}` |
