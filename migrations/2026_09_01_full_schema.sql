-- Migration 2026-09-01: Full schema bootstrap.
-- =============================================================================
-- PURPOSE
--   Build the ENTIRE database schema exactly as defined by the SQLAlchemy
--   models in src/api_trafix/models/. This is a drop-in replacement for the
--   app's Base.metadata.create_all() path so that:
--
--     git pull && psql "$DATABASE_URL" -f migrations/2026_09_01_full_schema.sql
--
--   produces a DB identical to the authoring database. It folds in every
--   previously-separate migration (gate cycle columns, FK cascades, vehicle
--   type price add/drop, subscription plan vehicle type, transaction method,
--   etc.) into a single idempotent script.
--
--   Ordering
--     1. ENUM types (must exist before tables reference them)
--     2. Tables in FK-dependency order (root -> leaf)
--
--   Idempotency:
--     * CREATE TABLE IF NOT EXISTS  -> no-op on an existing DB
--     * ENUM creation wrapped in a DO block that swallows "already exists"
--     * Existing migration ALTERs are re-folded with IF NOT EXISTS
--
--   Run: psql "$DATABASE_URL" -f migrations/2026_09_01_full_schema.sql
-- =============================================================================

-- =============================================================================
-- 1) ENUM TYPES
-- =============================================================================
-- Each enum is created only if it does not already exist. PostgreSQL has no
-- CREATE TYPE IF NOT EXISTS, so we guard with a DO block that catches the
-- 42710 "duplicate_object" error when the type is already present.

DO $$ BEGIN
    CREATE TYPE gate_type AS ENUM ('gate_in', 'gate_out');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

DO $$ BEGIN
    CREATE TYPE gate_status AS ENUM ('online', 'offline');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

DO $$ BEGIN
    CREATE TYPE vehicle_status AS ENUM ('active', 'inactive');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

DO $$ BEGIN
    CREATE TYPE user_role AS ENUM ('admin', 'finance', 'teknisi', 'operator');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

DO $$ BEGIN
    CREATE TYPE user_status AS ENUM ('active', 'inactive');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

DO $$ BEGIN
    CREATE TYPE shift_status AS ENUM ('active', 'inactive');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

DO $$ BEGIN
    CREATE TYPE member_status AS ENUM ('active', 'inactive', 'blocked');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

DO $$ BEGIN
    CREATE TYPE rate_status AS ENUM ('active', 'inactive');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

DO $$ BEGIN
    CREATE TYPE operator_session_status AS ENUM ('active', 'closed');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

DO $$ BEGIN
    CREATE TYPE operator_shift_assignment_status AS ENUM ('active', 'inactive');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

DO $$ BEGIN
    CREATE TYPE parking_status AS ENUM ('Parked', 'Completed', 'Void');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

DO $$ BEGIN
    CREATE TYPE detection_method AS ENUM ('Auto_LPR', 'Scanner', 'RFID', 'Manual');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

DO $$ BEGIN
    CREATE TYPE payment_method AS ENUM ('Cash', 'QRIS', 'Emoney');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

DO $$ BEGIN
    CREATE TYPE payment_status AS ENUM ('Pending', 'Success', 'Failed', 'Refunded');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

DO $$ BEGIN
    CREATE TYPE backup_status AS ENUM ('running', 'completed', 'failed');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

DO $$ BEGIN
    CREATE TYPE signage_status AS ENUM ('active', 'inactive');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

DO $$ BEGIN
    CREATE TYPE signage_content_type AS ENUM ('text', 'image', 'video');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

-- =============================================================================
-- 2) TABLES (FK-dependency order)
-- =============================================================================

-- -----------------------------------------------------------------------------
-- ROOT TABLES (no foreign keys)
-- -----------------------------------------------------------------------------

