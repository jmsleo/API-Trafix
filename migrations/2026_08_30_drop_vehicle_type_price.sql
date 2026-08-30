-- Migration 2026-08-30: drop vehicle_types.price.
-- parking_rates is now the single source of truth for flat pricing: the flat
-- rate lives on parking_rates.base_price, so the denormalized shortcut column
-- on vehicle_types is removed to prevent the two from drifting out of sync.
--
-- Run: psql "$DATABASE_URL" -f migrations/2026_08_30_drop_vehicle_type_price.sql

ALTER TABLE vehicle_types DROP COLUMN IF EXISTS price;
