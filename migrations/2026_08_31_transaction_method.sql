-- Migration 2026-08-31: park_transactions.transaction_method.
-- The operator app now exposes the transaction method as an explicit choice
-- (STANDAR / MANUAL / HILANG) instead of relying on the free-text `keterangan`
-- column. This adds a first-class, queryable column so reports and filters can
-- distinguish normal, manual, and lost tickets without parsing free text.
--
-- The backend encodes the method in `keterangan` when present. Existing rows
-- are backfilled from that text so history stays accurate:
--   * "tiket hilang"       -> 'lost'
--   * "tiket tidak cetak"  -> 'manual'
--   * everything else      -> 'normal'
--
-- Run: psql "$DATABASE_URL" -f migrations/2026_08_31_transaction_method.sql

-- 1) Add the column as nullable first so existing rows can be backfilled.
ALTER TABLE park_transactions ADD COLUMN IF NOT EXISTS transaction_method VARCHAR(16);

-- 2) Backfill existing rows from the free-text keterangan marker.
UPDATE park_transactions
SET transaction_method = 'lost'
WHERE transaction_method IS NULL
  AND lower(COALESCE(keterangan, '')) LIKE '%tiket hilang%';

UPDATE park_transactions
SET transaction_method = 'manual'
WHERE transaction_method IS NULL
  AND lower(COALESCE(keterangan, '')) LIKE '%tiket tidak cetak%';

-- 3) Any remaining rows are standard transactions.
UPDATE park_transactions
SET transaction_method = 'normal'
WHERE transaction_method IS NULL;

-- 4) Enforce the value going forward.
ALTER TABLE park_transactions
    ALTER COLUMN transaction_method SET NOT NULL,
    ALTER COLUMN transaction_method SET DEFAULT 'normal';
