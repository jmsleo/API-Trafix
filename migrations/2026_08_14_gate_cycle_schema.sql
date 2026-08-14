-- Migration 2026-08-14: gate-in / gate-out cycle schema.
-- Phase 1 of the trafix-api-mock integration: the columns and tables the LPR
-- gate cycle needs, mapped onto the modern API-Trafix schema.
--
-- The app uses Base.metadata.create_all (never alters), so schema changes must
-- be applied manually.
-- Run: psql "$DATABASE_URL" -f migrations/2026_08_14_gate_cycle_schema.sql
--
-- Design decisions:
--   * cash-only for now: no qrcode/pr_id_xendit/xendit_qr_pool columns.
--     On a cash ticket the printed QR *is* the ticket code.
--   * flat tariffs only: parking_rates keeps base_price; the added columns are
--     the flat path's own fields (grace, lost-ticket fee, overnight stay fee).
--   * police_number / entry_operator_id / entry_shift_id become nullable:
--     the mock records plates as advisory (4 of 6 live entry tickets had no
--     plate) and automated entries carry no operator/shift.

-- 1) parking_rates: flat-mode fields (port of mock parking_fees columns the
--    flat calculation actually reads)
ALTER TABLE parking_rates ADD COLUMN IF NOT EXISTS grace_period_minutes INTEGER;
ALTER TABLE parking_rates ADD COLUMN IF NOT EXISTS ticket_charge INTEGER;
ALTER TABLE parking_rates ADD COLUMN IF NOT EXISTS stay_charge INTEGER;

-- 2) park_transactions: gate-cycle columns (mirror of mock transactions)
ALTER TABLE park_transactions ADD COLUMN IF NOT EXISTS card_number VARCHAR(255);
ALTER TABLE park_transactions ADD COLUMN IF NOT EXISTS payment_status VARCHAR(20);
ALTER TABLE park_transactions ADD COLUMN IF NOT EXISTS payment_type VARCHAR(10) DEFAULT 'cash';
ALTER TABLE park_transactions ADD COLUMN IF NOT EXISTS paid_at TIMESTAMPTZ;
ALTER TABLE park_transactions ADD COLUMN IF NOT EXISTS duration VARCHAR(255);
ALTER TABLE park_transactions ADD COLUMN IF NOT EXISTS plate_out VARCHAR(255);
ALTER TABLE park_transactions ADD COLUMN IF NOT EXISTS keterangan TEXT;
ALTER TABLE park_transactions ADD COLUMN IF NOT EXISTS cam_in VARCHAR(255) DEFAULT '-';
ALTER TABLE park_transactions ADD COLUMN IF NOT EXISTS camin_lpr VARCHAR(255);
ALTER TABLE park_transactions ADD COLUMN IF NOT EXISTS cam_out VARCHAR(255);
ALTER TABLE park_transactions ADD COLUMN IF NOT EXISTS camout_lpr VARCHAR(255);
ALTER TABLE park_transactions ADD COLUMN IF NOT EXISTS cam_payment VARCHAR(255);

-- 3) park_transactions: relax NOT NULL constraints the gate cycle violates
ALTER TABLE park_transactions ALTER COLUMN police_number DROP NOT NULL;
ALTER TABLE park_transactions ALTER COLUMN entry_operator_id DROP NOT NULL;
ALTER TABLE park_transactions ALTER COLUMN entry_shift_id DROP NOT NULL;

-- 4) gates: wire id ("1", "2") -> gate UUID mapping
ALTER TABLE gates ADD COLUMN IF NOT EXISTS gate_code VARCHAR(16) UNIQUE;

-- 5) members: RFID tag for member auto-entry / gate-out-by-card
ALTER TABLE members ADD COLUMN IF NOT EXISTS card_number VARCHAR(255) UNIQUE;

-- 6) gate_events: audit trail of gate hardware decisions (the piece the
--    production system lacked -- flow.md had to be reconstructed from a packet
--    capture because nothing logged what the gate did)
CREATE TABLE IF NOT EXISTS gate_events (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    ts TIMESTAMPTZ NOT NULL DEFAULT now(),
    source VARCHAR(64) NOT NULL,
    gate_code VARCHAR(16),
    topic VARCHAR(255),
    method VARCHAR(64),
    ticket_number VARCHAR(255),
    detail TEXT
);

CREATE INDEX IF NOT EXISTS idx_gate_events_ts ON gate_events (ts);
CREATE INDEX IF NOT EXISTS idx_gate_events_ticket ON gate_events (ticket_number);
