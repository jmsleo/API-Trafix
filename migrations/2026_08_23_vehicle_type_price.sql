-- Migration 2026-08-23: vehicle_types.price.
-- Flat price (rupiah) the operator's manual ticket charges for a vehicle
-- class, editable from the admin vehicle-type screen. Nullable: existing rows
-- stay valid and the manual-ticket flow falls back to the legacy flat rates
-- when unset. Backfilled from each class's active parking_rates.base_price so
-- seeded databases start with the familiar 2000 / 4000 / 0 / 6000 values.
--
-- Run: psql "$DATABASE_URL" -f migrations/2026_08_23_vehicle_type_price.sql

ALTER TABLE vehicle_types ADD COLUMN IF NOT EXISTS price INTEGER;

UPDATE vehicle_types vt
SET price = pr.base_price
FROM parking_rates pr
WHERE pr.vehicle_type_id = vt.id
  AND pr.status = 'active'
  AND vt.price IS NULL;
