-- Circuit → Connection LLM extraction audit tables

CREATE TABLE IF NOT EXISTS llm_circuit_connection_extraction_runs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    provider VARCHAR(32) NOT NULL DEFAULT 'deepseek',
    model_name VARCHAR(128),
    mode VARCHAR(32) NOT NULL,  -- 'multi_connection' | 'main_pair'
    circuit_count INTEGER NOT NULL DEFAULT 0,
    dry_run BOOLEAN NOT NULL DEFAULT TRUE,
    create_mirror_updates BOOLEAN NOT NULL DEFAULT TRUE,
    overwrite_policy VARCHAR(64) NOT NULL DEFAULT 'fill_missing_only',
    status VARCHAR(32) NOT NULL DEFAULT 'pending',
    request_json JSONB NOT NULL DEFAULT '{}',
    summary_json JSONB NOT NULL DEFAULT '{}',
    warnings_json JSONB NOT NULL DEFAULT '[]',
    errors_json JSONB NOT NULL DEFAULT '[]',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS llm_circuit_connection_extraction_items (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    run_id UUID NOT NULL REFERENCES llm_circuit_connection_extraction_runs(id) ON DELETE CASCADE,
    circuit_id UUID REFERENCES mirror_region_circuits(id) ON DELETE SET NULL,
    source_region_name VARCHAR(256),
    target_region_name VARCHAR(256),
    source_candidate_id UUID REFERENCES candidate_brain_regions(id) ON DELETE SET NULL,
    target_candidate_id UUID REFERENCES candidate_brain_regions(id) ON DELETE SET NULL,
    connection_type VARCHAR(64),
    confidence NUMERIC,
    evidence_text TEXT,
    connection_id UUID REFERENCES mirror_region_connections(id) ON DELETE SET NULL,
    action VARCHAR(32) NOT NULL,  -- 'created' | 'updated' | 'skipped' | 'no_match'
    action_reason TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_cce_items_run_id ON llm_circuit_connection_extraction_items(run_id);
CREATE INDEX IF NOT EXISTS idx_cce_items_circuit_id ON llm_circuit_connection_extraction_items(circuit_id);
