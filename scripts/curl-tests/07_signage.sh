#!/usr/bin/env bash
# 07_signage.sh - signages, contents, assignments, schedules.
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/lib.sh"
SUITE="signage"

ADMIN="$(get_token admin)"
RANDOM_ID="$(random_uuid)"

echo "== signages =="
expect "create signage ok"               201 POST /signages "$ADMIN" "{\"name\":\"Gate A Screen\",\"code\":\"SCR$TAG\",\"location\":\"Gate A\",\"status\":\"active\"}"
SG_ID="$(json_get id)"
expect "create second signage"           201 POST /signages "$ADMIN" "{\"name\":\"Gate B Screen\",\"code\":\"SCR2$TAG\",\"location\":\"Gate B\",\"status\":\"active\"}"
SG2_ID="$(json_get id)"
expect "create duplicate signage code"   400 POST /signages "$ADMIN" "{\"name\":\"Dup Screen\",\"code\":\"SCR$TAG\",\"status\":\"active\"}"
expect "create signage missing name"     422 POST /signages "$ADMIN" "{\"code\":\"SCR3$TAG\"}"
expect "list signages"                   200 "GET /signages?page=1&page_size=10" "$ADMIN"
expect "get signage"                     200 "GET /signages/$SG_ID" "$ADMIN"
expect "get signage not found"           404 "GET /signages/$RANDOM_ID" "$ADMIN"
expect "update signage"                  200 "PUT /signages/$SG_ID" "$ADMIN" '{"location":"Gate A Main","status":"active"}'
expect "update signage duplicate code"   400 "PUT /signages/$SG_ID" "$ADMIN" "{\"code\":\"SCR2$TAG\"}"
expect "patch signage status"            200 "PATCH /signages/$SG_ID/status" "$ADMIN" '{"status":"inactive"}'
expect "patch signage status reactivate" 200 "PATCH /signages/$SG_ID/status" "$ADMIN" '{"status":"active"}'

echo "== signage contents =="
expect "create content ok"               201 POST /signages/contents "$ADMIN" '{"title":"Promo Diskon","content_type":"text","body":"Diskon 50% semua kendaraan","is_active":true}'
CT_ID="$(json_get id)"
expect "create content empty title"      422 POST /signages/contents "$ADMIN" '{"title":"","body":"x"}'
expect "list contents"                   200 "GET /signages/contents?page=1&page_size=10" "$ADMIN"
expect "get content"                     200 "GET /signages/contents/$CT_ID" "$ADMIN"
expect "get content not found"           404 "GET /signages/contents/$RANDOM_ID" "$ADMIN"
expect "update content"                  200 "PUT /signages/contents/$CT_ID" "$ADMIN" '{"title":"Promo Diskon Baru"}'
expect "patch content status"            200 "PATCH /signages/contents/$CT_ID/status" "$ADMIN" '{"is_active":false}'
expect "patch content status on"         200 "PATCH /signages/contents/$CT_ID/status" "$ADMIN" '{"is_active":true}'

echo "== signage media upload =="
TMPDIR="$SCRIPT_DIR/.tmp"
mkdir -p "$TMPDIR"
printf 'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg==' | base64 -d > "$TMPDIR/pixel.png"
printf 'FAKEVIDEODATA' > "$TMPDIR/clip.mp4"
: > "$TMPDIR/empty.png"

http_raw POST /signages/contents/upload "$ADMIN" -F "title=Logo Gate$TAG" -F "content_type=image" -F "file=@$TMPDIR/pixel.png;type=image/png"
if [ "$CODE" = "201" ]; then
  PASS=$((PASS+1)); printf 'PASS  %-42s -> %s\n' "upload image content (multipart)" "$CODE"
  IMG_ID="$(json_get id)"
  IMG_MT="$(json_get mime_type)"
  IMG_FP="$(json_get file_path)"
  IMG_SZ="$(json_get file_size_bytes)"
else
  FAIL=$((FAIL+1)); FAIL_NAMES+=("upload image")
  printf 'FAIL  %-42s -> expected 201, got %s (%s)\n' "upload image content (multipart)" "$CODE" "$BODY"
