-- MVP 1 File Upload & File Management — resource_files
-- Manual execution only; application does NOT auto-run this file.
--
-- Depends on: backend/migrations/001_resource_registry.sql (atlas_resources with id UUID PK).
-- Does NOT reference candidate_*, final_*, or kg_* tables.

CREATE TABLE IF NOT EXISTS resource_files (
    id                  UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    resource_id         UUID NOT NULL REFERENCES atlas_resources(id) ON DELETE RESTRICT,
    file_code           VARCHAR(128),
    original_filename   VARCHAR(500) NOT NULL,
    stored_filename     VARCHAR(500) NOT NULL,
    storage_path        VARCHAR(1000) NOT NULL,
    file_ext            VARCHAR(32) NOT NULL DEFAULT '',
    mime_type           VARCHAR(128),
    file_size           BIGINT NOT NULL,
    sha256              CHAR(64) NOT NULL,
    file_type           VARCHAR(64) NOT NULL DEFAULT 'other',
    file_role           VARCHAR(64) NOT NULL DEFAULT 'unknown',
    status              VARCHAR(32) NOT NULL DEFAULT 'active',
    description         TEXT,
    remark              TEXT,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    deleted_at          TIMESTAMPTZ,
    CONSTRAINT chk_resource_files_status CHECK (
        status IN ('active', 'archived')
    ),
    CONSTRAINT chk_resource_files_file_type CHECK (
        file_type IN (
            'nifti',
            'label_table',
            'spreadsheet',
            'pdf',
            'ontology',
            'json',
            'text',
            'connectivity_matrix',
            'image',
            'other'
        )
    ),
    CONSTRAINT chk_resource_files_file_role CHECK (
        file_role IN (
            'primary_atlas_volume',
            'label_dictionary',
            'documentation',
            'ontology_source',
            'connectivity_source',
            'evidence_source',
            'metadata',
            'auxiliary',
            'unknown'
        )
    ),
    CONSTRAINT chk_resource_files_sha256_format CHECK (
        sha256 ~ '^[a-f0-9]{64}$'
    )
);

CREATE INDEX IF NOT EXISTS idx_resource_files_resource_id
    ON resource_files (resource_id);
CREATE INDEX IF NOT EXISTS idx_resource_files_sha256
    ON resource_files (sha256);
CREATE INDEX IF NOT EXISTS idx_resource_files_file_type
    ON resource_files (file_type);
CREATE INDEX IF NOT EXISTS idx_resource_files_file_role
    ON resource_files (file_role);
CREATE INDEX IF NOT EXISTS idx_resource_files_status
    ON resource_files (status);

-- One active record per (resource_id, sha256); archived rows excluded.
CREATE UNIQUE INDEX IF NOT EXISTS uq_resource_files_resource_sha256_active
    ON resource_files (resource_id, sha256)
    WHERE deleted_at IS NULL;

DROP TRIGGER IF EXISTS trg_resource_files_updated_at ON resource_files;
CREATE TRIGGER trg_resource_files_updated_at
    BEFORE UPDATE ON resource_files
    FOR EACH ROW EXECUTE FUNCTION update_updated_at();
