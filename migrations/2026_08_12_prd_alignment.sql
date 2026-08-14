-- Migration 2026-08-12: signage media + broadcast, async backup progress, backup RUNNING status.
-- The app uses Base.metadata.create_all (never alters), so schema changes must be applied manually.
-- Run: psql "$DATABASE_URL" -f migrations/2026_08_12_prd_alignment.sql

-- 1) backups: progress column + RUNNING status value
ALTER TABLE backups ADD COLUMN IF NOT EXISTS progress INTEGER NOT NULL DEFAULT 0;
ALTER TYPE backup_status ADD VALUE IF NOT EXISTS 'running';

-- 2) signage_contents: media file columns + broadcast window
ALTER TABLE signage_contents ADD COLUMN IF NOT EXISTS file_path VARCHAR(500);
ALTER TABLE signage_contents ADD COLUMN IF NOT EXISTS mime_type VARCHAR(100);
ALTER TABLE signage_contents ADD COLUMN IF NOT EXISTS file_size_bytes BIGINT;
ALTER TABLE signage_contents ADD COLUMN IF NOT EXISTS broadcast_start TIMESTAMPTZ;
ALTER TABLE signage_contents ADD COLUMN IF NOT EXISTS broadcast_end TIMESTAMPTZ;

-- 3) signage_content_type enum: add 'video'
ALTER TYPE signage_content_type ADD VALUE IF NOT EXISTS 'video';

-- 4) parking_rates: flat-mode tariff category (gate cycle)
ALTER TABLE parking_rates ADD COLUMN IF NOT EXISTS fee_category VARCHAR(20) NOT NULL DEFAULT 'flat';
