#!/usr/bin/env bash
# 06_member_relations.sh - member-vehicles, member-subscriptions.
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

echo "== member-vehicles =="
expect "create member vehicle ok"        201 POST /member-vehicles "$ADMIN" "{\"member_id\":\"$MEMBER_ID\",\"vehicle_type_id\":\"$VT_ID\",\"police_number\":\"TST $TAG\"}"
MV_ID="$(json_get id)"
expect "delete vehicle type in use"      409 "DELETE /vehicle-types/$VT_ID" "$ADMIN"
expect "duplicate police number"         400 POST /member-vehicles "$ADMIN" "{\"member_id\":\"$MEMBER_ID\",\"vehicle_type_id\":\"$VT_ID\",\"police_number\":\"TST $TAG\"}"
expect "vehicle for inactive member"     400 POST /member-vehicles "$ADMIN" "{\"member_id\":\"$MEMBER_INACTIVE\",\"vehicle_type_id\":\"$VT_ID\",\"police_number\":\"TST $TAG B\"}"
expect "vehicle with inactive type"      400 POST /member-vehicles "$ADMIN" "{\"member_id\":\"$MEMBER_ID\",\"vehicle_type_id\":\"$VT_INACTIVE\",\"police_number\":\"TST $TAG C\"}"
expect "vehicle unknown member"          404 POST /member-vehicles "$ADMIN" "{\"member_id\":\"$RANDOM_ID\",\"vehicle_type_id\":\"$VT_ID\",\"police_number\":\"TST $TAG D\"}"
expect "vehicle unknown type"            404 POST /member-vehicles "$ADMIN" "{\"member_id\":\"$MEMBER_ID\",\"vehicle_type_id\":\"$RANDOM_ID\",\"police_number\":\"TST $TAG E\"}"
expect "list member vehicles"            200 "GET /member-vehicles?member_id=$MEMBER_ID&page=1&page_size=10" ""
expect "get member vehicle"              200 "GET /member-vehicles/$MV_ID" ""
expect "get member vehicle not found"    404 "GET /member-vehicles/$RANDOM_ID" ""
expect "update member vehicle"           200 "PUT /member-vehicles/$MV_ID" "$ADMIN" "{\"police_number\":\"TST $TAG F\"}"
http POST /member-vehicles "$ADMIN" "{\"member_id\":\"$MEMBER_ID\",\"vehicle_type_id\":\"$VT_ID\",\"police_number\":\"TST $TAG G\"}"
MV2_ID="$(json_get id)"
expect_body_match "member read includes vehicles" GET "/members/$MEMBER_ID" "$ADMIN" "" '"vehicles"'
expect_body_match "member read lists vehicle plate" GET "/members/$MEMBER_ID" "$ADMIN" "" "TST $TAG G"
expect "update duplicate plate"          400 "PUT /member-vehicles/$MV_ID" "$ADMIN" "{\"police_number\":\"TST $TAG G\"}"
expect "update member vehicle not found" 404 "PUT /member-vehicles/$RANDOM_ID" "$ADMIN" '{"police_number":"B 9999 XX"}'
expect "delete member vehicle"           204 "DELETE /member-vehicles/$MV_ID" "$ADMIN"
expect "delete second member vehicle"    204 "DELETE /member-vehicles/$MV2_ID" "$ADMIN"

echo "== member-subscriptions =="
http POST /subscription-plans "$ADMIN" "{\"name\":\"PlanKeep$TAG\",\"duration_in_days\":30,\"price\":100000,\"is_active\":true}"
PLAN_ID="$(json_get id)"
http POST /subscription-plans "$ADMIN" "{\"name\":\"PlanOff$TAG\",\"duration_in_days\":7,\"price\":50000,\"is_active\":false}"
PLAN_INACTIVE="$(json_get id)"
http POST /members "$ADMIN" '{"name":"Joko Widodo Sub","email":"joko@mail.com","status":"active"}'
SUB_MEMBER="$(json_get id)"

expect "create member subscription ok"   201 POST /member-subscriptions "$ADMIN" "{\"member_id\":\"$SUB_MEMBER\",\"plan_id\":\"$PLAN_ID\"}"
MS_ID="$(json_get id)"
expect_body_match "subscription has end_date" GET "/member-subscriptions/$MS_ID" "$ADMIN" "" '"end_date"'
expect "duplicate active subscription"    409 POST /member-subscriptions "$ADMIN" "{\"member_id\":\"$SUB_MEMBER\",\"plan_id\":\"$PLAN_ID\"}"
expect "subscribe inactive member"        400 POST /member-subscriptions "$ADMIN" "{\"member_id\":\"$MEMBER_INACTIVE\",\"plan_id\":\"$PLAN_ID\"}"
expect "subscribe inactive plan"          400 POST /member-subscriptions "$ADMIN" "{\"member_id\":\"$MEMBER_ID\",\"plan_id\":\"$PLAN_INACTIVE\"}"
expect "subscribe unknown member"         404 POST /member-subscriptions "$ADMIN" "{\"member_id\":\"$RANDOM_ID\",\"plan_id\":\"$PLAN_ID\"}"
expect "subscribe unknown plan"           404 POST /member-subscriptions "$ADMIN" "{\"member_id\":\"$SUB_MEMBER\",\"plan_id\":\"$RANDOM_ID\"}"
expect "list member subscriptions"        200 "GET /member-subscriptions?member_id=$SUB_MEMBER&status=active" ""
expect "get member subscription"          200 "GET /member-subscriptions/$MS_ID" ""
expect "get subscription not found"       404 "GET /member-subscriptions/$RANDOM_ID" ""
expect "cancel subscription"              200 "POST /member-subscriptions/$MS_ID/cancel" "$ADMIN"
expect "cancel again (not active)"        400 "POST /member-subscriptions/$MS_ID/cancel" "$ADMIN"
expect "cancel unknown subscription"      404 "POST /member-subscriptions/$RANDOM_ID/cancel" "$ADMIN"
expect "delete subscription"              204 "DELETE /member-subscriptions/$MS_ID" "$ADMIN"

summary
