#!/usr/bin/env bash
# 05_operator.sh - operator-shift assignments + operator sessions.
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/lib.sh"
SUITE="operator"

ADMIN="$(get_token admin)"
OP1="$(get_token op1)"
OP2="$(get_token op2)"
OP1_ID="$(get_value op1.id)"
ADMIN_ID="$(get_value admin.id)"
GATE_ID="$(get_value gate.id)"
RANDOM_ID="$(random_uuid)"

PGURL="${DATABASE_URL:-postgresql://trafix:trafix@localhost:5432/trafix}"
PGURL="${PGURL/+asyncpg/}"
INACTIVE_ID="$(psql "$PGURL" -tA -c "SELECT id FROM users WHERE username='testinactive';")"

http POST /shifts "$ADMIN" "{\"name\":\"Ops$TAG\",\"start_time\":\"08:00:00\",\"finish_time\":\"16:00:00\",\"crosses_midnight\":false,\"status\":\"active\"}"
SHIFT_ID="$(json_get id)"

echo "== operator-shifts =="
expect "assign operator to shift"        201 POST /operator-shifts "$ADMIN" "{\"operator_id\":\"$OP1_ID\",\"shift_id\":\"$SHIFT_ID\"}"
OSA_ID="$(json_get id)"
expect "assign duplicate operator+shift" 409 POST /operator-shifts "$ADMIN" "{\"operator_id\":\"$OP1_ID\",\"shift_id\":\"$SHIFT_ID\"}"
expect "assign non-operator user"        400 POST /operator-shifts "$ADMIN" "{\"operator_id\":\"$ADMIN_ID\",\"shift_id\":\"$SHIFT_ID\"}"
expect "assign inactive operator"        400 POST /operator-shifts "$ADMIN" "{\"operator_id\":\"$INACTIVE_ID\",\"shift_id\":\"$SHIFT_ID\"}"
expect "assign unknown operator"         404 POST /operator-shifts "$ADMIN" "{\"operator_id\":\"$RANDOM_ID\",\"shift_id\":\"$SHIFT_ID\"}"
expect "assign unknown shift"            404 POST /operator-shifts "$ADMIN" "{\"operator_id\":\"$OP1_ID\",\"shift_id\":\"$RANDOM_ID\"}"
expect "list operator-shifts"            200 "GET /operator-shifts?operator_id=$OP1_ID" ""
expect "get operator-shift"              200 "GET /operator-shifts/$OSA_ID" ""
expect "get operator-shift not found"    404 "GET /operator-shifts/$RANDOM_ID" ""
expect "delete operator-shift"           204 "DELETE /operator-shifts/$OSA_ID" "$ADMIN"
expect "delete operator-shift again"     404 "DELETE /operator-shifts/$OSA_ID" "$ADMIN"

echo "== operator-sessions =="
expect "start session ok"                201 POST /operator-sessions/start "$OP1" "{\"shift_id\":\"$SHIFT_ID\",\"gate_id\":\"$GATE_ID\"}"
SESS_ID="$(json_get id)"
expect "start session duplicate (active)" 409 POST /operator-sessions/start "$OP1" "{\"shift_id\":\"$SHIFT_ID\",\"gate_id\":\"$GATE_ID\"}"
expect "start session unknown shift"     404 POST /operator-sessions/start "$OP1" "{\"shift_id\":\"$RANDOM_ID\",\"gate_id\":\"$GATE_ID\"}"
expect "start session unknown gate"      404 POST /operator-sessions/start "$OP1" "{\"shift_id\":\"$SHIFT_ID\",\"gate_id\":\"$RANDOM_ID\"}"
expect "start as non-operator (403)"     403 POST /operator-sessions/start "$ADMIN" "{\"shift_id\":\"$SHIFT_ID\",\"gate_id\":\"$GATE_ID\"}"
expect "list operator-sessions public"   200 "GET /operator-sessions?status=active" ""
expect "get operator-session public"     200 "GET /operator-sessions/$SESS_ID" ""
expect "get operator-session not found"  404 "GET /operator-sessions/$RANDOM_ID" ""
expect "end session as other operator"   403 "POST /operator-sessions/$SESS_ID/end" "$OP2"
expect "end session as owner"            200 "POST /operator-sessions/$SESS_ID/end" "$OP1"
expect "end session again (already closed)" 400 "POST /operator-sessions/$SESS_ID/end" "$OP1"
expect "end unknown session"             404 "POST /operator-sessions/$RANDOM_ID/end" "$OP1"

summary
