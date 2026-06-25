-- Macro96 Raw Parsing — raw_macro96_region_rows
-- Manual execution only; application does NOT auto-run this file.
--
-- Depends on:
--   001_resource_registry.sql, 002_resource_files.sql, 003_import_batches.sql,
--   004_raw_parsing_aal3.sql (raw_parse_runs)
-- Does NOT reference candidate_*, final_*, or kg_* tables.

-- Extend import_batch_events event_type CHECK for macro96 parse lifecycle.
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
        'parse_failed',
        'parse_macro96_started',
        'parse_macro96_succeeded',
        'parse_macro96_failed'
    )
);

CREATE TABLE IF NOT EXISTS raw_macro96_region_rows (
    id                          UUID PRIMARY KEY DEFAULT uuid_generate_v4(),

    parse_run_id                UUID NOT NULL REFERENCES raw_parse_runs(id) ON DELETE CASCADE,
    resource_id                 UUID NOT NULL REFERENCES atlas_resources(id) ON DELETE RESTRICT,
    batch_id                    UUID NOT NULL REFERENCES import_batches(id) ON DELETE RESTRICT,
    source_file_id              UUID NOT NULL REFERENCES resource_files(id) ON DELETE RESTRICT,
    intermediate_artifact_id    UUID NULL,

    row_index                   INTEGER NOT NULL,
    region_index                INTEGER NOT NULL,
    en_name                     TEXT NOT NULL,
    cn_name                     TEXT NULL,

    raw_brain_structure         TEXT NULL,
    raw_cn_name                 TEXT NULL,
    source_sheet                TEXT NULL,

    parser_key                  TEXT NOT NULL DEFAULT 'macro96_xlsx',
    parser_version              TEXT NOT NULL DEFAULT 'v1',
    raw_payload                 JSONB NOT NULL DEFAULT '{}'::jsonb,

    created_at                  TIMESTAMPTZ NOT NULL DEFAULT now(),

    CONSTRAINT chk_raw_macro96_region_index_positive
        CHECK (region_index > 0),
    CONSTRAINT chk_raw_macro96_row_index_non_negative
        CHECK (row_index >= 0)
);

CREATE INDEX IF NOT EXISTS idx_raw_macro96_parse_run
    ON raw_macro96_region_rows(parse_run_id);

CREATE INDEX IF NOT EXISTS idx_raw_macro96_resource
    ON raw_macro96_region_rows(resource_id);

CREATE INDEX IF NOT EXISTS idx_raw_macro96_batch
    ON raw_macro96_region_rows(batch_id);

CREATE INDEX IF NOT EXISTS idx_raw_macro96_source_file
    ON raw_macro96_region_rows(source_file_id);

CREATE INDEX IF NOT EXISTS idx_raw_macro96_region_index
    ON raw_macro96_region_rows(region_index);

CREATE INDEX IF NOT EXISTS idx_raw_macro96_en_name
    ON raw_macro96_region_rows(en_name);

CREATE UNIQUE INDEX IF NOT EXISTS uq_raw_macro96_run_row_index
    ON raw_macro96_region_rows(parse_run_id, row_index);

CREATE UNIQUE INDEX IF NOT EXISTS uq_raw_macro96_run_region_index
    ON raw_macro96_region_rows(parse_run_id, region_index);
