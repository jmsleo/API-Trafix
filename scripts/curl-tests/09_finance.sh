#!/usr/bin/env bash
# 09_finance.sh - finance dashboard + reports (finance role), 403 for others.
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/lib.sh"
SUITE="finance"

FIN="$(get_token finance)"
ADMIN="$(get_token admin)"
OP="$(get_token op1)"

echo "== finance dashboard =="
expect "revenue today (finance)"         200 GET /finance/dashboard/revenue/today "$FIN"
expect "revenue by shift (finance)"      200 GET /finance/dashboard/revenue/shift "$FIN"
expect "vehicle distribution (finance)"  200 GET /finance/dashboard/vehicle-distribution "$FIN"
expect "payment distribution (finance)"  200 GET /finance/dashboard/payment-distribution "$FIN"
expect "executive insight (finance)"     200 GET /finance/dashboard/executive-insight "$FIN"

echo "== finance reports =="
expect "transaction report (finance)"    200 "GET /finance/reports/transactions?page=1&size=20" "$FIN"
expect "transaction report filters"      200 "GET /finance/reports/transactions?search=abc&status=Parked&page=1&size=20" "$FIN"
expect "pending tickets (finance)"       200 "GET /finance/reports/pending-tickets?page=1&size=20" "$FIN"

echo "== finance: role enforcement =="
expect "dashboard as admin (403)"        403 GET /finance/dashboard/revenue/today "$ADMIN"
expect "dashboard as operator (403)"     403 GET /finance/dashboard/revenue/today "$OP"
expect "reports as admin (403)"          403 GET /finance/reports/transactions "$ADMIN"
expect "reports without token"           401 GET /finance/reports/transactions ""
expect "dashboard without token"         401 GET /finance/dashboard/revenue/today ""

summary
