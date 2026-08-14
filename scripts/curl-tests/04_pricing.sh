#!/usr/bin/env bash
# 04_pricing.sh - parking-rates, subscription-plans.
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/lib.sh"
SUITE="pricing"

ADMIN="$(get_token admin)"
RANDOM_ID="$(random_uuid)"

http POST /vehicle-types "$ADMIN" "{\"code\":\"MTR$TAG\",\"name\":\"Motor\",\"status\":\"active\"}"
VT_ID="$(json_get id)"

echo "== parking-rates =="
expect "create parking rate ok"          201 POST /parking-rates "$ADMIN" "{\"name\":\"Motor 1 Jam\",\"vehicle_type_id\":\"$VT_ID\",\"base_price\":3000,\"status\":\"active\"}"
RATE_ID="$(json_get id)"
expect "create rate invalid vehicle_type" 400 POST /parking-rates "$ADMIN" "{\"name\":\"Bad Rate\",\"vehicle_type_id\":\"$RANDOM_ID\",\"base_price\":1000}"
expect "create rate negative price"      422 POST /parking-rates "$ADMIN" "{\"name\":\"Neg\",\"vehicle_type_id\":\"$VT_ID\",\"base_price\":-5}"
expect "list parking rates"              200 "GET /parking-rates?search=Motor&status=active" "$ADMIN"
expect "get parking rate"                200 "GET /parking-rates/$RATE_ID" "$ADMIN"
expect "get parking rate not found"      404 "GET /parking-rates/$RANDOM_ID" "$ADMIN"
expect "update parking rate"             200 "PUT /parking-rates/$RATE_ID" "$ADMIN" '{"base_price":4000}'
expect "update rate bad vehicle_type"    400 "PUT /parking-rates/$RATE_ID" "$ADMIN" "{\"vehicle_type_id\":\"$RANDOM_ID\"}"
expect "patch rate status inactive"      200 "PATCH /parking-rates/$RATE_ID/status" "$ADMIN" '{"status":"inactive"}'
expect "patch rate status not found"     404 "PATCH /parking-rates/$RANDOM_ID/status" "$ADMIN" '{"status":"inactive"}'
expect "delete parking rate"             204 "DELETE /parking-rates/$RATE_ID" "$ADMIN"

echo "== subscription-plans =="
expect "create plan ok"                  201 POST /subscription-plans "$ADMIN" "{\"name\":\"Bulanan$TAG\",\"duration_in_days\":30,\"price\":150000,\"is_active\":true}"
PLAN_ID="$(json_get id)"
save_value plan.id "$PLAN_ID"
expect "create duplicate plan name"      400 POST /subscription-plans "$ADMIN" "{\"name\":\"Bulanan$TAG\",\"duration_in_days\":30,\"price\":150000}"
expect "create plan zero duration"       422 POST /subscription-plans "$ADMIN" '{"name":"Instant","duration_in_days":0,"price":1000}'
expect "create plan negative price"      422 POST /subscription-plans "$ADMIN" '{"name":"Neg","duration_in_days":7,"price":-1}'
expect "list subscription plans"         200 "GET /subscription-plans?search=Bulanan$TAG&is_active=true" "$ADMIN"
expect "get subscription plan"           200 "GET /subscription-plans/$PLAN_ID" "$ADMIN"
expect "get plan not found"              404 "GET /subscription-plans/$RANDOM_ID" "$ADMIN"
expect "update plan"                     200 "PUT /subscription-plans/$PLAN_ID" "$ADMIN" '{"price":175000}'
expect "patch plan deactivate"           200 "PATCH /subscription-plans/$PLAN_ID/status" "$ADMIN" '{"is_active":false}'
expect "patch plan reactivate"           200 "PATCH /subscription-plans/$PLAN_ID/status" "$ADMIN" '{"is_active":true}'
expect "patch plan not found"            404 "PATCH /subscription-plans/$RANDOM_ID/status" "$ADMIN" '{"is_active":false}'

http POST /subscription-plans "$ADMIN" "{\"name\":\"Temp$TAG\",\"duration_in_days\":7,\"price\":50000}"
TMP_PLAN="$(json_get id)"
expect "delete plan ok"                  204 "DELETE /subscription-plans/$TMP_PLAN" "$ADMIN"
expect "delete plan not found"           404 "DELETE /subscription-plans/$TMP_PLAN" "$ADMIN"

summary
