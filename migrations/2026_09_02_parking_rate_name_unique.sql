-- Migration 2026-09-02: unique parking rate name.
-- Enforces that a parking rate name may not be reused, so admins cannot create
-- (or rename to) a tariff with a name that already exists. The check is applied
-- on the normalized (lowercased) name so uniqueness is case-insensitive, e.g.
-- "Tarif Reguler" and "tarif reguler" are treated as the same name.
--
-- Run: psql "$DATABASE_URL" -f migrations/2026_09_02_parking_rate_name_unique.sql

CREATE UNIQUE INDEX IF NOT EXISTS uq_parking_rates_name_lower ON parking_rates (lower(name));
