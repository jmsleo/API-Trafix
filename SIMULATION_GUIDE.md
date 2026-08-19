# Docker Simulation Guide

Full stack simulation of the API-Trafix parking gate system using Docker.
No hardware required — tests everything end-to-end on your local machine.

## Quick Start

```bash
cd /home/americano/kerja/API-Trafix

# Start everything
bash scripts/simulation/run.sh

# Open in browser
# Swagger:    http://localhost:8000/docs
# Signage:    http://localhost:8000/signage/?gate=1
# Adminer:    http://localhost:8080
```

## What Gets Simulated

| Real Component | Simulation |
|---|---|
| Gate Controller (MQTT) | `mock_gate_controller.py` — interactive CLI |
| Gate Controller (TCP) | `mock_tcp_controller.py` — TCP server |
| LPR Camera | `mock_lpr_camera.py` — HTTP server |
| Signage Display | Browser — real web app |
| GPIO Bridge | Not needed (no physical GPIO) |

## Architecture

```
Docker Compose
┌────────────────────────────────────────────────────┐
│                                                     │
│  ┌──────────┐  ┌───────┐  ┌─────────────────────┐ │
│  │ Postgres │  │ Redis │  │ Mosquitto MQTT       │ │
│  │ :5432    │  │ :6379 │  │ :1883                │ │
│  └──────────┘  └───────┘  └─────────────────────┘ │
│                                                     │
│  ┌──────────────────────────────────────────────┐  │
│  │ API-Trafix                                   │  │
│  │ :8000 (Swagger + Signage Display)            │  │
│  └──────────────────────────────────────────────┘  │
│                                                     │
│  ┌────────────────┐  ┌─────────────────────────┐  │
│  │ Mock LPR       │  │ Mock TCP Controller     │  │
│  │ :8090          │  │ :5000                   │  │
│  └────────────────┘  └─────────────────────────┘  │
│                                                     │
└────────────────────────────────────────────────────┘

Host machine:
  mock_gate_controller.py → connects to MQTT :1883
  Browser → http://localhost:8000
```

## Files

| File | Purpose |
|---|---|
| `docker-compose.sim.yml` | Docker Compose stack with all services |
| `scripts/simulation/mock_gate_controller.py` | Interactive CLI for gate events |
| `scripts/simulation/mock_lpr_camera.py` | HTTP server returning plate data |
| `scripts/simulation/mock_tcp_controller.py` | TCP server for TCP controllers |
| `scripts/simulation/run.sh` | One-command launcher |

## Step-by-Step Setup

### 1. Start Docker services

```bash
cd /home/americano/kerja/API-Trafix
docker compose -f docker-compose.sim.yml up -d --build
```

Wait for all containers to be healthy:

```bash
docker compose -f docker-compose.sim.yml ps
```

Expected output:
```
NAME                    STATUS
api-trafix-db           Up
api-trafix-redis        Up
api-trafix-mqtt         Up
api-trafix-mock-lpr     Up
api-trafix-mock-tcp     Up
api-trafix-api          Up
```

### 2. Verify API is ready

```bash
curl http://localhost:8000/health
# Should return: {"status": "healthy"}
```

### 3. Open Swagger docs

Open in browser:
```
http://localhost:8000/docs
```

Test endpoints:
- `GET /api/system/health` — system health
- `GET /api/gates/status` — gate status
- `GET /api/events/stream` — SSE stream

### 4. Open Signage Display

Open in browser:
```
http://localhost:8000/signage/?gate=1
```

You should see the fullscreen signage display with clock.

### 5. Run Mock Gate Controller

In a new terminal:

```bash
cd /home/americano/kerja/API-Trafix
python3 scripts/simulation/mock_gate_controller.py
```

