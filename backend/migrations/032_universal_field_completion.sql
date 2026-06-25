-- Step 10.3 — Universal Field Completion audit tables
-- Manual execution only; application does NOT auto-run this file.
--
-- Adds llm_field_completion_runs / llm_field_completion_items only.
-- Does NOT modify mirror_*, final_*, kg_*, or candidate tables.

CREATE TABLE IF NOT EXISTS llm_field_completion_runs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    provider TEXT NOT NULL DEFAULT 'deepseek',
    model_name TEXT NULL,
    target_type TEXT NOT NULL,
    target_count INTEGER NOT NULL DEFAULT 0,
    field_scope TEXT NOT NULL DEFAULT 'missing_only',
    selected_fields_json JSONB NOT NULL DEFAULT '[]'::jsonb,
    overwrite_policy TEXT NOT NULL DEFAULT 'fill_missing_only',
    dry_run BOOLEAN NOT NULL DEFAULT TRUE,
    create_mirror_updates BOOLEAN NOT NULL DEFAULT TRUE,
    create_evidence BOOLEAN NOT NULL DEFAULT FALSE,
    status TEXT NOT NULL DEFAULT 'pending',
    request_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    summary_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    warnings_json JSONB NOT NULL DEFAULT '[]'::jsonb,
    errors_json JSONB NOT NULL DEFAULT '[]'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    started_at TIMESTAMPTZ NULL,
    completed_at TIMESTAMPTZ NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS llm_field_completion_items (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    run_id UUID NOT NULL REFERENCES llm_field_completion_runs(id) ON DELETE CASCADE,
    target_type TEXT NOT NULL,
    target_id UUID NOT NULL,
    field_name TEXT NOT NULL,
    old_value_json JSONB NULL,
    suggested_value_json JSONB NULL,
    applied_value_json JSONB NULL,
    confidence DOUBLE PRECISION NULL,
    evidence_text TEXT NULL,
    reasoning_summary TEXT NULL,
    uncertainty_reason TEXT NULL,
    update_status TEXT NOT NULL DEFAULT 'suggested',
    error_message TEXT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_llm_field_completion_runs_target_type
    ON llm_field_completion_runs (target_type);
CREATE INDEX IF NOT EXISTS idx_llm_field_completion_runs_status
    ON llm_field_completion_runs (status);
CREATE INDEX IF NOT EXISTS idx_llm_field_completion_runs_created_at_desc
    ON llm_field_completion_runs (created_at DESC);
CREATE INDEX IF NOT EXISTS idx_llm_field_completion_items_run_id
    ON llm_field_completion_items (run_id);
CREATE INDEX IF NOT EXISTS idx_llm_field_completion_items_target
    ON llm_field_completion_items (target_type, target_id);
CREATE INDEX IF NOT EXISTS idx_llm_field_completion_items_field_name
    ON llm_field_completion_items (field_name);
CREATE INDEX IF NOT EXISTS idx_llm_field_completion_items_update_status
    ON llm_field_completion_items (update_status);
