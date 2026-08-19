-- 2026_08_19_system_config.sql
-- Runtime configuration overrides persisted in the DB (e.g. MQTT broker
-- settings editable from the Teknisi portal). Values win over env defaults
-- and are merged at startup ("applies on restart").
CREATE TABLE IF NOT EXISTS system_config (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    section VARCHAR(50) NOT NULL,
    key VARCHAR(100) NOT NULL,
    value JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_system_config_section_key UNIQUE (section, key)
);