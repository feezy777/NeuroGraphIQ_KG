-- MVP 1 Candidate DB — candidate_generation_runs, candidate_brain_regions
-- Manual execution only; application does NOT auto-run this file.
--
-- Depends on:
--   001_resource_registry.sql, 002_resource_files.sql,
--   003_import_batches.sql, 004_raw_parsing_aal3.sql
-- Candidate side ONLY. Does NOT reference final_* or kg_* tables.
-- candidate_created != manual_approved != promoted_to_final.

-- Extend import_batch_events event_type for candidate generation lifecycle.
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
        'candidate_generation_started',
        'candidate_generation_succeeded',
        'candidate_generation_failed'
    )
);

CREATE TABLE IF NOT EXISTS candidate_generation_runs (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    batch_id        UUID NOT NULL REFERENCES import_batches(id) ON DELETE RESTRICT,
    resource_id     UUID NOT NULL REFERENCES atlas_resources(id) ON DELETE RESTRICT,
    parse_run_id    UUID NOT NULL REFERENCES raw_parse_runs(id) ON DELETE RESTRICT,
    generator_key   VARCHAR(128) NOT NULL DEFAULT 'aal3_region_candidate',
    generator_version VARCHAR(64) NOT NULL DEFAULT 'v1',
    status          VARCHAR(32) NOT NULL DEFAULT 'created',
    output_count    INTEGER NOT NULL DEFAULT 0,
    skipped_count   INTEGER NOT NULL DEFAULT 0,
    error_message   TEXT,
    started_at      TIMESTAMPTZ,
    finished_at     TIMESTAMPTZ,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT chk_candidate_gen_runs_status CHECK (
        status IN ('created', 'running', 'succeeded', 'failed')
    )
);

-- Idempotency: one succeeded generation run per (batch_id, parse_run_id).
CREATE UNIQUE INDEX IF NOT EXISTS uq_candidate_gen_runs_batch_parse_succeeded
    ON candidate_generation_runs (batch_id, parse_run_id)
    WHERE status = 'succeeded';

CREATE TABLE IF NOT EXISTS candidate_brain_regions (
    id                  UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    generation_run_id   UUID NOT NULL REFERENCES candidate_generation_runs(id) ON DELETE RESTRICT,
    batch_id            UUID NOT NULL REFERENCES import_batches(id) ON DELETE RESTRICT,
    resource_id         UUID NOT NULL REFERENCES atlas_resources(id) ON DELETE RESTRICT,
    parse_run_id        UUID NOT NULL REFERENCES raw_parse_runs(id) ON DELETE RESTRICT,
    source_raw_label_id UUID NOT NULL REFERENCES raw_aal3_region_labels(id) ON DELETE RESTRICT,
    source_file_id      UUID NOT NULL REFERENCES resource_files(id) ON DELETE RESTRICT,
    source_atlas        VARCHAR(128) NOT NULL,
    source_version      VARCHAR(64) NOT NULL,
    source_label_id     VARCHAR(128),
    label_value         INTEGER,
    raw_name            VARCHAR(500) NOT NULL,
    std_name            VARCHAR(500),
    en_name             VARCHAR(500),
    cn_name             VARCHAR(500),
    laterality          VARCHAR(32) NOT NULL DEFAULT 'unknown',
    region_base_name    VARCHAR(500),
    granularity_level   VARCHAR(32) NOT NULL,
    granularity_family  VARCHAR(64) NOT NULL,
    candidate_status    VARCHAR(64) NOT NULL DEFAULT 'candidate_created',
    raw_payload         JSONB NOT NULL,
    row_index           INTEGER NOT NULL DEFAULT 0,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT chk_candidate_region_laterality CHECK (
        laterality IN ('left', 'right', 'bilateral', 'midline', 'unknown')
    ),
    CONSTRAINT chk_candidate_region_status CHECK (
        candidate_status IN (
            'candidate_created',
            'rule_validating',
            'rule_passed',
            'rule_failed',
            'llm_not_required',
            'llm_validating',
            'llm_passed',
            'llm_conflict',
            'manual_review_pending',
            'manual_approved',
            'manual_rejected',
            'archived'
        )
    )
);

-- One candidate per source raw label within a generation run (no auto-merge of same-name regions).
CREATE UNIQUE INDEX IF NOT EXISTS uq_candidate_region_run_source_label
    ON candidate_brain_regions (generation_run_id, source_raw_label_id);

CREATE INDEX IF NOT EXISTS idx_candidate_gen_runs_batch ON candidate_generation_runs (batch_id);
CREATE INDEX IF NOT EXISTS idx_candidate_gen_runs_resource ON candidate_generation_runs (resource_id);
CREATE INDEX IF NOT EXISTS idx_candidate_gen_runs_parse_run ON candidate_generation_runs (parse_run_id);
CREATE INDEX IF NOT EXISTS idx_candidate_gen_runs_status ON candidate_generation_runs (status);

CREATE INDEX IF NOT EXISTS idx_candidate_regions_gen_run ON candidate_brain_regions (generation_run_id);
CREATE INDEX IF NOT EXISTS idx_candidate_regions_batch ON candidate_brain_regions (batch_id);
CREATE INDEX IF NOT EXISTS idx_candidate_regions_resource ON candidate_brain_regions (resource_id);
CREATE INDEX IF NOT EXISTS idx_candidate_regions_parse_run ON candidate_brain_regions (parse_run_id);
CREATE INDEX IF NOT EXISTS idx_candidate_regions_status ON candidate_brain_regions (candidate_status);
CREATE INDEX IF NOT EXISTS idx_candidate_regions_laterality ON candidate_brain_regions (laterality);

DROP TRIGGER IF EXISTS trg_candidate_gen_runs_updated_at ON candidate_generation_runs;
CREATE TRIGGER trg_candidate_gen_runs_updated_at
    BEFORE UPDATE ON candidate_generation_runs
    FOR EACH ROW EXECUTE FUNCTION update_updated_at();

DROP TRIGGER IF EXISTS trg_candidate_regions_updated_at ON candidate_brain_regions;
CREATE TRIGGER trg_candidate_regions_updated_at
    BEFORE UPDATE ON candidate_brain_regions
    FOR EACH ROW EXECUTE FUNCTION update_updated_at();
