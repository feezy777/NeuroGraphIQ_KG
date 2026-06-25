-- LLM Extraction Infrastructure Foundation (Step 1)
-- Manual execution only; application does NOT auto-run this file.
--
-- Depends on: 001–009 (atlas_resources, import_batches, candidate_brain_regions, candidate_llm_extractions)
--
-- Adds unified run/item audit tables and optional prompt templates.
-- Does NOT write Mirror KG or final_*. Legacy candidate_llm_extractions is preserved.

CREATE TABLE IF NOT EXISTS llm_prompt_templates (
    id                  UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    template_key        TEXT NOT NULL UNIQUE,
    task_type           TEXT NOT NULL,
    version             TEXT NOT NULL DEFAULT 'v1',
    name                TEXT NOT NULL,
    description         TEXT,
    system_prompt       TEXT NOT NULL,
    user_prompt_template TEXT NOT NULL,
    output_schema_json  JSONB NOT NULL DEFAULT '{}'::jsonb,
    status              TEXT NOT NULL DEFAULT 'active',
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT chk_llm_prompt_template_status CHECK (
        status IN ('active', 'inactive', 'archived')
    )
);

CREATE TABLE IF NOT EXISTS llm_extraction_runs (
    id                          UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    task_type                   TEXT NOT NULL,
    provider                    TEXT NOT NULL,
    model_name                  TEXT NOT NULL,
    prompt_template_id          UUID REFERENCES llm_prompt_templates(id) ON DELETE SET NULL,
    prompt_template_key         TEXT,
    prompt_version              TEXT,
    scope_type                  TEXT NOT NULL DEFAULT 'unknown',
    scope_json                  JSONB NOT NULL DEFAULT '{}'::jsonb,
    resource_id                 UUID REFERENCES atlas_resources(id) ON DELETE SET NULL,
    batch_id                    UUID REFERENCES import_batches(id) ON DELETE SET NULL,
    granularity_level           TEXT,
    granularity_family          TEXT,
    source_atlas                TEXT,
    source_version              TEXT,
    status                      TEXT NOT NULL DEFAULT 'created',
    input_count                 INTEGER NOT NULL DEFAULT 0,
    output_count                INTEGER NOT NULL DEFAULT 0,
    error_count                 INTEGER NOT NULL DEFAULT 0,
    temperature                 NUMERIC,
    max_tokens                  INTEGER,
    request_payload_redacted    JSONB NOT NULL DEFAULT '{}'::jsonb,
    usage_json                  JSONB NOT NULL DEFAULT '{}'::jsonb,
    error_message               TEXT,
    started_at                  TIMESTAMPTZ,
    finished_at                 TIMESTAMPTZ,
    created_at                  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT chk_llm_extraction_run_status CHECK (
        status IN ('created', 'running', 'succeeded', 'partially_succeeded', 'failed', 'cancelled')
    ),
    CONSTRAINT chk_llm_extraction_run_scope_type CHECK (
        scope_type IN ('single_candidate', 'candidate_batch', 'resource', 'manual_selection', 'unknown')
    )
);

CREATE TABLE IF NOT EXISTS llm_extraction_items (
    id                      UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    run_id                  UUID NOT NULL REFERENCES llm_extraction_runs(id) ON DELETE CASCADE,
    candidate_id            UUID REFERENCES candidate_brain_regions(id) ON DELETE SET NULL,
    resource_id             UUID REFERENCES atlas_resources(id) ON DELETE SET NULL,
    batch_id                UUID REFERENCES import_batches(id) ON DELETE SET NULL,
    task_type               TEXT NOT NULL,
    item_index              INTEGER NOT NULL DEFAULT 0,
    input_json              JSONB NOT NULL DEFAULT '{}'::jsonb,
    prompt_json             JSONB NOT NULL DEFAULT '{}'::jsonb,
    raw_response_text       TEXT,
    parsed_response_json    JSONB NOT NULL DEFAULT '{}'::jsonb,
    normalized_output_json  JSONB NOT NULL DEFAULT '{}'::jsonb,
    status                  TEXT NOT NULL DEFAULT 'created',
    confidence              NUMERIC,
    evidence_text           TEXT,
    uncertainty_reason      TEXT,
    error_message           TEXT,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT chk_llm_extraction_item_status CHECK (
        status IN ('created', 'running', 'succeeded', 'failed', 'skipped', 'needs_review')
    )
);

CREATE INDEX IF NOT EXISTS idx_llm_runs_task_type ON llm_extraction_runs (task_type);
CREATE INDEX IF NOT EXISTS idx_llm_runs_provider ON llm_extraction_runs (provider);
CREATE INDEX IF NOT EXISTS idx_llm_runs_status ON llm_extraction_runs (status);
CREATE INDEX IF NOT EXISTS idx_llm_runs_resource ON llm_extraction_runs (resource_id);
CREATE INDEX IF NOT EXISTS idx_llm_runs_batch ON llm_extraction_runs (batch_id);
CREATE INDEX IF NOT EXISTS idx_llm_items_run ON llm_extraction_items (run_id);
CREATE INDEX IF NOT EXISTS idx_llm_items_candidate ON llm_extraction_items (candidate_id);
CREATE INDEX IF NOT EXISTS idx_llm_items_status ON llm_extraction_items (status);
CREATE INDEX IF NOT EXISTS idx_llm_items_task_type ON llm_extraction_items (task_type);
