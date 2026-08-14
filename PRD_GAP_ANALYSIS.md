# PRD GAP ANALYSIS — Trafix (Admin & Teknisi)

Source: PRD Trafix (Admin & Teknisi) v1 · July/2026 (Google Docs)
Analyzed against: `development` (+ open PR #38 `feat/audit-log-view`, already conflict-merged locally)

Scope note from the PRD: the system is **not** for parking transactions, payments, financial
reports, or operator/kasir use. Several existing endpoints sit outside the PRD MVP (marked "extra").

## Coverage matrix

| PRD Module / Feature | PRD Requirement | Status | Detail |
|---|---|---|---|
| **Auth — Login** | login page, validate creds, error msg, audit-log login activity | ✅/❌ | Login/refresh/logout/me work; inactive users blocked (403) + `last_login` updated. **Login activity NOT written to Audit Log** |
| **Auth — RBAC** | restrict access by role on every feature | ⚠️ | Roles exist (`admin`, `finance`, `teknisi`, `operator`). Enforced on users, backup, signage, audit-log, subscription-plans, member-vehicles, member-subscriptions, operator-sessions/shifts, finance. **Not enforced on member, parking-rate, vehicle-type, shift** (no auth at all) |
| **Dashboard — Teknisi** | online/offline device counts, MQTT broker, problem-device list, refresh | ❌ | Not implemented. Only a Finance dashboard exists |
| **Business Config — Tarif Parkir** | CRUD, list (name/type/rates/status/date), search, status filter, pagination | ⚠️ | Full CRUD + status toggle + search + pagination. **No auth, no Audit Log writes** |
| **Business Config — Jenis Kendaraan** | CRUD, list (code/name/status/date), search by name/code, status filter, pagination, unique code | ⚠️ | CRUD + unique code. **No pagination/search/filter on list; no auth; no Audit Log writes** |
| **Business Config — Member** | CRUD + register + block, list (number/name/vehicle/type/status), search, status filter, pagination, unique member number | ⚠️ | CRUD + block + search + pagination present. **No auth, no Audit Log writes** |
| **Business Config — Shift** | CRUD, list (name/start/finish/status/date), search, status filter, pagination, unique name | ⚠️ | CRUD + search + filter + pagination. **No auth, no Audit Log writes** |
| **Signage Management** | content CRUD + upload w/ format+size validation + preview; active/inactive; assignment to signage; schedule + broadcast-period status | ⚠️ | Content/assignment/schedule CRUD + status toggles + delete guards done. **Missing: file upload with validation + preview; schedule does not auto-derive content status from broadcast period; no Audit Log writes** |
| **Device Configuration — Gate** | list/search/paginate gates; configure controller, MQTT, camera LPR, loop sensor, ticket dispenser, card reader, barrier, signage | ❌ | `Gate` model exists; **no routes** |
| **Device Configuration — Manless / Signage / Camera LPR** | central device configuration | ❌ | `Device` model exists; **no routes** |
| **Monitoring** | manless / MQTT / camera LPR / reader / signage status; real-time updates; device log; test connection | ❌ | **Not implemented** (no routes) |
| **Device Log** | history log, time/device-type/description, filter by time + type | ❌ | **Not implemented** |
| **Admin — User Management** | list (name/username/role/status/last login), search, role/status filter, pagination; create/update/reset password/status; role change effective next login; inactive blocked | ✅ | Admin-only (PR #35). last_login tracked, inactive blocked on login, RBAC on all endpoints. **No Audit Log writes** |
| **Admin — Audit Log** | list: time, user, role, module, action, description; search by name/description; filter by date/user/module/action | ✅/❌ | **Viewing** complete (PR #38): list + detail + all filters. **Writes are nearly absent** — only the backup module logs (services/backup.py) |
| **Admin — Backup DB** | run backup, progress, status, save file | ✅ | `POST /backups/` + list/download/delete + audit writes |
| **Admin — Restore DB** | upload backup file, validate, run restore, status | ✅ | upload/restore with format validation + audit writes |

## Gap list (priority order)

### P0 — RBAC + Audit Log writing (PRD: "Seluruh fitur menerapkan RBAC", "Seluruh aktivitas tercatat pada Audit Log")
1. **No auth on 4 modules** — `members`, `parking-rates`, `vehicle-types`, `shifts` expose create/update/delete to anyone. Add admin gate (or `require_roles(ADMIN)`).
2. **Audit Log writes missing** — `log_action()` is only wired into the backup module. Required per PRD on: login, parking-rate CRUD/status, vehicle-type CRUD, member register/update/status/block, shift CRUD, signage content/assignment/schedule CRUD + status, user create/update/reset/inactive, backup, restore. (`services/audit.log_action` already exists and is verified working.)

### P1 — Teknisi role & device modules (entire Teknisi side of the PRD)
3. **Dashboard Teknisi** — online/offline device counts, MQTT broker status, problem-device list, refresh + last-updated time. `teknisi` role exists but is unused.
4. **Gate Management** — CRUD + search + pagination for gates (model exists).
5. **Device Configuration** — gate sub-components (controller, MQTT, camera LPR, loop sensor, ticket dispenser, card reader, barrier, signage) + manless/camera/signage device config.
6. **Monitoring** — manless / MQTT / camera / reader / signage status endpoints, device log, test connection, restart device.

### P2 — PRD detail gaps in existing modules
7. **Jenis Kendaraan list** — add search (name/code) + status filter + pagination (currently plain list).
8. **Signage content file upload** — format + size validation and preview (currently content is metadata only).
9. **Signage broadcast-period status** — content status should auto-derive from the schedule period (start/end validation exists; derivation does not).
10. **Login audit entry** — log successful logins (PRD explicitly lists "record login activity in the audit log").

## Present but OUT of PRD scope (extras — keep, don't delete)
- `finance_dashboard`, `finance_reports` — PRD excludes financial reports (leave as-is / future).
- `operator_session`, `operator_shift_assignment` — operator flow is out of PRD (parking ops).
- `subscription_plan`, `member_vehicle`, `member_subscription`, `park_transaction`, `payment`, `parking_slot` models/routes — membership features beyond the PRD MVP, harmless additions.
- `UserRole.FINANCE` / `OPERATOR` roles — PRD app is Admin + Teknisi only; existing roles are compatible (superset).

## Summary
- **Fully implemented:** Login, User Management, Audit Log viewing, Backup, Restore.
- **Partially implemented (core gaps):** RBAC enforcement (4 modules unauthenticated), Audit Log writes (all modules except backup), vehicle-type list UX, signage upload/preview/period-status.
- **Not implemented (entire Teknisi workstream):** Dashboard, Gate management/config, device configuration, all monitoring, device log, test connection, restart.
