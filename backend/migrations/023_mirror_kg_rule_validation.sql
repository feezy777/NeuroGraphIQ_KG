-- MVP 2 Step 7 — Mirror KG Rule Validation runs and results
-- Manual execution only; application does NOT auto-run this file.
--
-- Depends on: 001_resource_registry.sql, 003_import_batches.sql, 022_mirror_kg_schema.sql
-- Deterministic rule layer (NO LLM). Reads mirror_* tables; writes validation side ONLY.
-- Does NOT write final_* / kg_*. rule_checked != human_approved != promoted.

CREATE TABLE IF NOT EXISTS mirror_rule_validation_runs (
    id                  UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    target_types        TEXT[] NOT NULL DEFAULT ARRAY[]::TEXT[],
    scope_json          JSONB NOT NULL DEFAULT '{}'::jsonb,
    resource_id         UUID NULL REFERENCES atlas_resources(id) ON DELETE SET NULL,
    batch_id            UUID NULL REFERENCES import_batches(id) ON DELETE SET NULL,
    source_atlas        TEXT NULL,
    source_version      TEXT NULL,
    granularity_level   TEXT NULL,
    granularity_family  TEXT NULL,
    status              TEXT NOT NULL DEFAULT 'created',
    object_count        INTEGER NOT NULL DEFAULT 0,
    passed_count        INTEGER NOT NULL DEFAULT 0,
    warning_count       INTEGER NOT NULL DEFAULT 0,
    failed_count        INTEGER NOT NULL DEFAULT 0,
    blocked_count       INTEGER NOT NULL DEFAULT 0,
    result_count        INTEGER NOT NULL DEFAULT 0,
    dry_run             BOOLEAN NOT NULL DEFAULT false,
    apply_status_update BOOLEAN NOT NULL DEFAULT false,
    error_message       TEXT NULL,
    started_at          TIMESTAMPTZ NULL,
    finished_at         TIMESTAMPTZ NULL,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT chk_mirror_validation_runs_status CHECK (
        status IN ('created', 'running', 'succeeded', 'partially_succeeded', 'failed', 'cancelled')
    )
);

CREATE TABLE IF NOT EXISTS mirror_rule_validation_results (
    id                  UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    run_id              UUID NOT NULL REFERENCES mirror_rule_validation_runs(id) ON DELETE CASCADE,
    target_type         TEXT NOT NULL,
    target_id           UUID NOT NULL,
    rule_code           TEXT NOT NULL,
    severity            TEXT NOT NULL,
    status              TEXT NOT NULL,
    message             TEXT NOT NULL,
    details_json        JSONB NOT NULL DEFAULT '{}'::jsonb,
    resource_id         UUID NULL REFERENCES atlas_resources(id) ON DELETE SET NULL,
    batch_id            UUID NULL REFERENCES import_batches(id) ON DELETE SET NULL,
    source_atlas        TEXT NULL,
    granularity_level   TEXT NULL,
    granularity_family  TEXT NULL,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT chk_mirror_validation_results_target_type CHECK (
        target_type IN ('connection', 'function', 'circuit', 'triple')
    ),
    CONSTRAINT chk_mirror_validation_results_severity CHECK (
        severity IN ('info', 'warning', 'error', 'blocker')
    ),
    CONSTRAINT chk_mirror_validation_results_status CHECK (
        status IN ('passed', 'warning', 'failed', 'blocked')
    )
);

CREATE INDEX IF NOT EXISTS idx_mirror_validation_runs_status
    ON mirror_rule_validation_runs (status);
CREATE INDEX IF NOT EXISTS idx_mirror_validation_runs_resource
    ON mirror_rule_validation_runs (resource_id);
CREATE INDEX IF NOT EXISTS idx_mirror_validation_runs_batch
    ON mirror_rule_validation_runs (batch_id);
CREATE INDEX IF NOT EXISTS idx_mirror_validation_runs_source_atlas
    ON mirror_rule_validation_runs (source_atlas);
CREATE INDEX IF NOT EXISTS idx_mirror_validation_results_run
    ON mirror_rule_validation_results (run_id);
CREATE INDEX IF NOT EXISTS idx_mirror_validation_results_target
    ON mirror_rule_validation_results (target_type, target_id);
CREATE INDEX IF NOT EXISTS idx_mirror_validation_results_rule_code
    ON mirror_rule_validation_results (rule_code);
CREATE INDEX IF NOT EXISTS idx_mirror_validation_results_severity
    ON mirror_rule_validation_results (severity);
CREATE INDEX IF NOT EXISTS idx_mirror_validation_results_status
    ON mirror_rule_validation_results (status);
