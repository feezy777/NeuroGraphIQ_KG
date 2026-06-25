-- Macro96 Event Constraint Fix + raw_macro96_region_rows table creation
-- Manual execution only; application does NOT auto-run this file.
--
-- Context:
--   Migration 016_raw_parsing_macro96.sql was never applied to dev DB because
--   its event_type constraint rebuild would have dropped candidate_generation_*
--   and rule_validation_* (which exist as live events in import_batch_events).
--
--   This migration supersedes 016's constraint changes:
--   1. Creates raw_macro96_region_rows (IF NOT EXISTS — idempotent).
--   2. Rebuilds chk_import_batch_events_type with the FULL event_type set:
--      original (003) + parse lifecycle (004) + candidate (005) +
--      rule_validation (006) + macro96 parse (new).
--
-- Depends on: 001..006, 016 (for uuid_generate_v4 and referenced tables).
-- Does NOT reference candidate_*, final_*, or kg_* tables.
-- Does NOT generate candidates, does NOT write final_* or kg_*, does NOT call LLM.

-- ─── 1. Create raw_macro96_region_rows (idempotent) ──────────────────────────

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


-- ─── 2. Rebuild import_batch_events CHECK constraint ─────────────────────────
-- Rebuilds with full cumulative event_type list:
--   003 originals + 004 parse lifecycle + 005 candidate + 006 rule_validation
--   + this migration: parse_macro96 lifecycle

ALTER TABLE import_batch_events
    DROP CONSTRAINT IF EXISTS chk_import_batch_events_type;

ALTER TABLE import_batch_events
    ADD CONSTRAINT chk_import_batch_events_type CHECK (
        event_type IN (
            -- 003 originals
            'created',
            'file_attached',
            'status_changed',
            'cancelled',
            'failed',
            'completed',
            'note',

            -- 004 parse lifecycle (AAL3 / generic raw parse)
            'parse_started',
            'parse_succeeded',
            'parse_failed',

            -- 005 candidate generation lifecycle
            'candidate_generation_started',
            'candidate_generation_succeeded',
            'candidate_generation_failed',

            -- 006 rule validation lifecycle
            'rule_validation_started',
            'rule_validation_succeeded',
            'rule_validation_failed',

            -- 017 Macro96 parse lifecycle (new)
            'parse_macro96_started',
            'parse_macro96_succeeded',
            'parse_macro96_failed'
        )
    );
