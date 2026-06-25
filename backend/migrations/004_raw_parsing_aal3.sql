-- MVP 1 Raw Parsing for AAL3 — raw_parse_runs, raw_aal3_region_labels
-- Manual execution only; application does NOT auto-run this file.
--
-- Depends on:
--   001_resource_registry.sql, 002_resource_files.sql, 003_import_batches.sql
-- Does NOT reference candidate_*, final_*, or kg_* tables.

-- Extend import_batch_events event_type for parse lifecycle (003 constraint extension).
ALTER TABLE import_batch_events DROP CONSTRAINT IF EXISTS chk_import_batch_events_type;
ALTER TABLE import_batch_events ADD CONSTRAINT chk_import_batch_events_type CHECK (
    event_type IN (
        'created',
        'file_attached',
        'status_changed',
        'cancelled',
        'failed',
        'completed',
        'note',
        'parse_started',
        'parse_succeeded',
        'parse_failed'
    )
);

CREATE TABLE IF NOT EXISTS raw_parse_runs (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    batch_id        UUID NOT NULL REFERENCES import_batches(id) ON DELETE RESTRICT,
    resource_id     UUID NOT NULL REFERENCES atlas_resources(id) ON DELETE RESTRICT,
    parser_key      VARCHAR(128) NOT NULL,
    parser_version  VARCHAR(64) NOT NULL DEFAULT 'v1',
    status          VARCHAR(32) NOT NULL DEFAULT 'created',
    input_file_ids  JSONB NOT NULL DEFAULT '[]',
    output_count    INTEGER NOT NULL DEFAULT 0,
    warning_count   INTEGER NOT NULL DEFAULT 0,
    error_message   TEXT,
    started_at      TIMESTAMPTZ,
    finished_at     TIMESTAMPTZ,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT chk_raw_parse_runs_status CHECK (
        status IN ('created', 'running', 'succeeded', 'failed')
    )
);

CREATE TABLE IF NOT EXISTS raw_aal3_region_labels (
    id                  UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    parse_run_id        UUID NOT NULL REFERENCES raw_parse_runs(id) ON DELETE RESTRICT,
    batch_id            UUID NOT NULL REFERENCES import_batches(id) ON DELETE RESTRICT,
    resource_id         UUID NOT NULL REFERENCES atlas_resources(id) ON DELETE RESTRICT,
    source_file_id      UUID NOT NULL REFERENCES resource_files(id) ON DELETE RESTRICT,
    source_atlas        VARCHAR(128) NOT NULL,
    source_version      VARCHAR(64) NOT NULL,
    source_label_id     VARCHAR(128),
    label_value         INTEGER,
    raw_name            VARCHAR(500) NOT NULL,
    en_name             VARCHAR(500),
    cn_name             VARCHAR(500),
    laterality          VARCHAR(32) NOT NULL DEFAULT 'unknown',
    region_base_name    VARCHAR(500),
    raw_payload         JSONB NOT NULL,
    row_index           INTEGER NOT NULL DEFAULT 0,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT chk_raw_aal3_laterality CHECK (
        laterality IN ('left', 'right', 'bilateral', 'midline', 'unknown')
    )
);

CREATE INDEX IF NOT EXISTS idx_raw_parse_runs_batch_id ON raw_parse_runs (batch_id);
CREATE INDEX IF NOT EXISTS idx_raw_parse_runs_resource_id ON raw_parse_runs (resource_id);
CREATE INDEX IF NOT EXISTS idx_raw_parse_runs_parser_key ON raw_parse_runs (parser_key);
CREATE INDEX IF NOT EXISTS idx_raw_parse_runs_status ON raw_parse_runs (status);

CREATE UNIQUE INDEX IF NOT EXISTS uq_raw_parse_runs_batch_parser_succeeded
    ON raw_parse_runs (batch_id, parser_key)
    WHERE status = 'succeeded';

CREATE INDEX IF NOT EXISTS idx_raw_aal3_labels_parse_run ON raw_aal3_region_labels (parse_run_id);
CREATE INDEX IF NOT EXISTS idx_raw_aal3_labels_batch_id ON raw_aal3_region_labels (batch_id);
CREATE INDEX IF NOT EXISTS idx_raw_aal3_labels_resource_id ON raw_aal3_region_labels (resource_id);
CREATE INDEX IF NOT EXISTS idx_raw_aal3_labels_laterality ON raw_aal3_region_labels (laterality);

CREATE UNIQUE INDEX IF NOT EXISTS uq_raw_aal3_labels_run_file_row
    ON raw_aal3_region_labels (parse_run_id, source_file_id, row_index);

CREATE UNIQUE INDEX IF NOT EXISTS uq_raw_aal3_labels_run_label_value
    ON raw_aal3_region_labels (parse_run_id, label_value)
    WHERE label_value IS NOT NULL;

DROP TRIGGER IF EXISTS trg_raw_parse_runs_updated_at ON raw_parse_runs;
CREATE TRIGGER trg_raw_parse_runs_updated_at
    BEFORE UPDATE ON raw_parse_runs
    FOR EACH ROW EXECUTE FUNCTION update_updated_at();
