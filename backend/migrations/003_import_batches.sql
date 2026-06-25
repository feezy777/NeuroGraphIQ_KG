-- MVP 1 Import Batch / Task — import_batches, import_batch_files, import_batch_events
-- Manual execution only; application does NOT auto-run this file.
--
-- Depends on:
--   backend/migrations/001_resource_registry.sql (atlas_resources)
--   backend/migrations/002_resource_files.sql (resource_files)
-- Does NOT reference candidate_*, final_*, or kg_* tables.

CREATE TABLE IF NOT EXISTS import_batches (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    batch_code      VARCHAR(128) NOT NULL,
    resource_id     UUID NOT NULL REFERENCES atlas_resources(id) ON DELETE RESTRICT,
    batch_type      VARCHAR(64) NOT NULL,
    parser_key      VARCHAR(128),
    status          VARCHAR(64) NOT NULL DEFAULT 'created',
    description     TEXT,
    remark          TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    started_at      TIMESTAMPTZ,
    finished_at     TIMESTAMPTZ,
    failed_at       TIMESTAMPTZ,
    cancelled_at    TIMESTAMPTZ,
    error_message   TEXT,
    CONSTRAINT uq_import_batches_batch_code UNIQUE (batch_code),
    CONSTRAINT chk_import_batches_status CHECK (
        status IN (
            'created',
            'queued',
            'running',
            'parsed',
            'candidate_generated',
            'validation_dispatched',
            'completed',
            'failed',
            'cancelled'
        )
    ),
    CONSTRAINT chk_import_batches_batch_type CHECK (
        batch_type IN (
            'atlas_import',
            'label_import',
            'ontology_import',
            'connectivity_import',
            'evidence_import',
            'metadata_import'
        )
    )
);

CREATE TABLE IF NOT EXISTS import_batch_files (
    id                  UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    batch_id            UUID NOT NULL REFERENCES import_batches(id) ON DELETE RESTRICT,
    file_id             UUID NOT NULL REFERENCES resource_files(id) ON DELETE RESTRICT,
    resource_id         UUID NOT NULL REFERENCES atlas_resources(id) ON DELETE RESTRICT,
    file_role_in_batch  VARCHAR(64) NOT NULL DEFAULT 'unknown',
    sort_order          INTEGER NOT NULL DEFAULT 0,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_import_batch_files_batch_file UNIQUE (batch_id, file_id),
    CONSTRAINT chk_import_batch_files_role CHECK (
        file_role_in_batch IN (
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
    )
);

CREATE TABLE IF NOT EXISTS import_batch_events (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    batch_id        UUID NOT NULL REFERENCES import_batches(id) ON DELETE RESTRICT,
    event_type      VARCHAR(64) NOT NULL,
    from_status     VARCHAR(64),
    to_status       VARCHAR(64),
    message         TEXT,
    payload_json    JSONB,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT chk_import_batch_events_type CHECK (
        event_type IN (
            'created',
            'file_attached',
            'status_changed',
            'cancelled',
            'failed',
            'completed',
            'note'
        )
    )
);

CREATE INDEX IF NOT EXISTS idx_import_batches_resource_id ON import_batches (resource_id);
CREATE INDEX IF NOT EXISTS idx_import_batches_status ON import_batches (status);
CREATE INDEX IF NOT EXISTS idx_import_batches_batch_type ON import_batches (batch_type);
CREATE INDEX IF NOT EXISTS idx_import_batches_parser_key ON import_batches (parser_key);
CREATE INDEX IF NOT EXISTS idx_import_batches_created_at ON import_batches (created_at DESC);

CREATE INDEX IF NOT EXISTS idx_import_batch_files_batch_id ON import_batch_files (batch_id);
CREATE INDEX IF NOT EXISTS idx_import_batch_files_file_id ON import_batch_files (file_id);

CREATE INDEX IF NOT EXISTS idx_import_batch_events_batch_id ON import_batch_events (batch_id);
CREATE INDEX IF NOT EXISTS idx_import_batch_events_created_at ON import_batch_events (created_at DESC);

DROP TRIGGER IF EXISTS trg_import_batches_updated_at ON import_batches;
CREATE TRIGGER trg_import_batches_updated_at
    BEFORE UPDATE ON import_batches
    FOR EACH ROW EXECUTE FUNCTION update_updated_at();
