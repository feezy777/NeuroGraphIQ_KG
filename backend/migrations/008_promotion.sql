-- MVP 1 Promotion to final_* — final_brain_regions, promotion_records
-- Manual execution only; application does NOT auto-run this file.
--
-- Depends on:
--   001_resource_registry.sql, 002_resource_files.sql, 003_import_batches.sql,
--   004_raw_parsing_aal3.sql, 005_candidate_db.sql, 006_rule_validation.sql,
--   007_human_review.sql
--
-- This is the ONLY module allowed to write final_* tables. final_brain_regions is a
-- SEPARATE table from candidate_brain_regions (never merged). Promotion writes NEVER
-- touch kg_* or legacy staging_*. Only manual_approved candidates may be promoted.
-- Promotion does NOT alter import_batch_events (decoupled from the Import Batch state
-- machine); promotion_records is the audit trail.

-- Extend the candidate_status CHECK constraint to allow 'promoted_to_final'.
-- 005 created chk_candidate_region_status WITHOUT this value; promoting a candidate
-- sets candidate_status='promoted_to_final', so the constraint MUST accept it.
-- We extend it here (in 008) instead of editing the 005 history file.
-- Risk: this rebuilds the constraint on candidate_brain_regions; it only ADDS one
-- allowed value, so existing rows remain valid.
ALTER TABLE candidate_brain_regions DROP CONSTRAINT IF EXISTS chk_candidate_region_status;
ALTER TABLE candidate_brain_regions ADD CONSTRAINT chk_candidate_region_status CHECK (
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
        'promoted_to_final',
        'archived'
    )
);

CREATE TABLE IF NOT EXISTS final_brain_regions (
    id                          UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    -- Full lineage back to the originating candidate / raw label / batch / resource.
    candidate_id                UUID NOT NULL REFERENCES candidate_brain_regions(id) ON DELETE RESTRICT,
    resource_id                 UUID NOT NULL REFERENCES atlas_resources(id) ON DELETE RESTRICT,
    batch_id                    UUID NOT NULL REFERENCES import_batches(id) ON DELETE RESTRICT,
    parse_run_id                UUID NOT NULL REFERENCES raw_parse_runs(id) ON DELETE RESTRICT,
    generation_run_id           UUID NOT NULL REFERENCES candidate_generation_runs(id) ON DELETE RESTRICT,
    source_file_id              UUID NOT NULL REFERENCES resource_files(id) ON DELETE RESTRICT,
    source_raw_label_id         UUID NOT NULL REFERENCES raw_aal3_region_labels(id) ON DELETE RESTRICT,
    latest_review_record_id     UUID REFERENCES candidate_review_records(id) ON DELETE RESTRICT,
    latest_validation_result_id UUID REFERENCES candidate_rule_validation_results(id) ON DELETE RESTRICT,
    -- Provenance + domain fields (copied from the approved candidate).
    source_atlas                VARCHAR(128) NOT NULL,
    source_version              VARCHAR(64) NOT NULL,
    source_label_id             VARCHAR(128),
    label_value                 INTEGER,
    raw_name                    VARCHAR(500) NOT NULL,
    std_name                    VARCHAR(500),
    en_name                     VARCHAR(500),
    cn_name                     VARCHAR(500),
    laterality                  VARCHAR(32) NOT NULL DEFAULT 'unknown',
    region_base_name            VARCHAR(500),
    granularity_level           VARCHAR(32) NOT NULL,
    granularity_family          VARCHAR(64) NOT NULL,
    status                      VARCHAR(32) NOT NULL DEFAULT 'active',
    promoted_by                 VARCHAR(256) NOT NULL,
    promoted_at                 TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_at                  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at                  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT chk_final_region_laterality CHECK (
        laterality IN ('left', 'right', 'bilateral', 'midline', 'unknown')
    ),
    CONSTRAINT chk_final_region_status CHECK (status IN ('active', 'archived'))
);

-- Idempotency: at most one final region per source candidate.
CREATE UNIQUE INDEX IF NOT EXISTS uq_final_region_candidate
    ON final_brain_regions (candidate_id);

CREATE INDEX IF NOT EXISTS idx_final_region_resource ON final_brain_regions (resource_id);
CREATE INDEX IF NOT EXISTS idx_final_region_batch ON final_brain_regions (batch_id);
CREATE INDEX IF NOT EXISTS idx_final_region_laterality ON final_brain_regions (laterality);
CREATE INDEX IF NOT EXISTS idx_final_region_status ON final_brain_regions (status);

CREATE TABLE IF NOT EXISTS promotion_records (
    id                          UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    candidate_id                UUID NOT NULL REFERENCES candidate_brain_regions(id) ON DELETE RESTRICT,
    final_region_id             UUID REFERENCES final_brain_regions(id) ON DELETE RESTRICT,
    resource_id                 UUID NOT NULL REFERENCES atlas_resources(id) ON DELETE RESTRICT,
    batch_id                    UUID NOT NULL REFERENCES import_batches(id) ON DELETE RESTRICT,
    parse_run_id                UUID NOT NULL REFERENCES raw_parse_runs(id) ON DELETE RESTRICT,
    generation_run_id           UUID NOT NULL REFERENCES candidate_generation_runs(id) ON DELETE RESTRICT,
    source_file_id              UUID NOT NULL REFERENCES resource_files(id) ON DELETE RESTRICT,
    source_raw_label_id         UUID NOT NULL REFERENCES raw_aal3_region_labels(id) ON DELETE RESTRICT,
    latest_review_record_id     UUID REFERENCES candidate_review_records(id) ON DELETE RESTRICT,
    latest_validation_result_id UUID REFERENCES candidate_rule_validation_results(id) ON DELETE RESTRICT,
    status                      VARCHAR(32) NOT NULL DEFAULT 'running',
    from_status                 VARCHAR(64) NOT NULL,
    to_status                   VARCHAR(64) NOT NULL,
    promoted_by                 VARCHAR(256) NOT NULL,
    reason                      TEXT,
    before_snapshot             JSONB NOT NULL DEFAULT '{}',
    after_snapshot              JSONB NOT NULL DEFAULT '{}',
    error_message               TEXT,
    created_at                  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT chk_promotion_record_status CHECK (
        status IN ('running', 'succeeded', 'failed')
    )
);

CREATE INDEX IF NOT EXISTS idx_promotion_records_candidate ON promotion_records (candidate_id);
CREATE INDEX IF NOT EXISTS idx_promotion_records_batch ON promotion_records (batch_id);
CREATE INDEX IF NOT EXISTS idx_promotion_records_resource ON promotion_records (resource_id);
CREATE INDEX IF NOT EXISTS idx_promotion_records_status ON promotion_records (status);
CREATE INDEX IF NOT EXISTS idx_promotion_records_created ON promotion_records (created_at);

DROP TRIGGER IF EXISTS trg_final_brain_regions_updated_at ON final_brain_regions;
CREATE TRIGGER trg_final_brain_regions_updated_at
    BEFORE UPDATE ON final_brain_regions
    FOR EACH ROW EXECUTE FUNCTION update_updated_at();
