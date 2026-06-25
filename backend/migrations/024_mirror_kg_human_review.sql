-- MVP 2 Step 8 — Mirror KG Human Review records
-- Manual execution only; application does NOT auto-run this file.
--
-- Depends on: 001_resource_registry.sql, 003_import_batches.sql, 022_mirror_kg_schema.sql
-- Human review side ONLY for mirror connections/functions/circuits/triples.
-- Does NOT write final_* / kg_*. human_approved != promoted_to_final.

CREATE TABLE IF NOT EXISTS mirror_human_review_records (
    id                      UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    target_type             TEXT NOT NULL,
    target_id               UUID NOT NULL,
    action                  TEXT NOT NULL,
    from_mirror_status      TEXT NULL,
    to_mirror_status        TEXT NULL,
    from_review_status      TEXT NULL,
    to_review_status        TEXT NULL,
    from_promotion_status   TEXT NULL,
    to_promotion_status     TEXT NULL,
    reviewer                TEXT NOT NULL,
    reviewer_note           TEXT NULL,
    edit_patch_json         JSONB NOT NULL DEFAULT '{}'::jsonb,
    before_json             JSONB NOT NULL DEFAULT '{}'::jsonb,
    after_json              JSONB NOT NULL DEFAULT '{}'::jsonb,
    validation_summary_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    evidence_summary_json   JSONB NOT NULL DEFAULT '{}'::jsonb,
    resource_id             UUID NULL REFERENCES atlas_resources(id) ON DELETE SET NULL,
    batch_id                UUID NULL REFERENCES import_batches(id) ON DELETE SET NULL,
    source_atlas            TEXT NULL,
    source_version          TEXT NULL,
    granularity_level       TEXT NULL,
    granularity_family      TEXT NULL,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT chk_mirror_review_target_type CHECK (
        target_type IN ('connection', 'function', 'circuit', 'triple')
    ),
    CONSTRAINT chk_mirror_review_action CHECK (
        action IN ('approve', 'reject', 'needs_revision', 'edit', 'comment')
    )
);

CREATE INDEX IF NOT EXISTS idx_mirror_review_target
    ON mirror_human_review_records (target_type, target_id);
CREATE INDEX IF NOT EXISTS idx_mirror_review_action
    ON mirror_human_review_records (action);
CREATE INDEX IF NOT EXISTS idx_mirror_review_reviewer
    ON mirror_human_review_records (reviewer);
CREATE INDEX IF NOT EXISTS idx_mirror_review_resource
    ON mirror_human_review_records (resource_id);
CREATE INDEX IF NOT EXISTS idx_mirror_review_batch
    ON mirror_human_review_records (batch_id);
CREATE INDEX IF NOT EXISTS idx_mirror_review_source_atlas
    ON mirror_human_review_records (source_atlas);
CREATE INDEX IF NOT EXISTS idx_mirror_review_created_at
    ON mirror_human_review_records (created_at);
