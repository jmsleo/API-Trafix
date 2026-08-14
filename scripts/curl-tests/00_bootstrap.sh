#!/usr/bin/env bash
# 00_bootstrap.sh - ensure infra + server, seed test users + gate, log in, save tokens/IDs.
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/lib.sh"

REPO_ROOT="$SCRIPT_DIR/../.."
PGURL="${DATABASE_URL:-postgresql://trafix:trafix@localhost:5432/trafix}"
PGURL="${PGURL/+asyncpg/}"
PY="$REPO_ROOT/.venv/bin/python"

echo "== bootstrap: infra =="
(cd "$REPO_ROOT" && docker compose up -d >/dev/null 2>&1 || true)

wait_db() {
  for _ in $(seq 1 30); do
    if psql "$PGURL" -tAc 'SELECT 1' >/dev/null 2>&1; then return 0; fi
    sleep 1
  done
  echo "ERROR: database not reachable at $PGURL"; exit 1
}
wait_db
echo "  db ok"

ensure_server() {
  if curl -sf --max-time 3 "$BASE/health" >/dev/null 2>&1; then
    echo "  server already running at $BASE"; return
  fi
  echo "  starting uvicorn..."
  (cd "$REPO_ROOT" && nohup "$PY" -m uvicorn api_trafix.main:app --host 0.0.0.0 --port 8000 \
     > /tmp/api_trafix_uvicorn.log 2>&1 &)
  for _ in $(seq 1 60); do
    if curl -sf --max-time 3 "$BASE/health" >/dev/null 2>&1; then
      echo "  server up"; return
    fi
    sleep 1
  done
  echo "ERROR: server did not start; see /tmp/api_trafix_uvicorn.log"; exit 1
}
ensure_server

hash_pw() { "$PY" -c 'import sys; from werkzeug.security import generate_password_hash; print(generate_password_hash(sys.argv[1]))' "$1"; }

upsert_user() { # username role status password
  local u="$1" r="$2" s="$3" h
  h="$(hash_pw "$4")"
  psql "$PGURL" -v ON_ERROR_STOP=1 -q -c \
    "INSERT INTO users (id, name, username, password, role, status, created_at, updated_at)
     VALUES (gen_random_uuid(), '$u','$u','$h','$r','$s', now(), now())
     ON CONFLICT (username) DO UPDATE SET password=EXCLUDED.password, role=EXCLUDED.role,
       status=EXCLUDED.status, name=EXCLUDED.name, updated_at=now();"
}

echo "== bootstrap: seed users =="
upsert_user testadmin    admin    active  TestAdmin123!
upsert_user testfinance  finance  active  TestFin123!
upsert_user testteknisi  teknisi  active  TestTek123!
upsert_user testop1      operator active  TestOp12345!
upsert_user testop2      operator active  TestOp67890!
upsert_user testinactive admin    inactive TestInact123!

echo "== bootstrap: ensure gate =="
GATE_ID="$(psql "$PGURL" -tA -c 'SELECT id FROM gates ORDER BY created_at LIMIT 1;')"
if [ -z "$GATE_ID" ]; then
  GATE_ID="$(psql "$PGURL" -tA -c "INSERT INTO gates (name,type,status,created_at,updated_at) VALUES ('Test Gate In','gate_in','online',now(),now()) RETURNING id;")"
fi
save_value gate.id "$GATE_ID"
echo "  gate: $GATE_ID"

echo "== bootstrap: login + capture tokens =="
login_as admin   testadmin    TestAdmin123!
login_as finance testfinance  TestFin123!
login_as teknisi testteknisi  TestTek123!
login_as op1     testop1      TestOp12345!
login_as op2     testop2      TestOp67890!

save_admin_id() { http GET /auth/me "$(get_token admin)"; save_value admin.id "$(json_get id)"; }
save_admin_id
http GET /auth/me "$(get_token op1)"; save_value op1.id "$(json_get id)"
http GET /auth/me "$(get_token op2)"; save_value op2.id "$(json_get id)"
http GET /auth/me "$(get_token finance)"; save_value finance.id "$(json_get id)"
http GET /auth/me "$(get_token teknisi)"; save_value teknisi.id "$(json_get id)"

echo "== bootstrap done =="
