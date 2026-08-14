-- Migration 2026-08-14: gate-cycle fee engine fields.
-- Phase 2 of the trafix-api-mock integration: ``parking_rates.fee_category``
-- distinguishes the tariff model, mirroring the mock's ``parking_fees`` table.
-- Flat is the only tariff the gate cycle seeds, so the column defaults to
-- 'flat' and the progressive fields are intentionally absent for now.
--
-- Run: psql "$DATABASE_URL" -f migrations/2026_08_14_gate_cycle_fee_fields.sql

ALTER TABLE parking_rates ADD COLUMN IF NOT EXISTS fee_category VARCHAR(20) NOT NULL DEFAULT 'flat';
