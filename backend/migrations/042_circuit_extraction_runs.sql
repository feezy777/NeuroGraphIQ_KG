-- 042_circuit_extraction_runs.sql
-- Circuit pack extraction run tracking.

CREATE TABLE IF NOT EXISTS circuit_extraction_runs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    provider VARCHAR(64) NOT NULL,
    model_name VARCHAR(128),
    candidate_count INT NOT NULL DEFAULT 0,
    pack_count INT NOT NULL DEFAULT 0,
    circuit_count INT NOT NULL DEFAULT 0,
    step_count INT NOT NULL DEFAULT 0,
    function_count INT NOT NULL DEFAULT 0,
    status VARCHAR(32) NOT NULL DEFAULT 'pending',
    request_json JSONB,
    result_summary_json JSONB,
    errors_json JSONB DEFAULT '[]',
    warnings_json JSONB DEFAULT '[]',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
