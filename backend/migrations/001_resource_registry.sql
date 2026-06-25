-- MVP 1 Resource Registry — atlas_resources
-- Manual execution only; application does NOT auto-run this file.
--
-- NOTE: Legacy 20260520_coarse_grain_schema.sql defines a different atlas_resources
-- (atlas_code / atlas_name). For greenfield MVP1 rebuild, use a fresh database or
-- drop legacy atlas_resources (and dependent atlas_labels) before applying this DDL.

CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

CREATE TABLE IF NOT EXISTS atlas_resources (
    id                  UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    resource_code       VARCHAR(128) NOT NULL,
    source_atlas        VARCHAR(128) NOT NULL,
    source_version      VARCHAR(64) NOT NULL,
    resource_type       VARCHAR(64) NOT NULL DEFAULT 'atlas',
    species             VARCHAR(32) NOT NULL DEFAULT 'human',
    granularity_level   VARCHAR(32) NOT NULL,
    granularity_family  VARCHAR(64) NOT NULL,
    template_space      VARCHAR(64) NOT NULL DEFAULT 'unknown',
    cn_name             VARCHAR(500),
    en_name             VARCHAR(500),
    description         TEXT,
    remark              TEXT,
    status              VARCHAR(32) NOT NULL DEFAULT 'active',
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    deleted_at          TIMESTAMPTZ,
    CONSTRAINT uq_atlas_resources_resource_code UNIQUE (resource_code),
    CONSTRAINT chk_atlas_resources_status CHECK (
        status IN ('active', 'inactive', 'archived')
    ),
    CONSTRAINT chk_atlas_resources_granularity_level CHECK (
        granularity_level IN ('macro', 'meso', 'micro', 'molecular', 'term')
    ),
    CONSTRAINT chk_atlas_resources_granularity_family CHECK (
        granularity_family IN (
            'macro_clinical',
            'meso_anatomical',
            'subregion_connectivity',
            'cytoarchitectonic',
            'histological',
            'molecular',
            'terminology'
        )
    ),
    CONSTRAINT chk_atlas_resources_resource_type CHECK (
        resource_type IN (
            'atlas',
            'label_table',
            'ontology',
            'connectivity_matrix',
            'literature',
            'terminology'
        )
    ),
    CONSTRAINT chk_atlas_resources_species CHECK (
        species IN ('human', 'mouse', 'unknown')
    ),
    CONSTRAINT chk_atlas_resources_template_space CHECK (
        template_space IN ('MNI152', 'fsaverage', 'native', 'unknown', 'not_applicable')
    )
);

CREATE INDEX IF NOT EXISTS idx_atlas_resources_source_atlas
    ON atlas_resources (source_atlas);
CREATE INDEX IF NOT EXISTS idx_atlas_resources_granularity_level
    ON atlas_resources (granularity_level);
CREATE INDEX IF NOT EXISTS idx_atlas_resources_granularity_family
    ON atlas_resources (granularity_family);
CREATE INDEX IF NOT EXISTS idx_atlas_resources_status
    ON atlas_resources (status);
CREATE INDEX IF NOT EXISTS idx_atlas_resources_deleted_at
    ON atlas_resources (deleted_at)
    WHERE deleted_at IS NULL;

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_proc WHERE proname = 'update_updated_at') THEN
        CREATE OR REPLACE FUNCTION update_updated_at()
        RETURNS TRIGGER AS $fn$
        BEGIN
            NEW.updated_at = NOW();
            RETURN NEW;
        END;
        $fn$ LANGUAGE plpgsql;
    END IF;
END $$;

DROP TRIGGER IF EXISTS trg_atlas_resources_updated_at ON atlas_resources;
CREATE TRIGGER trg_atlas_resources_updated_at
    BEFORE UPDATE ON atlas_resources
    FOR EACH ROW EXECUTE FUNCTION update_updated_at();
