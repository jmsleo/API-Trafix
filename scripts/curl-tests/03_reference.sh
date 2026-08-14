#!/usr/bin/env bash
# 03_reference.sh - vehicle-types, shifts, members.
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/lib.sh"
SUITE="reference"

ADMIN="$(get_token admin)"
RANDOM_ID="$(random_uuid)"

echo "== vehicle-types =="
expect "create vehicle type ok"          201 POST /vehicle-types "$ADMIN" '{"code":"TSTMTR","name":"Test Motor","status":"active"}'
VT_ID="$(json_get id)"
expect "create second vehicle type"      201 POST /vehicle-types "$ADMIN" '{"code":"TSTMOB","name":"Test Mobil","status":"active"}'
VT2_ID="$(json_get id)"
expect "create duplicate code"           400 POST /vehicle-types "$ADMIN" '{"code":"TSTMTR","name":"Test Motor 2","status":"active"}'
expect "create missing fields"           422 POST /vehicle-types "$ADMIN" '{"name":"NoCode"}'
expect "create bad status"               422 POST /vehicle-types "$ADMIN" '{"code":"BIC","name":"Bicycle","status":"broken"}'
expect "list vehicle types"              200 "GET /vehicle-types?search=TSTMTR&status=active&page=1&page_size=10" "$ADMIN"
expect "get vehicle type"                200 "GET /vehicle-types/$VT_ID" "$ADMIN"
expect "get vehicle type not found"      404 "GET /vehicle-types/$RANDOM_ID" "$ADMIN"
expect "update vehicle type"             200 "PUT /vehicle-types/$VT_ID" "$ADMIN" '{"name":"Test Motor Matic"}'
expect "update duplicate code"           400 "PUT /vehicle-types/$VT_ID" "$ADMIN" '{"code":"TSTMOB"}'
expect "update not found"                404 "PUT /vehicle-types/$RANDOM_ID" "$ADMIN" '{"name":"X"}'
expect "delete vehicle type"             204 "DELETE /vehicle-types/$VT_ID" "$ADMIN"
expect "delete vehicle type again"       404 "DELETE /vehicle-types/$VT_ID" "$ADMIN"
expect "delete second vehicle type"      204 "DELETE /vehicle-types/$VT2_ID" "$ADMIN"

echo "== shifts =="
expect "create shift ok"                 201 POST /shifts "$ADMIN" "{\"name\":\"Pagi$TAG\",\"start_time\":\"06:00:00\",\"finish_time\":\"14:00:00\",\"crosses_midnight\":false,\"status\":\"active\"}"
SHIFT_ID="$(json_get id)"
expect "create shift crossing midnight"  201 POST /shifts "$ADMIN" "{\"name\":\"Malam$TAG\",\"start_time\":\"22:00:00\",\"finish_time\":\"06:00:00\",\"crosses_midnight\":true,\"status\":\"active\"}"
SHIFT_ID2="$(json_get id)"
expect "create shift invalid order"      422 POST /shifts "$ADMIN" '{"name":"BadShift","start_time":"14:00:00","finish_time":"06:00:00","crosses_midnight":false,"status":"active"}'
expect "create duplicate name"           400 POST /shifts "$ADMIN" "{\"name\":\"Pagi$TAG\",\"start_time\":\"06:00:00\",\"finish_time\":\"14:00:00\",\"crosses_midnight\":false,\"status\":\"active\"}"
expect "list shifts"                     200 "GET /shifts?search=Pagi$TAG&status=active" "$ADMIN"
expect "get shift"                       200 "GET /shifts/$SHIFT_ID" "$ADMIN"
expect "get shift not found"             404 "GET /shifts/$RANDOM_ID" "$ADMIN"
expect "update shift"                    200 "PUT /shifts/$SHIFT_ID" "$ADMIN" "{\"name\":\"PagiA$TAG\"}"
expect "update shift bad time"           422 "PUT /shifts/$SHIFT_ID" "$ADMIN" '{"start_time":"20:00:00","finish_time":"08:00:00","crosses_midnight":false}'
expect "delete shift"                    204 "DELETE /shifts/$SHIFT_ID" "$ADMIN"
expect "delete shift again"              404 "DELETE /shifts/$SHIFT_ID" "$ADMIN"
expect "delete midnight shift"           204 "DELETE /shifts/$SHIFT_ID2" "$ADMIN"

echo "== members =="
expect "create member ok"                201 POST /members "$ADMIN" '{"name":"Budi Santoso","email":"budi@mail.com","phone_number":"081234567890","status":"active"}'
MEMBER_ID="$(json_get id)"
MEMBER_CODE="$(json_get member_code)"
[ -n "$MEMBER_CODE" ] && { PASS=$((PASS+1)); printf 'PASS  %-42s -> member_code generated: %s\n' "create member returns member_code" "$MEMBER_CODE"; } \
  || { FAIL=$((FAIL+1)); FAIL_NAMES+=("member_code"); echo "FAIL  create member missing member_code"; }
expect "create member missing status"    422 POST /members "$ADMIN" '{"name":"No Status"}'
expect "create member bad email"         422 POST /members "$ADMIN" '{"name":"Bad Email","email":"not-an-email","status":"active"}'
expect "list members"                    200 "GET /members?search=Budi&status=active" "$ADMIN"
expect "get member"                      200 "GET /members/$MEMBER_ID" "$ADMIN"
expect "get member not found"            404 "GET /members/$RANDOM_ID" "$ADMIN"
expect "update member"                   200 "PUT /members/$MEMBER_ID" "$ADMIN" '{"name":"Budi Santoso SE"}'
expect "update member not found"         404 "PUT /members/$RANDOM_ID" "$ADMIN" '{"name":"Ghost"}'
expect "block member"                    200 "PATCH /members/$MEMBER_ID/block" "$ADMIN"
expect "block member idempotent"         200 "PATCH /members/$MEMBER_ID/block" "$ADMIN"
expect "block member not found"          404 "PATCH /members/$RANDOM_ID/block" "$ADMIN"
expect "delete member"                   204 "DELETE /members/$MEMBER_ID" "$ADMIN"
expect "delete member again"             404 "DELETE /members/$MEMBER_ID" "$ADMIN"

summary