fi
if [ -n "$IMG_ID" ] && [ "$IMG_MT" = "image/png" ] && [ -n "$IMG_FP" ] && [ "$IMG_SZ" = "70" ]; then
  PASS=$((PASS+1)); printf 'PASS  %-42s -> %s\n' "uploaded image metadata (png, size)" "$IMG_SZ bytes"
else
  FAIL=$((FAIL+1)); FAIL_NAMES+=("image metadata")
  printf 'FAIL  %-42s -> got mime=%s fp=%s size=%s\n' "uploaded image metadata" "$IMG_MT" "$IMG_FP" "$IMG_SZ"
fi

http_raw POST /signages/contents/upload "$ADMIN" -F "title=Promo Video$TAG" -F "content_type=video" -F "file=@$TMPDIR/clip.mp4;type=video/mp4"
if [ "$CODE" = "201" ]; then
  PASS=$((PASS+1)); printf 'PASS  %-42s -> %s\n' "upload video content (multipart)" "$CODE"
  VID_ID="$(json_get id)"
  VID_MT="$(json_get mime_type)"
else
  FAIL=$((FAIL+1)); FAIL_NAMES+=("upload video")
  printf 'FAIL  %-42s -> expected 201, got %s (%s)\n' "upload video content (multipart)" "$CODE" "$BODY"
fi
if [ -n "$VID_ID" ] && [ "$VID_MT" = "video/mp4" ]; then
  PASS=$((PASS+1)); printf 'PASS  %-42s -> %s\n' "uploaded video metadata (mp4)" "$VID_MT"
else
  FAIL=$((FAIL+1)); FAIL_NAMES+=("video metadata")
  printf 'FAIL  %-42s -> got mime=%s\n' "uploaded video metadata" "$VID_MT"
fi

expect "list video contents"             200 "GET /signages/contents?content_type=video" "$ADMIN"

http_raw POST /signages/contents/upload "$ADMIN" -F "title=Empty$TAG" -F "content_type=image" -F "file=@$TMPDIR/empty.png;type=image/png"
if [ "$CODE" = "400" ]; then
  PASS=$((PASS+1)); printf 'PASS  %-42s -> %s\n' "upload empty file rejected" "$CODE"
else
  FAIL=$((FAIL+1)); FAIL_NAMES+=("upload empty")
  printf 'FAIL  %-42s -> expected 400, got %s (%s)\n' "upload empty file rejected" "$CODE" "$BODY"
fi

printf 'not-a-real-image' > "$TMPDIR/bad.txt"
http_raw POST /signages/contents/upload "$ADMIN" -F "title=Bad$TAG" -F "content_type=image" -F "file=@$TMPDIR/bad.txt;type=text/plain"
if [ "$CODE" = "400" ]; then
  PASS=$((PASS+1)); printf 'PASS  %-42s -> %s\n' "upload bad extension rejected" "$CODE"
else
  FAIL=$((FAIL+1)); FAIL_NAMES+=("bad ext")
  printf 'FAIL  %-42s -> expected 400, got %s (%s)\n' "upload bad extension rejected" "$CODE" "$BODY"
fi

http_raw GET "/signages/contents/$IMG_ID/file" "$ADMIN"
if [ "$CODE" = "200" ] && [ -s "$BODY_FILE" ]; then
  PASS=$((PASS+1)); printf 'PASS  %-42s -> %s (%s bytes)\n' "get image file" "$CODE" "$(wc -c < "$BODY_FILE")"
else
  FAIL=$((FAIL+1)); FAIL_NAMES+=("get image file")
  printf 'FAIL  %-42s -> expected 200, got %s\n' "get image file" "$CODE"
fi
expect "get file for text content not found" 404 "GET /signages/contents/$CT_ID/file" "$ADMIN"

echo "== signage broadcast window =="
expect "set broadcast window"            200 "PUT /signages/contents/$CT_ID" "$ADMIN" '{"broadcast_start":"2020-01-01T00:00:00Z","broadcast_end":"2030-01-01T00:00:00Z"}'
expect_body_match "read broadcast window" "GET" "/signages/contents/$CT_ID" "$ADMIN" "" "broadcast_start"
expect "clear broadcast window"          200 "PUT /signages/contents/$CT_ID" "$ADMIN" '{"broadcast_start":null,"broadcast_end":null}'

