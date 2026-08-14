#!/usr/bin/env bash
# 02_users.sh - users CRUD, validation, permissions, reset-password.
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/lib.sh"
SUITE="users"

ADMIN="$(get_token admin)"
OP="$(get_token op1)"
RANDOM_ID="$(random_uuid)"

echo "== users: list =="
expect "list users as admin"             200 GET /users "$ADMIN"
expect "list users filters+pagination"   200 "GET /users?search=test&role=operator&status=active&page=1&page_size=5" "$ADMIN"
expect "list users without token"        401 GET /users ""
expect "list users as operator (403)"    403 GET /users "$OP"
expect "list users invalid page"         422 "GET /users?page=0" "$ADMIN"

echo "== users: get =="
expect "get user not found"              404 "GET /users/$RANDOM_ID" "$ADMIN"
expect "get user no token"               401 "GET /users/$RANDOM_ID" ""

echo "== users: create =="
expect "create user ok"                  201 POST /users "$ADMIN" "{\"name\":\"Curl User\",\"username\":\"curl$TAG\",\"role\":\"operator\",\"status\":\"active\",\"password\":\"CurlUser123!\"}"
NEW_ID="$(json_get id)"
save_value curluser.id "$NEW_ID"
expect "create duplicate username"       400 POST /users "$ADMIN" "{\"name\":\"Dup\",\"username\":\"curl$TAG\",\"role\":\"operator\",\"status\":\"active\",\"password\":\"DupUser123!\"}"
expect "create weak password"            422 POST /users "$ADMIN" "{\"name\":\"Weak\",\"username\":\"weak$TAG\",\"role\":\"operator\",\"status\":\"active\",\"password\":\"short\"}"
expect "create invalid role"             422 POST /users "$ADMIN" "{\"name\":\"Bad\",\"username\":\"bad$TAG\",\"role\":\"superadmin\",\"status\":\"active\",\"password\":\"BadUser123!\"}"
expect "create missing fields"           422 POST /users "$ADMIN" '{"name":"NoPass"}'
expect "create without token"            401 POST /users "" "{\"name\":\"X\",\"username\":\"xu$TAG\",\"role\":\"admin\",\"status\":\"active\",\"password\":\"XUser123!\"}"
expect "create as operator (403)"        403 POST /users "$OP" "{\"name\":\"X\",\"username\":\"xu2$TAG\",\"role\":\"admin\",\"status\":\"active\",\"password\":\"XUser123!\"}"

echo "== users: update =="
expect "update user ok"                  200 PUT "/users/$NEW_ID" "$ADMIN" '{"name":"Curl User Updated","status":"inactive"}'
expect "update duplicate username"       400 PUT "/users/$NEW_ID" "$ADMIN" '{"username":"testadmin"}'
expect "update not found"                404 "PUT /users/$RANDOM_ID" "$ADMIN" '{"name":"Ghost"}'
expect "update without token"            401 "PUT /users/$NEW_ID" "" '{"name":"Hax"}'

echo "== users: reset password =="
expect "reset-password ok"               200 POST "/users/$NEW_ID/reset-password" "$ADMIN" '{"password":"NewCurl456!"}'
expect "reset-password not found"        404 "POST /users/$RANDOM_ID/reset-password" "$ADMIN" '{"password":"NewCurl456!"}'
expect "reset-password weak"             422 "POST /users/$NEW_ID/reset-password" "$ADMIN" '{"password":"weak"}'
http POST /users "$ADMIN" "{\"name\":\"Pwd Match\",\"username\":\"Cur$TAG\",\"role\":\"admin\",\"status\":\"active\",\"password\":\"Cur$TAG!!\"}"
PWD_ID="$(json_get id)"
expect "reset-password equals username"  400 "POST /users/$PWD_ID/reset-password" "$ADMIN" "{\"password\":\"Cur$TAG\"}"

echo "== users: delete =="
expect "delete user ok"                  204 "DELETE /users/$NEW_ID" "$ADMIN"
expect "delete user again (404)"         404 "DELETE /users/$NEW_ID" "$ADMIN"
expect "delete without token"            401 "DELETE /users/$PWD_ID" ""
expect "delete as operator (403)"        403 "DELETE /users/$PWD_ID" "$OP"

summary
