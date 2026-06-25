-- MVP 1 Rule Validation — rule_validation_runs, candidate_rule_validation_results
-- Manual execution only; application does NOT auto-run this file.
--
-- Depends on:
--   001_resource_registry.sql, 002_resource_files.sql, 003_import_batches.sql,
--   004_raw_parsing_aal3.sql, 005_candidate_db.sql
-- Deterministic rule layer (NO LLM). Reads candidate_brain_regions; writes validation
-- side ONLY. Does NOT write final_* / kg_*. rule_passed != manual_approved != promoted.

-- Extend import_batch_events event_type for rule validation lifecycle.
ALTER TABLE import_batch_events DROP CONSTRAINT IF EXISTS chk_import_batch_events_type;
ALTER TABLE import_batch_events ADD CONSTRAINT chk_import_batch_events_type CHECK (
    event_type IN (
        'created',
        'file_attached',
        'status_changed',
        'cancelled',
        'failed',
        'completed',
        'note',
        'parse_started',
        'parse_succeeded',
        'parse_failed',
        'candidate_generation_started',
        'candidate_generation_succeeded',
        'candidate_generation_failed',
        'rule_validation_started',
        'rule_validation_succeeded',
        'rule_validation_failed'
    )
);

CREATE TABLE IF NOT EXISTS rule_validation_runs (
    id                  UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    scope               VARCHAR(32) NOT NULL,
    batch_id            UUID NOT NULL REFERENCES import_batches(id) ON DELETE RESTRICT,
    resource_id         UUID NOT NULL REFERENCES atlas_resources(id) ON DELETE RESTRICT,
    generation_run_id   UUID REFERENCES candidate_generation_runs(id) ON DELETE RESTRICT,
    parse_run_id        UUID REFERENCES raw_parse_runs(id) ON DELETE RESTRICT,
    target_candidate_id UUID REFERENCES candidate_brain_regions(id) ON DELETE RESTRICT,
    validator_key       VARCHAR(128) NOT NULL DEFAULT 'aal3_candidate_rules',
    validator_version   VARCHAR(64) NOT NULL DEFAULT 'v1',
    status              VARCHAR(32) NOT NULL DEFAULT 'created',
    candidate_count     INTEGER NOT NULL DEFAULT 0,
    passed_count        INTEGER NOT NULL DEFAULT 0,
    failed_count        INTEGER NOT NULL DEFAULT 0,
    warning_count       INTEGER NOT NULL DEFAULT 0,
    skipped_count       INTEGER NOT NULL DEFAULT 0,
    error_message       TEXT,
    started_at          TIMESTAMPTZ,
    finished_at         TIMESTAMPTZ,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT chk_rule_validation_runs_scope CHECK (
        scope IN ('candidate', 'generation_run', 'batch', 'parse_run')
    ),
    CONSTRAINT chk_rule_validation_runs_status CHECK (
        status IN ('created', 'running', 'succeeded', 'failed')
    )
);

CREATE TABLE IF NOT EXISTS candidate_rule_validation_results (
    id                  UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    validation_run_id   UUID NOT NULL REFERENCES rule_validation_runs(id) ON DELETE RESTRICT,
    candidate_id        UUID NOT NULL REFERENCES candidate_brain_regions(id) ON DELETE RESTRICT,
    batch_id            UUID NOT NULL REFERENCES import_batches(id) ON DELETE RESTRICT,
    resource_id         UUID NOT NULL REFERENCES atlas_resources(id) ON DELETE RESTRICT,
    generation_run_id   UUID NOT NULL REFERENCES candidate_generation_runs(id) ON DELETE RESTRICT,
    parse_run_id        UUID NOT NULL REFERENCES raw_parse_runs(id) ON DELETE RESTRICT,
    overall_status      VARCHAR(32) NOT NULL,
    error_count         INTEGER NOT NULL DEFAULT 0,
    warning_count       INTEGER NOT NULL DEFAULT 0,
    info_count          INTEGER NOT NULL DEFAULT 0,
    checks              JSONB NOT NULL DEFAULT '[]',
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT chk_candidate_rule_result_status CHECK (
        overall_status IN ('passed', 'failed')
    )
);

-- One result row per candidate per validation run.
CREATE UNIQUE INDEX IF NOT EXISTS uq_candidate_rule_result_run_candidate
    ON candidate_rule_validation_results (validation_run_id, candidate_id);

CREATE INDEX IF NOT EXISTS idx_rule_validation_runs_batch ON rule_validation_runs (batch_id);
CREATE INDEX IF NOT EXISTS idx_rule_validation_runs_resource ON rule_validation_runs (resource_id);
CREATE INDEX IF NOT EXISTS idx_rule_validation_runs_gen_run ON rule_validation_runs (generation_run_id);
CREATE INDEX IF NOT EXISTS idx_rule_validation_runs_parse_run ON rule_validation_runs (parse_run_id);
CREATE INDEX IF NOT EXISTS idx_rule_validation_runs_status ON rule_validation_runs (status);

CREATE INDEX IF NOT EXISTS idx_candidate_rule_result_run ON candidate_rule_validation_results (validation_run_id);
CREATE INDEX IF NOT EXISTS idx_candidate_rule_result_candidate ON candidate_rule_validation_results (candidate_id);
CREATE INDEX IF NOT EXISTS idx_candidate_rule_result_batch ON candidate_rule_validation_results (batch_id);
CREATE INDEX IF NOT EXISTS idx_candidate_rule_result_status ON candidate_rule_validation_results (overall_status);

DROP TRIGGER IF EXISTS trg_rule_validation_runs_updated_at ON rule_validation_runs;
CREATE TRIGGER trg_rule_validation_runs_updated_at
    BEFORE UPDATE ON rule_validation_runs
    FOR EACH ROW EXECUTE FUNCTION update_updated_at();