echo "== signage assignments =="
expect "create assignment ok"            201 POST /signages/assignments "$ADMIN" "{\"signage_id\":\"$SG_ID\",\"content_id\":\"$CT_ID\",\"is_active\":true}"
ASG_ID="$(json_get id)"
expect "create duplicate assignment"     409 POST /signages/assignments "$ADMIN" "{\"signage_id\":\"$SG_ID\",\"content_id\":\"$CT_ID\",\"is_active\":true}"
expect "create assignment unknown signage" 404 POST /signages/assignments "$ADMIN" "{\"signage_id\":\"$RANDOM_ID\",\"content_id\":\"$CT_ID\"}"
expect "create assignment unknown content" 404 POST /signages/assignments "$ADMIN" "{\"signage_id\":\"$SG_ID\",\"content_id\":\"$RANDOM_ID\"}"
expect "list assignments"                200 "GET /signages/assignments?signage_id=$SG_ID" "$ADMIN"
expect "get assignment"                  200 "GET /signages/assignments/$ASG_ID" "$ADMIN"
expect "get assignment not found"        404 "GET /signages/assignments/$RANDOM_ID" "$ADMIN"
expect "patch assignment status"         200 "PATCH /signages/assignments/$ASG_ID/status" "$ADMIN" '{"is_active":false}'
expect "delete assignment"               204 "DELETE /signages/assignments/$ASG_ID" "$ADMIN"

echo "== signage schedules =="
expect "create schedule ok"              201 POST /signages/schedules "$ADMIN" "{\"signage_id\":\"$SG_ID\",\"content_id\":\"$CT_ID\",\"start_time\":\"08:00:00\",\"end_time\":\"20:00:00\",\"is_active\":true}"
SCH_ID="$(json_get id)"
expect "create schedule end before start" 422 POST /signages/schedules "$ADMIN" "{\"signage_id\":\"$SG_ID\",\"content_id\":\"$CT_ID\",\"start_time\":\"20:00:00\",\"end_time\":\"08:00:00\"}"
expect "create schedule unknown signage" 404 POST /signages/schedules "$ADMIN" "{\"signage_id\":\"$RANDOM_ID\",\"content_id\":\"$CT_ID\",\"start_time\":\"08:00:00\",\"end_time\":\"20:00:00\"}"
expect "list schedules"                  200 "GET /signages/schedules?content_id=$CT_ID" "$ADMIN"
expect "get schedule"                    200 "GET /signages/schedules/$SCH_ID" "$ADMIN"
expect "get schedule not found"          404 "GET /signages/schedules/$RANDOM_ID" "$ADMIN"
expect "update schedule"                 200 "PUT /signages/schedules/$SCH_ID" "$ADMIN" '{"end_time":"21:00:00"}'
expect "update schedule bad time"        422 "PUT /signages/schedules/$SCH_ID" "$ADMIN" '{"start_time":"22:00:00","end_time":"05:00:00"}'
expect "patch schedule status"           200 "PATCH /signages/schedules/$SCH_ID/status" "$ADMIN" '{"is_active":false}'
expect "delete schedule"                 204 "DELETE /signages/schedules/$SCH_ID" "$ADMIN"

echo "== signage cleanup =="
expect "delete media content (video)"    204 "DELETE /signages/contents/$VID_ID" "$ADMIN"
expect "delete media content (image)"    204 "DELETE /signages/contents/$IMG_ID" "$ADMIN"
expect "delete content"                  204 "DELETE /signages/contents/$CT_ID" "$ADMIN"
expect "delete signage"                  204 "DELETE /signages/$SG_ID" "$ADMIN"
expect "delete signage again"            404 "DELETE /signages/$SG_ID" "$ADMIN"
expect "delete second signage"           204 "DELETE /signages/$SG2_ID" "$ADMIN"

rm -rf "$TMPDIR"
summary