-- gates
CREATE TABLE IF NOT EXISTS gates (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name        VARCHAR(100) NOT NULL,
    gate_code   VARCHAR(16) UNIQUE,
    type        gate_type NOT NULL,
    status      gate_status NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- vehicle_types
CREATE TABLE IF NOT EXISTS vehicle_types (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    code        VARCHAR(20) NOT NULL UNIQUE,
    name        VARCHAR(100) NOT NULL,
    status      vehicle_status NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- users
CREATE TABLE IF NOT EXISTS users (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name        VARCHAR(100) NOT NULL,
    username    VARCHAR(50) NOT NULL UNIQUE,
    password    VARCHAR(255) NOT NULL,
    role        user_role NOT NULL,
    status      user_status NOT NULL,
    last_login  TIMESTAMPTZ,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Case-insensitive unique index on username (mirrors model Index(...lower...))
CREATE UNIQUE INDEX IF NOT EXISTS ix_users_username_lower
    ON users (lower(username));

-- shifts
CREATE TABLE IF NOT EXISTS shifts (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name             VARCHAR(50) NOT NULL UNIQUE,
    start_time       TIME NOT NULL,
    finish_time      TIME NOT NULL,
    crosses_midnight BOOLEAN NOT NULL DEFAULT FALSE,
    status           shift_status NOT NULL,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- gate_events (audit trail of gate hardware decisions)
CREATE TABLE IF NOT EXISTS gate_events (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    ts            TIMESTAMPTZ NOT NULL DEFAULT now(),
    source        VARCHAR(64) NOT NULL,
    gate_code     VARCHAR(16),
    topic         VARCHAR(255),
    method        VARCHAR(64),
    ticket_number VARCHAR(255),
    detail        TEXT
);
CREATE INDEX IF NOT EXISTS idx_gate_events_ts ON gate_events (ts);
CREATE INDEX IF NOT EXISTS idx_gate_events_ticket ON gate_events (ticket_number);

-- system_config (runtime config overrides; section+key unique)
CREATE TABLE IF NOT EXISTS system_config (
    id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    section    VARCHAR(50) NOT NULL,
    key        VARCHAR(100) NOT NULL,
    value      JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_system_config_section_key UNIQUE (section, key)
);

-- signages
CREATE TABLE IF NOT EXISTS signages (
    id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name       VARCHAR(100) NOT NULL,
    code       VARCHAR(50) NOT NULL UNIQUE,
    location   VARCHAR(200),
    status     signage_status NOT NULL DEFAULT 'active',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- signage_contents
CREATE TABLE IF NOT EXISTS signage_contents (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    title           VARCHAR(100) NOT NULL,
    content_type    signage_content_type NOT NULL DEFAULT 'text',
    body            TEXT,
    is_active       BOOLEAN NOT NULL DEFAULT TRUE,
    file_path       VARCHAR(500),
    mime_type       VARCHAR(100),
    file_size_bytes BIGINT,
    broadcast_start TIMESTAMPTZ,
    broadcast_end   TIMESTAMPTZ,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- -----------------------------------------------------------------------------
-- LEVEL 1 TABLES (foreign keys to root tables)
-- -----------------------------------------------------------------------------

-- members
CREATE TABLE IF NOT EXISTS members (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    member_code  VARCHAR(50) NOT NULL UNIQUE,
    name         VARCHAR(100) NOT NULL,
    email        VARCHAR(100),
    phone_number VARCHAR(20),
    card_number  VARCHAR(255) UNIQUE,
    status       member_status NOT NULL,
    created_by   UUID REFERENCES users(id) ON DELETE SET NULL,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- devices
CREATE TABLE IF NOT EXISTS devices (
    id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    gate_id        UUID NOT NULL REFERENCES gates(id) ON DELETE CASCADE,
    name           VARCHAR(100) NOT NULL,
    type           VARCHAR(50) NOT NULL,
    ip_address     VARCHAR(45) NOT NULL,
    config         JSONB,
    status         VARCHAR(20) NOT NULL DEFAULT 'offline',
    last_heartbeat TIMESTAMPTZ,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- subscription_plans
CREATE TABLE IF NOT EXISTS subscription_plans (
    id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name              VARCHAR(50) NOT NULL,
    duration_in_days  INTEGER NOT NULL,
    price             INTEGER NOT NULL,
    vehicle_type_id   UUID NOT NULL REFERENCES vehicle_types(id) ON DELETE CASCADE,
    is_active         BOOLEAN NOT NULL DEFAULT TRUE,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- parking_slots
CREATE TABLE IF NOT EXISTS parking_slots (
    id                 UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    vehicle_type_id    UUID NOT NULL REFERENCES vehicle_types(id) ON DELETE CASCADE,
    total_capacity     INTEGER NOT NULL,
    available_capacity INTEGER NOT NULL,
    created_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at         TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- parking_rates
CREATE TABLE IF NOT EXISTS parking_rates (
    id                   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name                 VARCHAR(100) NOT NULL,
    vehicle_type_id      UUID NOT NULL REFERENCES vehicle_types(id) ON DELETE CASCADE,
    base_price           INTEGER NOT NULL,
    fee_category         VARCHAR(20) NOT NULL DEFAULT 'flat',
    grace_period_minutes INTEGER,
    ticket_charge        INTEGER,
    stay_charge          INTEGER,
    status               rate_status NOT NULL DEFAULT 'active',
    created_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at           TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- member_vehicles
CREATE TABLE IF NOT EXISTS member_vehicles (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    member_id       UUID NOT NULL REFERENCES members(id) ON DELETE CASCADE,
    vehicle_type_id UUID NOT NULL REFERENCES vehicle_types(id) ON DELETE CASCADE,
    police_number   VARCHAR(20) NOT NULL UNIQUE,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- -----------------------------------------------------------------------------
-- LEVEL 2 TABLES (foreign keys to level 1 tables)
-- -----------------------------------------------------------------------------

-- member_subscriptions
CREATE TABLE IF NOT EXISTS member_subscriptions (
    id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    member_id  UUID NOT NULL REFERENCES members(id) ON DELETE CASCADE,
    plan_id    UUID NOT NULL REFERENCES subscription_plans(id) ON DELETE CASCADE,
    start_date TIMESTAMPTZ NOT NULL,
    end_date   TIMESTAMPTZ NOT NULL,
    status     VARCHAR(20) NOT NULL DEFAULT 'active',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- operator_sessions
CREATE TABLE IF NOT EXISTS operator_sessions (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id     UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    shift_id    UUID NOT NULL REFERENCES shifts(id) ON DELETE CASCADE,
    gate_id     UUID NOT NULL REFERENCES gates(id) ON DELETE CASCADE,
    login_time  TIMESTAMPTZ NOT NULL,
    logout_time TIMESTAMPTZ,
    status      operator_session_status NOT NULL DEFAULT 'active',
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- operator_shift_assignments
CREATE TABLE IF NOT EXISTS operator_shift_assignments (
    id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    operator_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    shift_id   UUID NOT NULL REFERENCES shifts(id) ON DELETE CASCADE,
    status     operator_shift_assignment_status NOT NULL DEFAULT 'active',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_operator_shift_assignment UNIQUE (operator_id, shift_id)
);

-- signage_assignments
CREATE TABLE IF NOT EXISTS signage_assignments (
    id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    signage_id UUID NOT NULL REFERENCES signages(id) ON DELETE CASCADE,
    content_id UUID NOT NULL REFERENCES signage_contents(id) ON DELETE CASCADE,
    is_active  BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_signage_assignment UNIQUE (signage_id, content_id)
);

-- signage_schedules
CREATE TABLE IF NOT EXISTS signage_schedules (
    id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    signage_id UUID NOT NULL REFERENCES signages(id) ON DELETE CASCADE,
    content_id UUID NOT NULL REFERENCES signage_contents(id) ON DELETE CASCADE,
    start_time TIME NOT NULL,
    end_time   TIME NOT NULL,
    is_active  BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- backups
CREATE TABLE IF NOT EXISTS backups (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    filename         VARCHAR(255) NOT NULL UNIQUE,
    format           VARCHAR(10) NOT NULL DEFAULT 'custom',
    size_bytes       BIGINT NOT NULL DEFAULT 0,
    progress         INTEGER NOT NULL DEFAULT 0,
    status           backup_status NOT NULL DEFAULT 'completed',
    error_message    TEXT,
    created_by       UUID REFERENCES users(id) ON DELETE SET NULL,
    last_restored_at TIMESTAMPTZ,
    last_restored_by UUID REFERENCES users(id) ON DELETE SET NULL,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- audit_logs
CREATE TABLE IF NOT EXISTS audit_logs (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id     UUID REFERENCES users(id) ON DELETE SET NULL,
    role        VARCHAR(20),
    module      VARCHAR(50) NOT NULL,
    action      VARCHAR(50) NOT NULL,
    description TEXT,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- -----------------------------------------------------------------------------
-- LEVEL 3 TABLES (foreign keys to level 2 tables)
-- -----------------------------------------------------------------------------

-- park_transactions (includes ALL gate-cycle and transaction-method columns)
CREATE TABLE IF NOT EXISTS park_transactions (
    id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    ticket_number     VARCHAR UNIQUE,
    police_number     VARCHAR,
    vehicle_type_id   UUID NOT NULL REFERENCES vehicle_types(id) ON DELETE CASCADE,
    member_vehicle_id UUID REFERENCES member_vehicles(id) ON DELETE SET NULL,
    entry_time        TIMESTAMPTZ NOT NULL,
    exit_time         TIMESTAMPTZ,
    entry_gate_id     UUID NOT NULL REFERENCES gates(id) ON DELETE CASCADE,
    exit_gate_id      UUID REFERENCES gates(id) ON DELETE SET NULL,
    entry_shift_id    UUID REFERENCES shifts(id) ON DELETE SET NULL,
    exit_shift_id     UUID REFERENCES shifts(id) ON DELETE SET NULL,
    entry_operator_id UUID REFERENCES users(id) ON DELETE SET NULL,
    exit_operator_id  UUID REFERENCES users(id) ON DELETE SET NULL,
    parking_rate_id   UUID REFERENCES parking_rates(id) ON DELETE SET NULL,
    status_parking    parking_status NOT NULL DEFAULT 'Parked',
    is_member         BOOLEAN NOT NULL DEFAULT FALSE,
    total_fee         INTEGER NOT NULL DEFAULT 0,
    detection_method  detection_method NOT NULL,
    transaction_method VARCHAR(16) NOT NULL DEFAULT 'normal',
    card_number       VARCHAR(255),
    payment_status    VARCHAR(20),
    payment_type      VARCHAR(10) NOT NULL DEFAULT 'cash',
    paid_at           TIMESTAMPTZ,
    duration          VARCHAR(255),
    plate_out         VARCHAR,
    keterangan        TEXT,
    cam_in            VARCHAR(255) NOT NULL DEFAULT '-',
    camin_lpr         VARCHAR(255),
    cam_out           VARCHAR(255),
    camout_lpr        VARCHAR(255),
    cam_payment       VARCHAR(255),
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- -----------------------------------------------------------------------------
-- LEVEL 4 TABLES (foreign keys to level 3 tables)
-- -----------------------------------------------------------------------------

-- payments
CREATE TABLE IF NOT EXISTS payments (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    park_transaction_id UUID NOT NULL REFERENCES park_transactions(id) ON DELETE CASCADE,
    amount              INTEGER NOT NULL,
    method              payment_method NOT NULL,
    status              payment_status NOT NULL DEFAULT 'Pending',
    reference_number    VARCHAR,
    paid_at             TIMESTAMPTZ,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- =============================================================================
-- 3) BACKFILL for legacy migrations that required existing-row updates
--    (safe no-ops when tables are freshly created / already backfilled)
-- =============================================================================

-- subscription_plans: guarantee vehicle_type_id is populated (migration 2026-08-30)
UPDATE subscription_plans sp
SET vehicle_type_id = (
    SELECT vt.id
    FROM vehicle_types vt
    ORDER BY (vt.status = 'active') DESC, vt.code
    LIMIT 1
)
WHERE sp.vehicle_type_id IS NULL;

-- park_transactions.transaction_method: backfill history from keterangan (2026-08-31)
UPDATE park_transactions
SET transaction_method = 'lost'
WHERE transaction_method IS NULL
  AND lower(COALESCE(keterangan, '')) LIKE '%tiket hilang%';

UPDATE park_transactions
SET transaction_method = 'manual'
WHERE transaction_method IS NULL
  AND lower(COALESCE(keterangan, '')) LIKE '%tiket tidak cetak%';

UPDATE park_transactions
SET transaction_method = 'normal'
WHERE transaction_method IS NULL;
