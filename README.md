# API-Trafix

FastAPI-based REST API for a complete parking gate management system. Replaces
the legacy Parkways Monitoring desktop app with a web-based architecture that
controls gate controllers via MQTT/TCP, manages LPR cameras, processes tickets
and payments, and drives digital signage displays.

## Architecture

```
┌─────────────────────────────────────────────────────────────────────────┐
│                          Server (Linux/AMD64)                           │
│                                                                         │
│  ┌──────────────┐  ┌──────────┐  ┌─────────┐  ┌─────────────────────┐ │
│  │  FastAPI App  │  │ Postgres │  │  Redis  │  │  Mosquitto Broker   │ │
│  │  (port 8000)  │  │  :5432   │  │  :6379  │  │     :1883           │ │
│  │               │  │          │  │         │  │                     │ │
│  │  Orchestrator │  │          │  │         │  │                     │ │
│  │  Gate Cycle   │  │          │  │         │  │                     │ │
│  │  Signage Svc  │  │          │  │         │  │                     │ │
│  │  TCP Gateway  │  │          │  │         │  │                     │ │
│  └──────┬───────┘  └──────────┘  └─────────┘  └────────┬────────────┘ │
│         │                                               │              │
└─────────┼───────────────────────────────────────────────┼──────────────┘
          │                                               │
          │ MQTT/TCP                                     │ MQTT
          │                                               │
    ┌─────▼───────────────────────────────────────────────▼─────┐
    │              Gate Controllers (ARM boards)                 │
    │   ┌─────────┐  ┌─────────┐  ┌─────────┐  ┌─────────┐    │
    │   │ Gate 1  │  │ Gate 2  │  │ Gate 3  │  │ Gate N  │    │
    │   │ (Entry) │  │ (Exit)  │  │ (Entry) │  │ (Mixed) │    │
    │   └─────────┘  └─────────┘  └─────────┘  └─────────┘    │
    └───────────────────────────────────────────────────────────┘
          │                                    │
          │ HTTP (LPR results)                 │ GPIO
          │                                    │
    ┌─────▼──────┐                     ┌───────▼──────────┐
    │ LPR Cameras │                     │  Raspberry Pi    │
    │ (ECV86)     │                     │  GPIO Bridge     │
    └────────────┘                     │  Signage Display │
                                       └──────────────────┘
```

### Components

| Component | Description |
|---|---|
| **FastAPI App** | REST API for admin, operator, finance, gate control, and signage |
| **Orchestrator** | Subscribes to gate MQTT events, drives entry/exit flows, controls barriers |
| **Gate Cycle Service** | Business logic for ticketing, fees, member entry, and exit settlement |
| **Signage Service** | Manages web-based signage displays (welcome/thanks screens, ads) |
| **TCP Gateway** | Persistent TCP connections for controllers that speak raw TCP |
| **PostgreSQL** | Primary database (gates, devices, transactions, members, signage content) |
| **Redis** | Caching, sessions, and pub/sub for real-time event streaming |
| **Mosquitto MQTT** | Message broker bridging the API to gate controllers and LPR cameras |
| **GPIO Bridge** | Python script on Raspberry Pi for vehicle detection and help button |
| **Signage Display** | Fullscreen web app running in Chromium kiosk mode |

## Prerequisites

