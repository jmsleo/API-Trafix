#!/usr/bin/env bash
# lib.sh - shared helpers for the API-Trafix curl test suite.
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
BASE="${BASE:-http://localhost:8000}"
TOKEN_DIR="$SCRIPT_DIR/.tokens"
BODY_FILE="$SCRIPT_DIR/.last_body"
mkdir -p "$TOKEN_DIR"

PASS=0
FAIL=0
declare -a FAIL_NAMES=()

TAG="${TAG:-$(date +%s)}"

# json_get FIELD... -> reads $BODY, prints nested value (dict/list as JSON)
json_get() {
  BODY="$BODY" python3 -c '
import os, json, sys
try:
    d = json.loads(os.environ["BODY"])
except Exception:
    sys.exit(2)
for k in sys.argv[1:]:
    if isinstance(d, dict) and k in d:
        d = d[k]
    else:
        sys.exit(3)
print(d if not isinstance(d, (dict, list)) else json.dumps(d))
' "$@"
}

# http METHOD PATH [TOKEN] [JSON_BODY] -> sets CODE, BODY
http() {
  local method="$1" path="$2" token="${3:-}" json="${4:-}"
  local curl_args=(-sS -L --max-time 300 -o "$BODY_FILE" -w '%{http_code}' -X "$method" "$BASE$path")
  if [ -n "$token" ]; then curl_args+=(-H "Authorization: Bearer $token"); fi
  if [ -n "$json" ]; then curl_args+=(-H 'Content-Type: application/json' --data "$json"); fi
  CODE="$(curl "${curl_args[@]}")"
  BODY="$(cat "$BODY_FILE" 2>/dev/null || true)"
}

# http_raw METHOD PATH [TOKEN] [extra curl args...] -> sets CODE, BODY (body written to $BODY_FILE)
http_raw() {
  local method="$1" path="$2" token="${3:-}"
  shift 3
  local curl_args=(-sS -L --max-time 300 -o "$BODY_FILE" -w '%{http_code}' -X "$method" "$BASE$path")
  if [ -n "$token" ]; then curl_args+=(-H "Authorization: Bearer $token"); fi
  curl_args+=("$@")
  CODE="$(curl "${curl_args[@]}")"
  BODY="$(cat "$BODY_FILE" 2>/dev/null || true)"
}

# expect NAME EXPECTED_CODE METHOD PATH [TOKEN] [JSON_BODY]
# METHOD may be passed as a single "METHOD PATH" argument.
expect() {
  local name="$1" expected="$2" m="${3:-}" p="${4:-}" t="${5:-}" j="${6:-}"
  local METHOD PATHARG token json
  if [[ "$m" == *" "* ]]; then
    METHOD="${m%% *}"; PATHARG="${m#* }"; token="$p"; json="$t"
  else
    METHOD="$m"; PATHARG="$p"; token="$t"; json="$j"
  fi
  http "$METHOD" "$PATHARG" "$token" "$json"
  if [ "$CODE" = "$expected" ]; then
    PASS=$((PASS + 1))
    printf 'PASS  %-42s %-7s %-52s -> %s\n' "$name" "$METHOD" "$PATHARG" "$expected"
  else
    FAIL=$((FAIL + 1)); FAIL_NAMES+=("$name")
    printf 'FAIL  %-42s %-7s %-52s -> expected %s, got %s\n' "$name" "$METHOD" "$PATHARG" "$expected" "$CODE"
    printf '      body: %s\n' "$BODY"
  fi
}

# expect_body_match NAME METHOD PATH TOKEN JSON_GREP  -> checks HTTP 200 AND grep on body
expect_body_match() {
  local name="$1" method="$2" path="$3" token="${4:-}" json="${5:-}" grep_pat="${6:-}"
  http "$method" "$path" "$token" "$json"
  if [ "$CODE" = "200" ] && printf '%s' "$BODY" | grep -qE "$grep_pat"; then
    PASS=$((PASS + 1))
    printf 'PASS  %-42s %-7s %-52s -> 200 & matches %s\n' "$name" "$method" "$path" "$grep_pat"
  else
    FAIL=$((FAIL + 1)); FAIL_NAMES+=("$name")
    printf 'FAIL  %-42s %-7s %-52s -> got %s, body: %s\n' "$name" "$method" "$path" "$CODE" "$BODY"
  fi
}

save_value() { echo "$2" > "$TOKEN_DIR/$1"; }
get_value() { cat "$TOKEN_DIR/$1" 2>/dev/null; }

save_token() { echo "$2" > "$TOKEN_DIR/$1.token"; }
get_token() { cat "$TOKEN_DIR/$1.token" 2>/dev/null; }

login_as() { # login_as NAME USERNAME PASSWORD
  http POST /auth/login "" "{\"username\":\"$2\",\"password\":\"$3\"}"
  if [ "$CODE" = "200" ]; then
    local t
    t="$(json_get access_token)"
    if [ -z "$t" ]; then
      echo "ERROR: login_as $1 returned empty access_token"; exit 1
    fi
    save_token "$1" "$t"
  else
    echo "ERROR: login_as $1 failed (HTTP $CODE): $BODY"; exit 1
  fi
}

random_uuid() { python3 -c 'import uuid; print(uuid.uuid4())'; }

summary() {
  echo
  echo "================ $SUITE SUMMARY ================"
  echo "PASS: $PASS   FAIL: $FAIL"
  if [ "$FAIL" -gt 0 ]; then
    printf 'Failed scenarios: %s\n' "${FAIL_NAMES[*]}"
    return 1
  fi
  return 0
}
