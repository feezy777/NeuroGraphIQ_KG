-- Unified intermediate JSON for file-center preview / LLM validation
ALTER TABLE file_registry
    ADD COLUMN IF NOT EXISTS intermediate_json JSONB,
    ADD COLUMN IF NOT EXISTS intermediate_status VARCHAR(20) DEFAULT 'pending',
    ADD COLUMN IF NOT EXISTS intermediate_error TEXT,
    ADD COLUMN IF NOT EXISTS intermediate_parsed_at TIMESTAMPTZ;

CREATE INDEX IF NOT EXISTS idx_file_registry_intermediate_status
    ON file_registry (intermediate_status);
