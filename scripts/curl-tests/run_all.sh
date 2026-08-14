#!/usr/bin/env bash
# run_all.sh - bootstrap then execute every suite; aggregates PASS/FAIL.
set -uo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$DIR"

TOTAL_PASS=0
TOTAL_FAIL=0
FAILED_SUITES=()

run_suite() {
  echo
  echo "############################################################"
  echo "# SUITE: $1"
  echo "############################################################"
  local out
  out="$(bash "$1.sh" 2>&1)"
  local rc=$?
  echo "$out"
  local p f
  p="$(printf '%s' "$out" | sed -n 's/^PASS: *\([0-9]*\).*/\1/p' | tail -1)"
  f="$(printf '%s' "$out" | sed -n 's/^PASS: *[0-9]* *FAIL: *\([0-9]*\).*/\1/p' | tail -1)"
  TOTAL_PASS=$((TOTAL_PASS + ${p:-0}))
  TOTAL_FAIL=$((TOTAL_FAIL + ${f:-0}))
  [ "$rc" -ne 0 ] && FAILED_SUITES+=("$1")
  return 0
}

bash 00_bootstrap.sh

run_suite 01_auth
run_suite 02_users
run_suite 03_reference
run_suite 04_pricing
run_suite 05_operator
run_suite 06_member_relations
run_suite 07_signage
run_suite 08_backups_audit
run_suite 09_finance

echo
echo "============================================================"
echo "TOTAL PASS: $TOTAL_PASS   TOTAL FAIL: $TOTAL_FAIL"
if [ "${#FAILED_SUITES[@]}" -gt 0 ]; then
  printf 'Suites with failures: %s\n' "${FAILED_SUITES[*]}"
  exit 1
fi
echo "ALL SUITES PASSED"
