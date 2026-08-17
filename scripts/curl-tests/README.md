# API-Trafix curl test suite

Modular bash suite that exercises every HTTP endpoint of the API with curl.
Each scenario asserts an expected HTTP status code (success + error paths).

## Requirements

- Docker running (Postgres + Redis from `docker-compose.yml`)
- `curl`, `psql`, `python3`, and the project venv (`.venv/`) with werkzeug
- `pg_dump` / `pg_restore` on PATH (only needed for the backup suite)
- API listens on `http://localhost:8000` (started automatically by `00_bootstrap.sh`)

## Run

```bash
bash scripts/curl-tests/run_all.sh
```

Or step by step:

```bash
bash scripts/curl-tests/00_bootstrap.sh   # infra + seed users/gate + tokens
bash scripts/curl-tests/01_auth.sh        # single suite
```

## What it does

| File | Coverage |
|---|---|
| `00_bootstrap.sh` | docker services, starts uvicorn, seeds users via SQL (admin/finance/teknisi/operators/inactive), ensures a gate row, logs in and caches tokens + user/gate UUIDs |
| `01_auth.sh` | login, `/auth/me`, refresh rotation + replay, logout + replay, inactive account 403, login lockout 429 |
| `02_users.sh` | users CRUD, duplicates, weak password, role checks, reset-password |
| `03_reference.sh` | vehicle-types, shifts (incl. `crosses_midnight`), members + block |
| `04_pricing.sh` | parking-rates, subscription-plans + status toggles |
| `05_operator.sh` | operator-shift assignments, operator-session start/end + permission checks |
| `06_member_relations.sh` | member create with vehicle/subscription, member-subscriptions + cancel |
| `07_signage.sh` | signages, contents, assignments, schedules (full CRUD + status) |
| `08_backups_audit.sh` | backup create/upload/download/restore/delete + audit-log filters/roles |
| `09_finance.sh` | finance dashboard + reports, finance-role enforcement |
| `run_all.sh` | bootstrap then run all suites, aggregate totals, nonzero exit on failure |

## Notes

- **Destructive:** `08_backups_audit.sh` runs `POST /backups/{id}/restore` with
  `confirm:true` as its final scenario — this reloads the DB from the backup
  snapshot (drops/recreates tables). It runs last in that suite on purpose.
- **Rate limits:** the auth suite flushes Redis between phases to avoid the
  per-IP login counter (20/min) and resets the lockout it intentionally triggers.
- **State:** each suite creates its own data and cleans up after itself; only
  the bootstrap users/gate are shared. Tokens/IDs are cached in
  `scripts/curl-tests/.tokens/` (recreated on every bootstrap).
- `jq` is not required; JSON is parsed with `python3`.
