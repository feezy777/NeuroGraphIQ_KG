-- MVP 2 Step 9.15 — Server-side composite LLM extraction workflow runs
-- Manual execution only; application does NOT auto-run this file.
--
-- Depends on: prior LLM extraction infrastructure migrations
-- Adds llm_composite_workflow_runs / llm_composite_workflow_steps only.
-- Does NOT modify mirror_*, final_*, or kg_* tables.

CREATE TABLE IF NOT EXISTS llm_composite_workflow_runs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    workflow_type TEXT NOT NULL,
    status TEXT NOT NULL,
    provider TEXT,
    model_name TEXT,
    dry_run BOOLEAN NOT NULL DEFAULT TRUE,
    resource_id UUID NULL,
    batch_id UUID NULL,
    source_atlas TEXT NULL,
    source_version TEXT NULL,
    granularity_level TEXT NULL,
    granularity_family TEXT NULL,
    candidate_ids_json JSONB NOT NULL DEFAULT '[]'::jsonb,
    candidate_count INTEGER NOT NULL DEFAULT 0,
    pair_count INTEGER NOT NULL DEFAULT 0,
    input_scope_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    request_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    result_summary_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    warnings_json JSONB NOT NULL DEFAULT '[]'::jsonb,
    errors_json JSONB NOT NULL DEFAULT '[]'::jsonb,
    started_at TIMESTAMPTZ NULL,
    completed_at TIMESTAMPTZ NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS llm_composite_workflow_steps (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    workflow_run_id UUID NOT NULL REFERENCES llm_composite_workflow_runs(id) ON DELETE CASCADE,
    step_order INTEGER NOT NULL,
    step_key TEXT NOT NULL,
    step_label TEXT,
    status TEXT NOT NULL,
    dependency_step_key TEXT NULL,
    llm_run_id UUID NULL,
    llm_item_id UUID NULL,
    request_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    response_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_counts_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    warnings_json JSONB NOT NULL DEFAULT '[]'::jsonb,
    errors_json JSONB NOT NULL DEFAULT '[]'::jsonb,
    started_at TIMESTAMPTZ NULL,
    completed_at TIMESTAMPTZ NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_llm_composite_workflow_runs_workflow_type
    ON llm_composite_workflow_runs (workflow_type);
CREATE INDEX IF NOT EXISTS idx_llm_composite_workflow_runs_status
    ON llm_composite_workflow_runs (status);
CREATE INDEX IF NOT EXISTS idx_llm_composite_workflow_runs_created_at_desc
    ON llm_composite_workflow_runs (created_at DESC);
CREATE INDEX IF NOT EXISTS idx_llm_composite_workflow_runs_batch_id
    ON llm_composite_workflow_runs (batch_id);
CREATE INDEX IF NOT EXISTS idx_llm_composite_workflow_runs_resource_id
    ON llm_composite_workflow_runs (resource_id);
CREATE INDEX IF NOT EXISTS idx_llm_composite_workflow_runs_source_atlas
    ON llm_composite_workflow_runs (source_atlas);
CREATE INDEX IF NOT EXISTS idx_llm_composite_workflow_steps_run_order
    ON llm_composite_workflow_steps (workflow_run_id, step_order);
