#!/usr/bin/env bash
# 01_auth.sh - login, me, refresh rotation, logout, replay, lockout.
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/lib.sh"
SUITE="auth"

ADMIN="$(get_token admin)"
BAD="not-a-real-token"
GARBAGE="eyJhbGciOiJIUzI1NiJ9.invalid.signature"

echo "== auth: login =="
expect "login admin ok"                  200 POST /auth/login "" '{"username":"testadmin","password":"TestAdmin123!"}'
expect "login wrong credentials"         401 POST /auth/login "" '{"username":"nobody","password":"WrongPass123"}'
expect "login missing password"          422 POST /auth/login "" '{"username":"testadmin"}'
expect "login invalid json"              422 POST /auth/login "" '{"username":}'
expect "login inactive user blocked"     403 POST /auth/login "" '{"username":"testinactive","password":"TestInact123!"}'

echo "== auth: me =="
expect "me without token"                401 GET /auth/me ""
expect "me with garbage token"           401 GET /auth/me "$GARBAGE"
expect "me as admin"                     200 GET /auth/me "$ADMIN"
expect "me as operator"                  200 GET /auth/me "$(get_token op1)"
expect_body_match "login writes audit log" GET "/audit-logs?module=auth&action=login&page=1&page_size=5" "$ADMIN" "" '"action":"login"'

echo "== auth: refresh rotation =="
http POST /auth/login "" '{"username":"testadmin","password":"TestAdmin123!"}'
OLD_REFRESH="$(json_get refresh_token)"
REFRESHED_AT="$(json_get access_token)"
expect "refresh valid token"             200 POST /auth/refresh "" "{\"refresh_token\":\"$OLD_REFRESH\"}"
NEW_REFRESH="$(json_get refresh_token)"
expect "refresh token rotation (replay)" 401 POST /auth/refresh "" "{\"refresh_token\":\"$OLD_REFRESH\"}"
expect "refresh with garbage"            401 POST /auth/refresh "" "{\"refresh_token\":\"$GARBAGE\"}"
expect "refresh missing token"           422 POST /auth/refresh "" '{}'

echo "== auth: logout =="
http POST /auth/login "" '{"username":"testadmin","password":"TestAdmin123!"}'
LG_ACCESS="$(json_get access_token)"
LG_REFRESH="$(json_get refresh_token)"
expect "logout with valid tokens"        204 POST /auth/logout "" "{\"refresh_token\":\"$LG_REFRESH\",\"access_token\":\"$LG_ACCESS\"}"
expect "refresh after logout (jti gone)" 401 POST /auth/refresh "" "{\"refresh_token\":\"$LG_REFRESH\"}"
expect "logout is idempotent (replay 204)" 204 POST /auth/logout "" "{\"refresh_token\":\"$LG_REFRESH\"}"
expect "logout with garbage token"       401 POST /auth/logout "" "{\"refresh_token\":\"$GARBAGE\"}"
expect "logout missing refresh"          422 POST /auth/logout "" '{}'
expect_body_match "logout writes audit log" GET "/audit-logs?module=auth&action=logout&page=1&page_size=5" "$ADMIN" "" '"action":"logout"'

echo "== auth: rate limit lockout (6th consecutive failure) =="
docker exec api-trafix-redis redis-cli FLUSHDB >/dev/null 2>&1 || true
for i in 1 2 3 4 5; do
  expect "lockout attempt $i (fail)"     401 POST /auth/login "" '{"username":"ratelimituser","password":"WrongPass1"}'
done
expect "lockout triggered (429)"         429 POST /auth/login "" '{"username":"ratelimituser","password":"WrongPass1"}'
expect "login works after flush"         200 POST /auth/login "" '{"username":"testadmin","password":"TestAdmin123!"}'

summary
