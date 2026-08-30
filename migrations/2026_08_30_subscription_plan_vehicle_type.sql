-- Migration 2026-08-30: subscription_plans.vehicle_type_id.
-- Each package (subscription plan) belongs to one vehicle type, surfaced in
-- the admin package list. The column is NOT NULL; existing rows are backfilled
-- to the first active vehicle type (falling back to any) so they stay valid.
--
-- Run: psql "$DATABASE_URL" -f migrations/2026_08_30_subscription_plan_vehicle_type.sql

-- 1) Add the column as nullable first so existing rows can be backfilled.
ALTER TABLE subscription_plans ADD COLUMN IF NOT EXISTS vehicle_type_id UUID;

-- 2) Backfill rows that have no vehicle type yet.
UPDATE subscription_plans sp
SET vehicle_type_id = (
    SELECT vt.id
    FROM vehicle_types vt
    ORDER BY (vt.status = 'active') DESC, vt.code
    LIMIT 1
)
WHERE sp.vehicle_type_id IS NULL;

-- 3) Add the foreign key and enforce NOT NULL.
ALTER TABLE subscription_plans
    ALTER COLUMN vehicle_type_id SET NOT NULL;
ALTER TABLE subscription_plans
    ADD CONSTRAINT fk_subscription_plans_vehicle_type
    FOREIGN KEY (vehicle_type_id) REFERENCES vehicle_types(id);
