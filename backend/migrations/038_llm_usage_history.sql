-- 038: LLM usage history for Dry Run cost estimation calibration
-- Each row = one pack-level LLM call with real provider usage data.
-- Written after a composite workflow completes (non-dry-run only).

CREATE TABLE IF NOT EXISTS llm_usage_history (
    id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    workflow_run_id   UUID NOT NULL,
    workflow_type     VARCHAR(64) NOT NULL,
    stage_name        VARCHAR(64) NOT NULL,
    provider          VARCHAR(32) NOT NULL,
    model             VARCHAR(128) NOT NULL,
    pair_count        INTEGER NOT NULL DEFAULT 0,
    pack_index        INTEGER NOT NULL DEFAULT 0,
    prompt_tokens     INTEGER NOT NULL DEFAULT 0,
    completion_tokens INTEGER NOT NULL DEFAULT 0,
    reasoning_tokens  INTEGER,
    total_tokens      INTEGER NOT NULL DEFAULT 0,
    retry_count       INTEGER NOT NULL DEFAULT 0,
    actual_cost       DOUBLE PRECISION,
    pricing_version   VARCHAR(32),
    created_at        TIMESTAMP WITH TIME ZONE DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_usage_history_agg
    ON llm_usage_history (workflow_type, stage_name, provider, model);

COMMENT ON TABLE llm_usage_history IS
    'Per-pack LLM usage records written after composite workflow completion. Used by Dry Run to estimate output tokens from real historical data.';

COMMENT ON COLUMN llm_usage_history.stage_name IS
    'Stage key from workflow step definitions, e.g. extract_connections, extract_projection_functions';
