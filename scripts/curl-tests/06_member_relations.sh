#!/usr/bin/env bash
# 06_member_relations.sh - member vehicles (via /members), member-subscriptions.
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/lib.sh"
SUITE="member-relations"

ADMIN="$(get_token admin)"
RANDOM_ID="$(random_uuid)"

echo "== member-relations: fixtures =="
http POST /members "$ADMIN" '{"name":"Siti Aminah","email":"siti@mail.com","status":"active"}'
MEMBER_ID="$(json_get id)"
http POST /members "$ADMIN" '{"name":"User Inactive","status":"inactive"}'
MEMBER_INACTIVE="$(json_get id)"
http POST /vehicle-types "$ADMIN" "{\"code\":\"MTR$TAG\",\"name\":\"Motor\",\"status\":\"active\"}"
VT_ID="$(json_get id)"
http POST /vehicle-types "$ADMIN" "{\"code\":\"SEP$TAG\",\"name\":\"Sepeda\",\"status\":\"inactive\"}"
VT_INACTIVE="$(json_get id)"
http POST /subscription-plans "$ADMIN" "{\"name\":\"PlanKeep$TAG\",\"duration_in_days\":30,\"price\":100000,\"is_active\":true}"
PLAN_ID="$(json_get id)"
http POST /subscription-plans "$ADMIN" "{\"name\":\"PlanOff$TAG\",\"duration_in_days\":7,\"price\":50000,\"is_active\":false}"
PLAN_INACTIVE="$(json_get id)"

echo "== member vehicles (via /members) =="
http POST /members "$ADMIN" "{\"name\":\"Tukul Arwana\",\"status\":\"active\",\"police_number\":\"TST $TAG\",\"vehicle_type_id\":\"$VT_ID\"}"
MV_MEMBER="$(json_get id)"
expect "delete vehicle type in use"       409 "DELETE /vehicle-types/$VT_ID" "$ADMIN"
expect "create member duplicate plate"    400 POST /members "$ADMIN" "{\"name\":\"Dup Plate\",\"status\":\"active\",\"police_number\":\"TST $TAG\",\"vehicle_type_id\":\"$VT_ID\"}"
expect "create member inactive type"      400 POST /members "$ADMIN" "{\"name\":\"Inact Type\",\"status\":\"active\",\"police_number\":\"TST $TAG B\",\"vehicle_type_id\":\"$VT_INACTIVE\"}"
expect "create member unknown type"       404 POST /members "$ADMIN" "{\"name\":\"Unknown Type\",\"status\":\"active\",\"police_number\":\"TST $TAG C\",\"vehicle_type_id\":\"$RANDOM_ID\"}"
expect "create member only plate"         422 POST /members "$ADMIN" "{\"name\":\"No Type\",\"status\":\"active\",\"police_number\":\"TST $TAG D\"}"
expect "create member only type"          422 POST /members "$ADMIN" "{\"name\":\"No Plate\",\"status\":\"active\",\"vehicle_type_id\":\"$VT_ID\"}"
expect_body_match "member read includes vehicle" GET "/members/$MV_MEMBER" "$ADMIN" "" '"vehicles"'
expect_body_match "member read lists plate" GET "/members/$MV_MEMBER" "$ADMIN" "" "TST $TAG"

echo "== member subscriptions (via /members) =="
http POST /members "$ADMIN" "{\"name\":\"Susilo Sub\",\"email\":\"susilo@mail.com\",\"status\":\"active\",\"plan_id\":\"$PLAN_ID\"}"
SUB_MEMBER="$(json_get id)"
expect "create member with subscription ok"  201 POST /members "$ADMIN" "{\"name\":\"Soeharto Sub\",\"status\":\"active\",\"plan_id\":\"$PLAN_ID\"}"
expect_body_match "member read includes subscription" GET "/members/$SUB_MEMBER" "$ADMIN" "" '"subscriptions"'
expect "member with inactive plan"           400 POST /members "$ADMIN" "{\"name\":\"Plan Off\",\"status\":\"active\",\"plan_id\":\"$PLAN_INACTIVE\"}"
expect "member with unknown plan"            404 POST /members "$ADMIN" "{\"name\":\"Unknown Plan\",\"status\":\"active\",\"plan_id\":\"$RANDOM_ID\"}"
expect "inactive member with plan"           400 POST /members "$ADMIN" "{\"name\":\"Inactive With Plan\",\"status\":\"inactive\",\"plan_id\":\"$PLAN_ID\"}"

echo "== member-subscriptions =="
http POST /members "$ADMIN" '{"name":"Joko Widodo Sub","email":"joko@mail.com","status":"active"}'
SUB2_MEMBER="$(json_get id)"

expect "create member subscription ok"   201 POST /member-subscriptions "$ADMIN" "{\"member_id\":\"$SUB2_MEMBER\",\"plan_id\":\"$PLAN_ID\"}"
MS_ID="$(json_get id)"
expect_body_match "subscription has end_date" GET "/member-subscriptions/$MS_ID" "$ADMIN" "" '"end_date"'
expect "duplicate active subscription"    409 POST /member-subscriptions "$ADMIN" "{\"member_id\":\"$SUB2_MEMBER\",\"plan_id\":\"$PLAN_ID\"}"
expect "subscribe inactive member"        400 POST /member-subscriptions "$ADMIN" "{\"member_id\":\"$MEMBER_INACTIVE\",\"plan_id\":\"$PLAN_ID\"}"
expect "subscribe inactive plan"          400 POST /member-subscriptions "$ADMIN" "{\"member_id\":\"$SUB2_MEMBER\",\"plan_id\":\"$PLAN_INACTIVE\"}"
expect "subscribe unknown member"         404 POST /member-subscriptions "$ADMIN" "{\"member_id\":\"$RANDOM_ID\",\"plan_id\":\"$PLAN_ID\"}"
expect "subscribe unknown plan"           404 POST /member-subscriptions "$ADMIN" "{\"member_id\":\"$SUB2_MEMBER\",\"plan_id\":\"$RANDOM_ID\"}"
expect "list member subscriptions"        200 "GET /member-subscriptions?member_id=$SUB2_MEMBER&status=active" ""
expect "get member subscription"          200 "GET /member-subscriptions/$MS_ID" ""
expect "get subscription not found"       404 "GET /member-subscriptions/$RANDOM_ID" ""
expect "cancel subscription"              200 "POST /member-subscriptions/$MS_ID/cancel" "$ADMIN"
expect "cancel again (not active)"        400 "POST /member-subscriptions/$MS_ID/cancel" "$ADMIN"
expect "cancel unknown subscription"      404 "POST /member-subscriptions/$RANDOM_ID/cancel" "$ADMIN"
expect "delete subscription"              204 "DELETE /member-subscriptions/$MS_ID" "$ADMIN"

summary
