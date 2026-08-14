# API-Trafix

FastAPI-based REST API for a parking gate system ("Fix Trafing System"). Uses
async SQLAlchemy (PostgreSQL) for storage, Redis for caching, and an MQTT
broker (mosquitto) that bridges the API to the physical gate controllers and
LPR cameras.

## Architecture

- **API** — FastAPI app (`api_trafix.main:app`) with admin / operator / finance
  endpoints and the gate-in / gate-out cycle.
- **Postgres** — primary store (`api-trafix-db`).
- **Redis** — caching / sessions (`api-trafix-redis`).
- **Mosquitto MQTT broker** (`api-trafix-mqtt`) — the main server's broker that
  every gate board connects to. The API subscribes to gate events
  (`/GATE/event/{gate}`) and commands the barriers (`/GATE/IN/{gate}`), acting
  as the orchestrator between the hardware, the LPR, and the ticket/fee engine.

## Prerequisites

- [uv](https://docs.astral.sh/uv/) (Python package manager)
- [Docker](https://www.docker.com/) + Docker Compose
- Python 3.13+
- `psql` (PostgreSQL client) for applying migrations

## First Setup

1. Clone the repository and enter the directory:

   ```bash
   git clone <repo-url>
   cd API-Trafix
   ```

2. Install dependencies:

   ```bash
   uv sync
   ```

3. Create the environment file:

   ```bash
   cp .env.example .env
   ```

4. Edit `.env` and set the required values:

   - `SECRET_KEY` — generate with
     `python -c "import secrets; print(secrets.token_urlsafe(48))"`
   - `MQTT_USERNAME` / `MQTT_PASSWORD` — generate with
     `python -c "import secrets; print(secrets.token_urlsafe(24))"`. These are
     the credentials the broker requires and every device must use.
   - `MQTT_ENABLED` — `true` to start the gate-cycle orchestrator (needs the
     broker); `false` uses a `NullPublisher` so the API runs without any
     hardware or broker.

5. Start the infrastructure (Postgres + Redis + MQTT broker):

   ```bash
   docker compose up -d
   ```

6. Verify the containers are healthy:

   ```bash
   docker compose ps
   ```

## Migrations

The app uses `Base.metadata.create_all` at startup, which **never alters
existing tables** — schema changes live in `migrations/*.sql` and must be
applied manually. Apply them in filename order:

```bash
for f in migrations/*.sql; do
  psql "postgresql://trafix:trafix@localhost:5432/trafix" -f "$f"
done
```

Skipping a migration produces errors like
`column gates.gate_code does not exist` on startup.

## Running

Start the development server:

```bash
uv run uvicorn api_trafix.main:app --reload
```

The API is available at `http://localhost:8000` with interactive docs at
`http://localhost:8000/docs` (when `DEBUG=true`).

On startup the app seeds the reference data (gates with wire ids `1` = Gate
Masuk and `2` = Gate Keluar, vehicle classes, flat parking rates, and a demo
member Angelo / H4818AI / RFID `006343040`).

## Connecting real gate devices

1. Make sure the broker is running and `MQTT_ENABLED=true` in `.env`.
2. Configure each device's firmware to point at this server's IP, port `1883`,
   with the `MQTT_USERNAME` / `MQTT_PASSWORD` from `.env`.
3. Register the hardware layout in the **devices** table before the API starts
   (the orchestrator subscribes to topics at startup). Each device is tied to a
   gate by `gate_code`:
   - **Controller** (relay + printer) — `type` containing `Controller`, with
     `config: {"serial_no": "<board serial>"}`.
   - **Camera LPR** (plate camera) — `type` containing `LPR`, with
     `config: {"base_url": "http://<ip>:8090", "serves_http": true}` for the
     entry side, or `{"serves_http": false, "pos_topic_gate": "2"}` for the
     exit LPR.
   - **Camera** (CCTV) — optional.
   Devices can be managed through the admin API (`POST/PUT /devices`, which
   reloads the running registry), or inserted directly via SQL.

4. Restart the API and check the logs — the orchestrator connects to the broker
   and reports the gate topics it is watching.

The orchestrator can be verified without hardware by publishing a test
`inputInfo` envelope to `/GATE/event/1` (e.g. with
`mosquitto_pub`); the API will issue a ticket and publish the barrier
`outputCtrl` command.

## Test Suite

There is a curl-based test suite exercising every HTTP endpoint:

```bash
bash scripts/curl-tests/run_all.sh
```

Run a single suite:

```bash
bash scripts/curl-tests/00_bootstrap.sh   # infra + seed users + tokens
bash scripts/curl-tests/01_auth.sh        # single suite
```

## Useful Commands

| Command | Description |
| --- | --- |
| `docker compose up -d` | Start Postgres + Redis + MQTT broker |
| `docker compose down` | Stop containers (keeps data) |
| `docker compose down -v` | Stop containers and wipe volumes |
| `docker logs -f api-trafix-mqtt` | Follow broker logs |
| `docker exec -it api-trafix-db psql -U trafix -d trafix` | Open Postgres shell |
| `docker exec -it api-trafix-redis redis-cli` | Open Redis shell |

## Project Structure

```
deploy/                  # mosquitto broker config + entrypoint
migrations/              # SQL migrations (apply manually, see above)
scripts/curl-tests/      # end-to-end API test suite
src/api_trafix/
├── main.py              # FastAPI app entry point
├── config/              # settings, database, redis
├── models/              # SQLAlchemy models
├── schemas/             # Pydantic schemas
├── routes/              # API routers
├── services/            # business logic (gate cycle, MQTT bus, orchestrator)
└── utils/               # helpers
```
