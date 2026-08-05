# API-Trafix

FastAPI-based REST API with async SQLAlchemy (PostgreSQL) and Redis caching.

## Prerequisites

- [uv](https://docs.astral.sh/uv/) (Python package manager)
- [Docker](https://www.docker.com/) + Docker Compose
- Python 3.13+

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

4. Start the infrastructure containers (PostgreSQL + Redis):

   ```bash
   docker compose up -d
   ```

5. Verify containers are healthy:

   ```bash
   docker compose ps
   ```

## Running

Run the console script:

```bash
uv run api-trafix
```

Run the development server (once the FastAPI app is wired in `main.py`):

```bash
uv run uvicorn api_trafix.main:app --reload
```

The API will be available at `http://localhost:8000` with interactive docs at `http://localhost:8000/docs`.

## Useful Commands

| Command | Description |
| --- | --- |
| `docker compose up -d` | Start Postgres + Redis |
| `docker compose down` | Stop containers (keeps data) |
| `docker compose down -v` | Stop containers and wipe volumes |
| `docker exec -it api-trafix-db psql -U trafix -d trafix` | Open Postgres shell |
| `docker exec -it api-trafix-redis redis-cli` | Open Redis shell |

## Project Structure

```
src/api_trafix/
├── main.py          # FastAPI app entry point
├── config/          # settings, database, redis
├── models/          # SQLAlchemy models
├── schemas/         # Pydantic schemas
├── routes/          # API routers
├── services/        # business logic
└── utils/           # helpers
```