- [uv](https://docs.astral.sh/uv/) (Python package manager)
- [Docker](https://www.docker.com/) + Docker Compose
- Python 3.13+
- `psql` (PostgreSQL client) for applying migrations
- Raspberry Pi with Raspbian (for on-site deployment)

## Installation

### 1. Clone and install dependencies

```bash
git clone <repo-url>
cd API-Trafix
uv sync
```

### 2. Create environment file

```bash
cp .env.example .env
```

### 3. Configure environment variables

Open `.env` and set the required values:

```bash
# --- Required ---

# Generate a secret key for JWT tokens
SECRET_KEY=$(python3 -c "import secrets; print(secrets.token_urlsafe(48))")

# MQTT credentials (must match what gate controllers use)
MQTT_ENABLED=true
MQTT_HOST=127.0.0.1
MQTT_PORT=1883
MQTT_USERNAME=bssparking
MQTT_PASSWORD=BCTDev_2025

# Site identity (printed on tickets)
SITE_NAME=Trafix Parking
SITE_ADDRESS=Jl. Contoh No. 1

# API base URL (used by orchestrator for internal HTTP calls)
API_BASE_URL=http://127.0.0.1:8000

# --- Optional ---

# Debug mode (enables Swagger docs at /docs)
DEBUG=true

# TCP gateway for controllers that speak raw TCP
TCP_ENABLED=false
TCP_DEFAULT_PORT=5000

# Signage display
SIGNAGE_PUBLIC_BASE_URL=http://192.168.1.13:8000
```

**Important:** All MQTT credentials (`MQTT_USERNAME`, `MQTT_PASSWORD`) must be
identical across the API, the Mosquitto broker, and every gate controller.

### 4. Start infrastructure

```bash
docker compose up -d
```

This starts:

| Service | Container | Port | Purpose |
|---|---|---|---|
| PostgreSQL 17 | `api-trafix-db` | 5432 | Primary database |
| Redis 7 | `api-trafix-redis` | 6379 | Cache + sessions |
| Mosquitto 2 | `api-trafix-mqtt` | 1883 | MQTT broker |
| Adminer | `api-trafix-adminer` | 8080 | DB web UI |

Verify all containers are running:

```bash
docker compose ps
```

### 5. Apply migrations

The app uses `create_all` at startup which only creates new tables — it never
modifies existing ones. Schema changes (new columns, altered types) must be
applied manually:

```bash
for f in migrations/*.sql; do
  psql "postgresql://trafix:trafix@localhost:5432/trafix" -f "$f"
done
```

### 6. Start the API server

```bash
uv run uvicorn api_trafix.main:app --host 0.0.0.0 --port 8000 --reload
```

On startup the app:
- Creates all database tables
- Seeds reference data (gates, vehicle types, parking rates, demo member)
- Connects to MQTT broker (if `MQTT_ENABLED=true`)
- Subscribes to gate event topics
- Starts the TCP gateway (if `TCP_ENABLED=true`)
- Syncs signage content to displays

The API is now available at `http://localhost:8000` with interactive docs at
`http://localhost:8000/docs` (when `DEBUG=true`).

## Configuration Reference

### Environment Variables

| Variable | Default | Required | Description |
|---|---|---|---|
| `DATABASE_URL` | — | Yes | PostgreSQL connection string |
| `REDIS_URL` | — | Yes | Redis connection string |
| `SECRET_KEY` | — | Yes | JWT signing key |
| `DEBUG` | `false` | No | Enable Swagger docs + verbose errors |
| `MQTT_ENABLED` | `false` | Yes | Start MQTT orchestrator |
| `MQTT_HOST` | `127.0.0.1` | Yes | MQTT broker host |
| `MQTT_PORT` | `1883` | Yes | MQTT broker port |
| `MQTT_USERNAME` | — | Yes | MQTT auth username |
| `MQTT_PASSWORD` | — | Yes | MQTT auth password |
| `TCP_ENABLED` | `false` | No | Start TCP gateway |
| `TCP_DEFAULT_PORT` | `5000` | No | Default TCP port for controllers |
| `API_BASE_URL` | `http://127.0.0.1:8000` | Yes | Internal API URL for orchestrator |
| `SITE_NAME` | `Trafix Parking` | No | Name printed on tickets |
| `SITE_ADDRESS` | — | No | Address printed on tickets |
| `SIGNAGE_PUBLIC_BASE_URL` | `http://192.168.1.13:8000` | No | Base URL for signage content |
| `SIGNAGE_LEGACY_BROKERS` | `[{...}]` | No | Legacy MQTT brokers for signage |

### Device Configuration

Devices are stored in the `devices` table with a JSON `config` column.
The orchestrator reads this at startup to know how to talk to each gate.

**Controller (relay + printer):**

```json
{
  "serial_no": "YOUR_BOARD_SERIAL",
  "connection_type": "mqtt",
  "tcp_port": 5000
}
```

- `connection_type`: `"mqtt"` | `"tcp"` | `"both"`
- `tcp_port`: only used when `connection_type` includes `"tcp"`

**LPR Camera (entry side):**

```json
{
  "base_url": "http://192.168.1.130:8090",
  "serves_http": true,
  "update_topic": "gate/in/update/1"
}
```

**LPR Camera (exit side):**

```json
{
  "serves_http": false,
  "pos_topic_gate": "2"
}
```

**Signage Display:**

```json
{
  "signage_code": "signage-1",
  "gate_number": "1",
  "media_topic": "gate/media",
  "ads_topic": "gate/ads",
  "idle_topic": "gate/idle"
}
```

## Running the System

### Development mode (no hardware)

```bash
# Terminal 1: infrastructure
docker compose up -d

# Terminal 2: API server
uv run uvicorn api_trafix.main:app --reload

# Open Swagger docs
open http://localhost:8000/docs
```

With `MQTT_ENABLED=false`, the API runs without a broker — all gate operations
use a `NullPublisher` and return mock responses. This is useful for developing
admin/operator UIs without hardware.

### Production mode (with gate hardware)

```bash
# 1. Start infrastructure
docker compose up -d

# 2. Apply any pending migrations
for f in migrations/*.sql; do
  psql "postgresql://trafix:trafix@localhost:5432/trafix" -f "$f"
done

# 3. Start API with MQTT enabled
MQTT_ENABLED=true uv run uvicorn api_trafix.main:app --host 0.0.0.0 --port 8000

# 4. Check logs for orchestrator startup
# Should see: "watching gate 1 on /GATE/event/1"
# Should see: "MQTT: Connected and subscribed to:"
```

### Production mode (with TCP controllers)

```bash
# Add to .env
TCP_ENABLED=true
TCP_DEFAULT_PORT=5000

# Start API
MQTT_ENABLED=true TCP_ENABLED=true uv run uvicorn api_trafix.main:app --host 0.0.0.0 --port 8000
```

## Digital Signage System

The signage system replaces the legacy Vala apps (`pw-signage`,
`pw-signage-gateout`) with a web-based display.

### Architecture

```
Raspberry Pi                    API-Trafix Server              Browser Display
┌──────────────────┐           ┌─────────────────┐           ┌─────────────────┐
│ GPIO Bridge      │──HTTP───▶│ /api/signage/*  │──SSE───▶ │ Fullscreen HTML │
│ (vehicle detect) │           │                 │           │ (Chromium)      │
│                  │           │ MQTT bus        │           │                 │
│ Signage Display  │◀──SSE────│ gate/text       │           │ Welcome/Thanks  │
│ (Chromium)       │           │ gate/ads        │           │ Plate display   │
└──────────────────┘           └─────────────────┘           │ Ads slideshow   │
                                                             └─────────────────┘
```

### Setting up the signage display (Raspberry Pi)

**1. Install dependencies:**

```bash
sudo apt-get update
sudo apt-get install -y chromium-browser unclutter
pip install requests paho-mqtt RPi.GPIO
```

**2. Copy files to the Pi:**

```bash
# From the server
scp scripts/signage-display/start.sh pi@raspberrypi:/home/pi/signage-display/
scp scripts/gpio-bridge/gpio_bridge.py pi@raspberrypi:/opt/gpio-bridge/
scp scripts/gpio-bridge/config.example.json pi@raspberrypi:/opt/gpio-bridge/config.json
```

**3. Configure the GPIO bridge:**

Edit `/opt/gpio-bridge/config.json` on the Pi:

```json
{
    "api_base_url": "http://192.168.1.13:8000",
    "gate_code": "1",
    "gpio_pin_vehicle": 17,
    "gpio_pin_help": 27,
    "poll_interval_ms": 100,
    "debounce_seconds": 2.0,
    "mqtt_enabled": true,
    "mqtt_host": "192.168.1.1",
    "mqtt_port": 1883,
    "mqtt_username": "bssparking",
    "mqtt_password": "BCTDev_2025"
}
```

**4. Install systemd services:**

```bash
# GPIO Bridge
sudo cp /opt/gpio-bridge/gpio-bridge.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable gpio-bridge
sudo systemctl start gpio-bridge

# Signage Display
sudo cp /home/pi/signage-display/signage-display.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable signage-display
sudo systemctl start signage-display
```

**5. Verify:**

```bash
# Check GPIO bridge
sudo systemctl status gpio-bridge
sudo journalctl -u gpio-bridge -f

# Check signage display (should open Chromium in kiosk mode)
sudo systemctl status signage-display
```

### GPIO Pinout

| BCM Pin | Physical Pin | Function |
|---|---|---|
| GPIO 17 | Pin 11 | Vehicle detection (loop sensor input) |
| GPIO 27 | Pin 13 | Help button (intercom trigger) |

### Signage API Endpoints

| Endpoint | Method | Description |
|---|---|---|
| `/signage/` | GET | Open signage display (fullscreen web app) |
| `/api/signage/stream/{gate}` | GET | SSE stream for real-time updates |
| `/api/signage/status/{gate}` | GET | Get current signage state |
| `/api/signage/status/{gate}` | POST | Manually update status |
| `/api/signage/vehicle-detected` | POST | GPIO bridge callback |
| `/api/signage/help-button` | POST | GPIO bridge callback |
| `/api/signage/content/sync` | POST | Force content sync from DB |

### Testing the signage display

Open in any browser:

```
http://<server-ip>:8000/signage/?gate=1
```

Simulate events:

```bash
# Vehicle detected
curl -X POST http://localhost:8000/api/signage/vehicle-detected \
  -H "Content-Type: application/json" \
  -d '{"gate": "1"}'

# Set status to thanks with plate
curl -X POST http://localhost:8000/api/signage/status/1 \
  -H "Content-Type: application/json" \
  -d '{"status": "thanks", "plate_number": "B 1234 XYZ"}'
```

## Connecting Gate Devices

### MQTT-based controllers

1. Ensure `MQTT_ENABLED=true` in `.env`
2. Flash gate controller firmware with MQTT settings:
   - Broker: `<server-ip>:1883`
   - Username: `MQTT_USERNAME` from `.env`
   - Password: `MQTT_PASSWORD` from `.env`
3. Register devices in the `devices` table (via API or SQL)
4. Restart the API — logs should show:

```
watching gate 1 on /GATE/event/1
MQTT: Connected and subscribed to:
```

### TCP-based controllers

1. Set `TCP_ENABLED=true` in `.env`
2. Register devices with `connection_type: "tcp"` or `"both"`
3. Ensure the controller's TCP port matches `TCP_DEFAULT_PORT` (default: 5000)
4. Start the API — logs should show:

```
tcp_gateway: connected to gate 1 at 192.168.1.20:5000
```

### Verifying without hardware

Publish a test MQTT message:

```bash
mosquitto_pub -h localhost -p 1883 \
  -u bssparking -P BCTDev_2025 \
  -t '/GATE/event/1' \
  -m '{"method":"inputInfo","serialNo":"TEST","data":{"input3":1,"input2":0,"input4":0}}'
```

The API should:
1. Log "gate 1: vehicle arrived"
2. Publish `{"status":"welcome"}` to `/GATE/IN/1/status`
3. Wait for `input2=1` (ticket button press) to issue a ticket

## API Reference

### System Health

| Endpoint | Description |
|---|---|
| `GET /health` | Basic health check |
| `GET /api/system/health` | Detailed system health (MQTT + TCP status) |
| `GET /api/system/mqtt/status` | MQTT broker connection status |
| `GET /api/system/tcp/status` | TCP gateway connection status |

### Gate Control

| Endpoint | Description |
|---|---|
| `GET /api/gates/status` | All gates: online/offline, sensors |
| `GET /api/gates/{code}/status` | Single gate health detail |
| `GET /api/gates/{code}/sensors` | Current sensor states |
| `POST /api/gates/{code}/barrier/open` | Manually open barrier |
| `POST /api/gates/{code}/relay/{id}/pulse` | Pulse a specific relay |

### Events

| Endpoint | Description |
|---|---|
| `GET /api/events/stream` | Unified SSE stream (gate + system events) |
| `GET /api/gate/events` | Paginated gate event history |
| `GET /api/pos/events/stream` | POS-specific event stream |

### Gate Cycle (Business Logic)

| Endpoint | Description |
|---|---|
| `POST /api/gatein` | Issue entry ticket |
| `POST /api/gatein/card` | Member card entry |
| `POST /api/gateout/detailtransaction` | Quote exit fee |
| `PUT /api/gateout/gateoutKasir` | Settle exit at cashier |

### Signage

| Endpoint | Description |
|---|---|
| `GET /signage/?gate=N` | Open signage display |
| `GET /api/signage/stream/{gate}` | SSE stream for display |
| `GET /api/signage/status/{gate}` | Get signage state |
| `POST /api/signage/status/{gate}` | Update signage status |

### Admin (requires JWT)

| Endpoint | Description |
|---|---|
| `POST /auth/login` | Login, get JWT |
| `GET /auth/me` | Current user info |
| `GET,POST /gates/` | Manage gates |
| `GET,POST /devices/` | Manage devices |
| `GET,POST /members/` | Manage members |
| `GET,POST /shifts/` | Manage shifts |
| `GET,POST /signages/` | Manage signage content |
| `GET,POST /parking-rates/` | Manage parking rates |
| `GET /finance/dashboard/*` | Financial dashboards |

Full interactive docs: `http://localhost:8000/docs` (when `DEBUG=true`)

## Test Suite

### Curl-based integration tests

```bash
# Run all tests
bash scripts/curl-tests/run_all.sh

# Run individual suites
bash scripts/curl-tests/00_bootstrap.sh   # infra + seed users + tokens
bash scripts/curl-tests/01_auth.sh        # authentication
```

### Signage system tests

```bash
# Test signage endpoints
bash scripts/test-signage.sh
```

### Manual verification

```bash
# Health check
curl http://localhost:8000/api/system/health | python3 -m json.tool

# All gates status
curl http://localhost:8000/api/gates/status | python3 -m json.tool

# SSE stream (Ctrl+C to stop)
curl -N http://localhost:8000/api/events/stream
```

## Useful Commands

| Command | Description |
|---|---|
| `docker compose up -d` | Start Postgres + Redis + MQTT broker |
| `docker compose down` | Stop containers (keeps data) |
| `docker compose down -v` | Stop containers and wipe volumes |
| `docker logs -f api-trafix-mqtt` | Follow MQTT broker logs |
| `docker exec -it api-trafix-db psql -U trafix -d trafix` | Open Postgres shell |
| `docker exec -it api-trafix-redis redis-cli` | Open Redis shell |
| `uv run uvicorn api_trafix.main:app --reload` | Start API with hot-reload |
| `uv run uvicorn api_trafix.main:app --host 0.0.0.0 --port 8000` | Production start |

## Project Structure

```
API-Trafix/
├── deploy/                     # Mosquitto broker config + entrypoint
├── migrations/                 # SQL migrations (apply manually)
├── scripts/
│   ├── curl-tests/             # End-to-end API test suite
│   ├── gpio-bridge/            # Raspberry Pi GPIO bridge service
│   └── signage-display/        # Chromium kiosk launcher
├── src/api_trafix/
│   ├── main.py                 # FastAPI app + lifespan setup
│   ├── config/
│   │   ├── settings.py         # Pydantic Settings (env vars)
│   │   ├── database.py         # SQLAlchemy async engine
│   │   └── redis.py            # Redis client
│   ├── models/                 # SQLAlchemy ORM models
│   ├── schemas/                # Pydantic request/response schemas
│   ├── routes/
│   │   ├── auth.py             # /auth/*
│   │   ├── gate_cycle.py       # /api/gatein, /api/gateout
│   │   ├── gate_control.py     # /api/gates/* (barrier, sensors)
│   │   ├── events.py           # /api/events/stream (SSE)
│   │   ├── system.py           # /api/system/*
│   │   ├── signage.py          # /signages/* (CRUD)
│   │   ├── signage_display.py  # /api/signage/* (display control)
│   │   └── ...                 # Other admin endpoints
│   ├── services/
│   │   ├── orchestrator.py     # MQTT event handler + gate flow
│   │   ├── gate_cycle.py       # Ticket/fee/member business logic
│   │   ├── mqtt_bus.py         # MQTT transport (aiomqtt)
│   │   ├── tcp_gateway.py      # TCP connections to controllers
│   │   ├── tcp_protocol.py     # TCP frame encode/decode
│   │   ├── protocol.py         # MQTT wire protocol
│   │   ├── publisher.py        # MQTT command publisher
│   │   ├── device_registry.py  # Reads devices table, builds maps
│   │   ├── gate_health.py      # Per-gate heartbeat tracking
│   │   ├── system_status.py    # MQTT/TCP connection health
│   │   ├── events.py           # Redis pub/sub for SSE
│   │   ├── signage_display.py  # Web signage state management
│   │   ├── signage_publisher.py # Pushes content to displays
│   │   └── ...
│   └── utils/
├── static/signage/             # Web-based signage display (HTML)
├── storage/                    # Runtime: camera images, uploads
├── media/                      # Runtime: signage content files
├── .env                        # Environment config (not committed)
├── docker-compose.yml          # Infrastructure containers
└── pyproject.toml              # Python dependencies
```

## MQTT Topic Map

| Topic | Direction | Purpose |
|---|---|---|
| `/GATE/event/{gate}` | Controller → API | Sensor inputs, card reads, status |
| `/GATE/IN/{gate}` | API → Controller | Print ticket, open barrier |
| `/GATE/IN/{gate}/status` | API → LPR/Display | Drive signage: welcome/thanks |
| `/GATE/OUT/{gate}` | API → Controller | Exit barrier command |
| `gate/out/{gate}/pos` | LPR → API | Exit plate read announcement |
| `gate/text` | API → Display | Status text for signage |
| `gate/ads` | API → Display | Ad slideshow content |
| `gate/idle` | API → Display | Idle background image |
| `gate/media` | API → Display | Video playlist content |

## Troubleshooting

| Problem | Solution |
|---|---|
| `column gates.gate_code does not exist` | Apply pending migrations (see Migrations section) |
| MQTT broker connection refused | Check `docker compose ps` — broker must be running |
| Gate controller not receiving commands | Verify MQTT credentials match in `.env` and controller firmware |
| Signage display not updating | Check SSE connection: open browser console, look for `/api/signage/stream` |
| GPIO bridge not detecting vehicles | Check `sudo journalctl -u gpio-bridge -f` for errors |
| TCP gateway not connecting | Verify `TCP_ENABLED=true` and controller IP/port in devices table |
| API starts but gate operations fail | Set `MQTT_ENABLED=true` and ensure broker is running |
| Swagger docs not showing | Set `DEBUG=true` in `.env` |
