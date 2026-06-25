-- MVP 2 Step 1 LLM Extraction (DeepSeek candidate-side) — candidate_llm_extractions
-- Manual execution only; application does NOT auto-run this file.
--
-- Depends on:
--   001_resource_registry.sql, 002_resource_files.sql, 003_import_batches.sql,
--   004_raw_parsing_aal3.sql, 005_candidate_db.sql, 006_rule_validation.sql,
--   007_human_review.sql, 008_promotion.sql
--
-- CANDIDATE SIDE ONLY. DeepSeek output is an ADVISORY suggestion, never a fact.
-- This table NEVER writes final_* / kg_* / staging_*, NEVER approves, NEVER promotes,
-- and does NOT mutate candidate_brain_regions.candidate_status (extraction is decoupled
-- from the Candidate state machine in this step). Full lineage is preserved via the
-- *_id columns so every suggestion traces back to its candidate / batch / parse origin.

CREATE TABLE IF NOT EXISTS candidate_llm_extractions (
    id                  UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    candidate_id        UUID NOT NULL REFERENCES candidate_brain_regions(id) ON DELETE RESTRICT,
    batch_id            UUID NOT NULL REFERENCES import_batches(id) ON DELETE RESTRICT,
    resource_id         UUID NOT NULL REFERENCES atlas_resources(id) ON DELETE RESTRICT,
    generation_run_id   UUID NOT NULL REFERENCES candidate_generation_runs(id) ON DELETE RESTRICT,
    parse_run_id        UUID NOT NULL REFERENCES raw_parse_runs(id) ON DELETE RESTRICT,
    -- run_id groups all extractions triggered together (single call or a <=20 batch).
    run_id              UUID NOT NULL,
    provider            VARCHAR(32) NOT NULL DEFAULT 'deepseek',
    model               VARCHAR(128) NOT NULL,
    prompt_version      VARCHAR(32) NOT NULL,
    status              VARCHAR(32) NOT NULL DEFAULT 'pending',
    -- Verbatim model output (untrimmed) for audit; null until a response/error arrives.
    raw_response        TEXT,
    -- Parsed advisory fields (suggested_cn_name, suggested_laterality, confidence, ...).
    structured_result   JSONB,
    error_message       TEXT,
    prompt_tokens       INTEGER,
    completion_tokens   INTEGER,
    total_tokens        INTEGER,
    latency_ms          INTEGER,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT chk_llm_extraction_status CHECK (
        status IN ('pending', 'succeeded', 'failed')
    )
);

CREATE INDEX IF NOT EXISTS idx_llm_extraction_candidate ON candidate_llm_extractions (candidate_id);
CREATE INDEX IF NOT EXISTS idx_llm_extraction_batch ON candidate_llm_extractions (batch_id);
CREATE INDEX IF NOT EXISTS idx_llm_extraction_resource ON candidate_llm_extractions (resource_id);
CREATE INDEX IF NOT EXISTS idx_llm_extraction_run ON candidate_llm_extractions (run_id);
CREATE INDEX IF NOT EXISTS idx_llm_extraction_status ON candidate_llm_extractions (status);
CREATE INDEX IF NOT EXISTS idx_llm_extraction_created ON candidate_llm_extractions (created_at);
