-- Audit trail for import batch rollback execute (strong confirmation).
-- Manual execution only; application does NOT auto-run this file.
--
-- No FK to import_batches — audit survives batch archival/deletion.

CREATE TABLE IF NOT EXISTS import_batch_rollback_records (
    id                          UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    batch_id                    UUID NOT NULL,
    batch_code                  TEXT NULL,
    resource_id                 UUID NULL,
    parser_key                  TEXT NULL,
    from_status                 TEXT NOT NULL,
    target_status               TEXT NOT NULL,
    operator                    TEXT NOT NULL,
    reason                      TEXT NOT NULL,
    confirmation_text           TEXT NOT NULL,
    required_confirmation       TEXT NOT NULL,
    risk_level                  TEXT NOT NULL,
    preview_json                JSONB NOT NULL DEFAULT '{}'::jsonb,
    delete_plan_json            JSONB NOT NULL DEFAULT '{}'::jsonb,
    keep_plan_json              JSONB NOT NULL DEFAULT '{}'::jsonb,
    dependency_counts_json      JSONB NOT NULL DEFAULT '{}'::jsonb,
    deleted_counts_json         JSONB NOT NULL DEFAULT '{}'::jsonb,
    kept_counts_json            JSONB NOT NULL DEFAULT '{}'::jsonb,
    status                      TEXT NOT NULL,
    error_message               TEXT NULL,
    started_at                  TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at                 TIMESTAMPTZ NULL,
    created_at                  TIMESTAMPTZ NOT NULL DEFAULT now(),

    CONSTRAINT chk_import_batch_rollback_records_status CHECK (
        status IN ('started', 'succeeded', 'failed')
    ),
    CONSTRAINT chk_import_batch_rollback_records_risk CHECK (
        risk_level IN ('low', 'medium', 'high', 'critical')
    )
);

CREATE INDEX IF NOT EXISTS idx_import_batch_rollback_records_batch_id
    ON import_batch_rollback_records (batch_id);

CREATE INDEX IF NOT EXISTS idx_import_batch_rollback_records_status
    ON import_batch_rollback_records (status);

CREATE INDEX IF NOT EXISTS idx_import_batch_rollback_records_created_at
    ON import_batch_rollback_records (created_at DESC);
