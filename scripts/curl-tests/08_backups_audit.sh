#!/usr/bin/env bash
# 08_backups_audit.sh - backups (create/upload/download/restore/delete) + audit-logs.
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/lib.sh"
SUITE="backups-audit"

ADMIN="$(get_token admin)"
OP="$(get_token op1)"
RANDOM_ID="$(random_uuid)"
TMPDIR="$SCRIPT_DIR/.tmp"
mkdir -p "$TMPDIR"

# wait_backup_status ID TOKEN EXPECTED_STATUS NAME -> polls GET /backups/ID until status stops changing or timeout
wait_backup_status() {
  local id="$1" token="$2" expected="$3" name="$4"
  local tries=0 prev=""
  while [ "$tries" -lt 60 ]; do
    http GET "/backups/$id" "$token"
    local st
    st="$(json_get status 2>/dev/null || true)"
    if [ -n "$st" ] && [ "$st" != "running" ]; then
      prev="$st"
      break
    fi
    tries=$((tries + 1))
    sleep 1
  done
  if [ -n "$prev" ] && [ "$prev" = "$expected" ]; then
    PASS=$((PASS+1)); printf 'PASS  %-42s -> %s\n' "$name" "$prev"
  else
    FAIL=$((FAIL+1)); FAIL_NAMES+=("$name")
    printf 'FAIL  %-42s -> expected %s, got %s\n' "$name" "$expected" "${prev:-timeout}"
  fi
}

# wait_backup_done ID TOKEN NAME -> polls until status is not running; tolerates transient 5xx during restore
wait_backup_done() {
  local id="$1" token="$2" name="$3"
  local tries=0
  while [ "$tries" -lt 60 ]; do
    http GET "/backups/$id" "$token"
    if [ "$CODE" = "200" ]; then
      local st
      st="$(json_get status 2>/dev/null || true)"
      if [ -n "$st" ] && [ "$st" != "running" ]; then
        PASS=$((PASS+1)); printf 'PASS  %-42s -> %s\n' "$name" "$st"
        return 0
      fi
    fi
    tries=$((tries + 1))
    sleep 1
  done
  FAIL=$((FAIL+1)); FAIL_NAMES+=("$name")
  printf 'FAIL  %-42s -> timed out waiting (last HTTP %s)\n' "$name" "$CODE"
}

echo "== backups =="
expect "list backups without token"      401 GET /backups ""
expect "list backups as operator"        403 GET /backups "$OP"
expect "list backups as admin"           200 GET /backups "$ADMIN"

expect "create backup ok (async 202)"    202 POST /backups "$ADMIN"
BK_ID="$(json_get id)"
[ -n "$BK_ID" ] && [ "$BK_ID" != "null" ] && { PASS=$((PASS+1)); printf 'PASS  %-42s -> %s\n' "create backup returns id" "$BK_ID"; } \
  || { FAIL=$((FAIL+1)); FAIL_NAMES+=("backup id"); echo "FAIL  create backup missing id: $BODY"; }
expect "get backup"                      200 "GET /backups/$BK_ID" "$ADMIN"
expect "get backup not found"            404 "GET /backups/$RANDOM_ID" "$ADMIN"

wait_backup_done "$BK_ID" "$ADMIN" "create backup finishes (completed)"
wait_backup_status "$BK_ID" "$ADMIN" completed "create backup ends completed"

http_raw GET "/backups/$BK_ID/download" "$ADMIN"
if [ "$CODE" = "200" ] && [ -s "$BODY_FILE" ]; then
  PASS=$((PASS+1)); printf 'PASS  %-42s -> %s (file %s bytes)\n' "download backup" "200" "$(wc -c < "$BODY_FILE")"
else
  FAIL=$((FAIL+1)); FAIL_NAMES+=("download backup")
  printf 'FAIL  %-42s -> expected 200 & non-empty file, got %s\n' "download backup" "$CODE"
fi

expect "restore requires confirm"        400 "POST /backups/$BK_ID/restore" "$ADMIN" '{"confirm":false}'
expect "restore unknown backup"          404 "POST /backups/$RANDOM_ID/restore" "$ADMIN" '{"confirm":true}'

printf -- '-- Restore sentinel --\nSELECT 1;\n' > "$TMPDIR/restore_test.sql"
http_raw POST /backups/upload "$ADMIN" -F "file=@$TMPDIR/restore_test.sql;type=text/plain"
if [ "$CODE" = "201" ]; then
  PASS=$((PASS+1)); printf 'PASS  %-42s -> %s\n' "upload backup (multipart)" "$CODE"
  UP_ID="$(json_get id)"
else
  FAIL=$((FAIL+1)); FAIL_NAMES+=("upload backup")
  printf 'FAIL  %-42s -> expected 201, got %s (%s)\n' "upload backup (multipart)" "$CODE" "$BODY"
fi

: > "$TMPDIR/empty.sql"
http_raw POST /backups/upload "$ADMIN" -F "file=@$TMPDIR/empty.sql;type=text/plain"
if [ "$CODE" = "400" ]; then
  PASS=$((PASS+1)); printf 'PASS  %-42s -> %s\n' "upload empty file rejected" "$CODE"
else
  FAIL=$((FAIL+1)); FAIL_NAMES+=("upload empty")
  printf 'FAIL  %-42s -> expected 400, got %s (%s)\n' "upload empty file rejected" "$CODE" "$BODY"
fi

if [ -n "${UP_ID:-}" ] && [ "$UP_ID" != "null" ]; then
  expect "delete uploaded backup"        204 "DELETE /backups/$UP_ID" "$ADMIN"
fi
expect "delete backup not found"         404 "DELETE /backups/$RANDOM_ID" "$ADMIN"

echo "== backups: destructive restore (last) =="
expect "restore with confirm true (async 202)" 202 "POST /backups/$BK_ID/restore" "$ADMIN" '{"confirm":true}'
wait_backup_done "$BK_ID" "$ADMIN" "restore finishes (completed)"
expect "api healthy after restore"       200 GET /health ""

echo "== audit-logs =="
expect "audit-logs without token"        401 GET /audit-logs ""
expect "audit-logs as operator"          403 GET /audit-logs "$OP"
expect "audit-logs as admin"             200 GET /audit-logs "$ADMIN"
expect "audit-logs filters"              200 "GET /audit-logs?module=user&action=create&page=1&page_size=5" "$ADMIN"
expect "audit-logs date filter"          200 "GET /audit-logs?date_from=2000-01-01T00:00:00Z&date_to=2100-01-01T00:00:00Z" "$ADMIN"
expect "audit-log not found"             404 "GET /audit-logs/$RANDOM_ID" "$ADMIN"
http GET /audit-logs "$ADMIN"
FIRST_AUDIT="$(json_get items 2>/dev/null)"
AUDIT_ID="$(printf '%s' "$FIRST_AUDIT" | python3 -c 'import sys,json
try: print(json.load(sys.stdin)[0]["id"])
except Exception: pass')"
if [ -n "$AUDIT_ID" ]; then
  expect "get audit-log by id"           200 "GET /audit-logs/$AUDIT_ID" "$ADMIN"
else
  FAIL=$((FAIL+1)); FAIL_NAMES+=("audit id")
  echo "FAIL  could not extract audit-log id from list"
fi

rm -rf "$TMPDIR"
summary
