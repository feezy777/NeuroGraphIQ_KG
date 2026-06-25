-- MVP 1 Human Review — candidate_review_records
-- Manual execution only; application does NOT auto-run this file.
--
-- Depends on:
--   001_resource_registry.sql, 002_resource_files.sql, 003_import_batches.sql,
--   004_raw_parsing_aal3.sql, 005_candidate_db.sql, 006_rule_validation.sql
-- Human review side ONLY. Does NOT write final_* / kg_*, does NOT promote.
-- manual_approved != promoted_to_final. manual_rejected is NOT deleted.
--
-- The "review queue" is a query over candidate_brain_regions.candidate_status =
-- 'manual_review_pending' (no separate queue table). This file only records review
-- actions/audit; it does NOT alter import_batch_events (review is decoupled from the
-- Import Batch state machine).

CREATE TABLE IF NOT EXISTS candidate_review_records (
    id                  UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    candidate_id        UUID NOT NULL REFERENCES candidate_brain_regions(id) ON DELETE RESTRICT,
    batch_id            UUID NOT NULL REFERENCES import_batches(id) ON DELETE RESTRICT,
    resource_id         UUID NOT NULL REFERENCES atlas_resources(id) ON DELETE RESTRICT,
    generation_run_id   UUID NOT NULL REFERENCES candidate_generation_runs(id) ON DELETE RESTRICT,
    parse_run_id        UUID NOT NULL REFERENCES raw_parse_runs(id) ON DELETE RESTRICT,
    action              VARCHAR(32) NOT NULL,
    from_status         VARCHAR(64) NOT NULL,
    to_status           VARCHAR(64) NOT NULL,
    reviewed_by         VARCHAR(256) NOT NULL,
    reason              TEXT,
    snapshot            JSONB NOT NULL DEFAULT '{}',
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT chk_candidate_review_action CHECK (
        action IN ('submit', 'approve', 'reject', 'request_changes', 'mark_uncertain')
    )
);

CREATE INDEX IF NOT EXISTS idx_candidate_review_candidate ON candidate_review_records (candidate_id);
CREATE INDEX IF NOT EXISTS idx_candidate_review_batch ON candidate_review_records (batch_id);
CREATE INDEX IF NOT EXISTS idx_candidate_review_resource ON candidate_review_records (resource_id);
CREATE INDEX IF NOT EXISTS idx_candidate_review_action ON candidate_review_records (action);
CREATE INDEX IF NOT EXISTS idx_candidate_review_created ON candidate_review_records (created_at);
