-- Audit trail for destructive cascade resource deletes.
-- No FK to atlas_resources (resource row is removed).

CREATE TABLE IF NOT EXISTS destructive_resource_delete_records (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    resource_id UUID NOT NULL,
    resource_code TEXT NOT NULL,
    source_atlas TEXT,
    operator TEXT NOT NULL,
    reason TEXT NOT NULL,
    confirmation_text TEXT NOT NULL,
    delete_physical_files BOOLEAN NOT NULL DEFAULT FALSE,
    dependency_counts_json JSONB,
    deleted_counts_json JSONB,
    status TEXT NOT NULL,
    error_message TEXT,
    started_at TIMESTAMPTZ,
    finished_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_destructive_resource_delete_records_resource_id
    ON destructive_resource_delete_records (resource_id);

CREATE INDEX IF NOT EXISTS idx_destructive_resource_delete_records_resource_code
    ON destructive_resource_delete_records (resource_code);