You'll see:
```
╔══════════════════════════════════════════════════╗
║        Mock Gate Controller — Gate 1             ║
╠══════════════════════════════════════════════════╣
║  Connected to MQTT broker at localhost:1883      ║
║                                                  ║
║  [1] Vehicle arrives (loop sensor)               ║
║  [2] Ticket button pressed                       ║
║  [3] Vehicle clears lane                         ║
║  [4] RFID card tap                               ║
║  [h] Send heartbeat                              ║
║  [w] Force welcome status                        ║
║  [t] Force thanks status                         ║
║  [q] Quit                                        ║
╚══════════════════════════════════════════════════╝
```

### 6. Simulate a full gate cycle

Press keys in the mock controller:

```
[1] → Vehicle arrives
    → Signage shows "Selamat Datang" (Welcome)
    → API logs: "gate 1: vehicle arrived"

[2] → Ticket button pressed
    → API reads plate from mock LPR (B 1234 XYZ)
    → API issues ticket
    → API opens barrier (outputCtrl)
    → Signage shows "Terima Kasih" + plate number

[3] → Vehicle clears lane
    → API logs: "gate 1: vehicle cleared the lane"

[h] → Send heartbeat
    → API logs: "gate 1: status — inputs={...} relays={...}"
```

### 7. Test signage status manually

```bash
# Set welcome status
curl -X POST http://localhost:8000/api/signage/status/1 \
  -H "Content-Type: application/json" \
  -d '{"status": "welcome", "plate_number": "B 1234 XYZ"}'

# Set thanks status
curl -X POST http://localhost:8000/api/signage/status/1 \
  -H "Content-Type: application/json" \
  -d '{"status": "thanks", "plate_number": "B 1234 XYZ", "transaction_code": "TRX001"}'

# Check status
curl http://localhost:8000/api/signage/status/1
```

### 8. Browse database

Open Adminer:
```
http://localhost:8080
```

Login:
- System: PostgreSQL
- Server: db
- Username: trafix
- Password: trafix
- Database: trafix

Browse tables:
- `gates` — gate definitions
- `devices` — device configurations
- `park_transactions` — ticket history
- `signages` — signage displays
- `signage_contents` — uploaded content

## Simulated Plate Data

The mock LPR camera returns:

```json
{
  "plate_num": "B 1234 XYZ",
  "url_gambar": "http://mock-lpr:8090/image/B1234XYZ.jpg"
}
```

To change the plate number, set the `PLATE_NUMBER` env var in
`docker-compose.sim.yml`:

```yaml
mock-lpr:
  environment:
    PLATE_NUMBER: "B 9999 ABC"
```

## Simulated RFID Card

The mock controller sends card number `006343040` — this matches the demo
member seeded by the API (Angelo / H4818AI). Member entry should succeed
without a paper ticket.

## MQTT Topics Monitored

| Topic | Direction | What happens |
|---|---|---|
| `/GATE/event/1` | Mock → API | Sensor inputs, card reads, heartbeat |
| `/GATE/IN/1` | API → Mock | Barrier open command (outputCtrl) |
| `/GATE/IN/1/status` | API → Mock | Signage status (welcome/thanks) |
| `gate/text` | API → Signage | Status text for web display |

## Troubleshooting

| Problem | Solution |
|---|---|
| API won't start | Check `docker compose -f docker-compose.sim.yml logs api` |
| MQTT connection failed | Ensure MQTT container is running: `docker ps \| grep mqtt` |
| Signage shows "Menyambungkan..." | Check SSE: open browser console, look for errors |
| Mock controller can't connect | Verify MQTT port: `nc -z localhost 1883` |
| Port 8000 already in use | Stop other services: `lsof -i :8000` |
| Plate not showing on signage | Check mock LPR: `curl http://localhost:8090/checklpr` |

## Stop Everything

```bash
# Stop containers (keeps data)
docker compose -f docker-compose.sim.yml down

# Stop and wipe database
docker compose -f docker-compose.sim.yml down -v
```

## Cleanup

```bash
# Remove all containers and images
docker compose -f docker-compose.sim.yml down -v --rmi all
```
