# PRD GAP ANALYSIS — Trafix Operator App (POS)

Source: PRD Operator App v1 (provided 2026-08-15)
Analyzed against: `development`

Scope note: **Payment method selection (QRIS Dynamic / E-Money) is excluded from
this analysis** per feature decision. The transaction *recording* side of
payment (nominal, paid flag, paid time) is assessed where it intersects the
exit flow. Also excluded as out-of-scope per the PRD itself: tariff / vehicle /
member / gate / device / MQTT configuration, device monitoring, user
management, backup & restore, financial reporting.

The gate-cycle endpoints (`/api/gatein`, `/api/gateout/*`, `/api/lpr/*`) are
legacy-wire-compatible loopback routes (see `gate_cycle.py` docstrings), which
is why most are unauthenticated; the Operator App POS would consume them
directly or via a thin wrapper.

## Coverage matrix

| PRD Module / Feature | PRD Requirement | Status | Detail |
|---|---|---|---|
| **Auth — Shift selection before login** | select available shift before login; show name/code/start/end; prevent closed shifts; retain shift through login | ⚠️ | `POST /auth/login` takes only `username` + `password` (no shift/gate). Shift selection moved to `POST /operator-sessions/start`, called after login with `shift_id` + `gate_id`; it opens the `operator_sessions` row (operator + shift + gate, status Active) that is the POS transaction context, and rejects an operator who already has an active session (409) |
| **Auth — Login** | login page, validate username/password + account status, error on failure, block access on fail | ✅ | Login/refresh/logout/me work; inactive users blocked (403), lockout after repeated failures (`auth.py` + `dependencies`) |
| **Auth — Validate shift status + gate permission** | validate selected shift is open; validate operator is permitted for the assigned gate | ⚠️ | `POST /operator-sessions/start` validates the shift and gate exist (404 otherwise) but no longer checks the shift's open window or the operator's `operator_shift_assignment`; those checks, which lived in the removed shift-before-login flow, are not enforced at session start |
| **Auth — Operator session after login** | create session after successful auth; store operator/gate/shift/start-time/status; active session is the transaction context | ✅ | Session created by `POST /operator-sessions/start` (operator + gate + shift + status Active, audit-logged), not at login; the POS router resolves the active session per request |
| **Auth — Block transactions without active session** | prevent transaction processing when there is no active operator session | ✅ | `get_active_operator_session` dependency (JWT operator + active `operator_sessions` row, else 403) guards every `/api/pos/transactions/*` endpoint; gate/operator/shift come from the session, not the body |
| **Exit — Auto LPR** | accept plate from Camera LPR; find open entry by plate; auto-calc rate | ✅ | Exit LPR announcement (`gate/out/{gate}/pos`) → `_settle_by_plate` → `PUT /api/lpr/gateoutcard`; quote by plate (`/api/gateout/detailtransaction`) |
| **Exit — Ticket scan** | read barcode ticket; validate; show transaction info | ✅ | `gateoutKasir` (transaction_code) + `detailtransaction` quote; ticket-used → `already_paid`, not-found → 404 |
| **Exit — Member card** | read member card; validate; show info | ✅ | `gateout`/`gate_out_rfid` + `gateoutcard` `success_member`; member resolved by card |
| **Exit — Manual input** | manual vehicle input when LPR/scan fails | ✅ | `gateoutKasir` accepts `police_number` + `vehicle_id`; lost-ticket path writes a record from plate + vehicle class |
| **Exit — Vehicle validation** | show vehicle info when data not found | ⚠️ | API returns `notfound`/`already_paid` statuses the POS can render; the "show matching info" UX is app-side |
| **Exit — Auto rate calculation** | calculate rates automatically per Trafix config | ✅ | `quote`/`_price` (duration, breakdown, grace, flat tariffs) |
| **Exit — Save payment transaction** | save the settled transaction (nominal, paid flag/time) | ✅ | `payment_status="lunas"`, `paid_at`, `total_fee`, `duration`, `exit_time` recorded (`gate_cycle.py` `gate_out`) |
| **Exit — Print receipt** | print proof of payment when needed | ✅ | `POST /api/pos/transactions/receipt` prints the exit receipt (single `txUartData` block via `build_gate_out_receipt`); `gate_out`/`lost_ticket`/`manual_ticket` persist `exit_operator_id`/`exit_shift_id` |
| **Exit — Open barrier** | send open-barrier command after success; show opened status; record exit time | ✅ | Barrier command sent (`publisher.open_barrier(exit_lane=True)`, gated by `COMMAND_EXIT_BARRIER`), exit time recorded. `GET /api/pos/events/stream` (SSE, Redis pub/sub) streams `barrier_command`, `barrier_opened` (from the controller ack), `transaction_settled`, `transaction_voided` events in real time, with a DB snapshot replay on connect and keepalive fallback |
| **Exit — Void transaction** | void a transaction | ✅ | `POST /api/pos/transactions/void` (active session required): parked → VOID with `keterangan` reason; paid → existing payment marked `REFUNDED` (or a cash refund row added), `gate_event` audit, idempotence guard (409 on second void) |
| **Exit — Reprint receipt** | reprint a receipt | ✅ | `POST /api/pos/transactions/reprint` rebuilds the entry ESC/POS ticket from the persisted transaction and prints it (4 blocks, `gate_event` audit) |
| **Offline Transaction** | process a transaction offline | ❌ | No offline/batch queue or detached-transaction flow. Deferred — design-only, see gap 7 |

## Gap list (priority order)

### P0 — Transaction integrity
1. **Void transaction** — ✅ `POST /api/pos/transactions/void` (`gate_cycle.py::void_transaction`). Parked → `VOID` + reason; paid → refund (`REFUNDED` payment / new cash refund row); audit via `gate_event`; 409 on repeat.
2. **Active operator session enforcement** — ✅ `get_active_operator_session` (core/dependencies) guards all POS transaction endpoints; operator/gate/shift come from the session. Wire routes `gateoutKasir`/`gateout` remain body-based for loopback compatibility; the POS consumes them via `/api/pos/*`.
3. **Reprint receipt** — ✅ `POST /api/pos/transactions/reprint`.

### P1 — POS workflow gaps
4. **Shift selection before login** — ✅ Login is username/password only; the operator picks the shift and opens the session via `POST /operator-sessions/start` (shift + gate + 409 on an existing active session).
5. **Gate-opened status to the POS** — ✅ SSE stream `GET /api/pos/events/stream` (`services/events.py`, Redis pub/sub, `barrier_opened` published from the orchestrator ack handler).

### P2 — Detail
6. **Exit receipt print** — ✅ `POST /api/pos/transactions/receipt` (`escpos.build_gate_out_receipt`, single block); exit operator/shift persisted on settle.
7. **Offline transaction queue** — ❌ Deferred. Design a device-side queue + reconciliation for network-down operation (MVP lists it).

## Present but OUT of PRD scope (extras — keep, don't delete)
- `operator_shift_assignment` CRUD — covers the "operator permission for assigned gate" requirement partially; the shift/gate validity checks that were part of shift-before-login are no longer enforced at session start.
- Entry-side gate cycle (`gatein`, member auto-entry, orchestrator) — the Operator App PRD is Gate-Out only, but entry is the source of the sessions it settles.
- `audit_log` writes on session start/end — already present, aligns with the back-office audit requirement.
- RBAC on the admin modules — unchanged from the Admin & Teknisi scope.

## Summary
- **Fully implemented:** login/auth, session start via `POST /operator-sessions/start`, active-session enforcement, ticket scan, member card, manual input, auto-LPR exit, auto rate calc, payment recording, barrier-open command + real-time status, exit receipt print, void + refund, reprint.
- **Not implemented (deferred):** offline transaction flow.
