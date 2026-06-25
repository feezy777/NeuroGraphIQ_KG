-- Mirror Circuit-Projection Cross Validation (Step 8.11)
-- Manual execution only; application does NOT auto-run this file.
--
-- Depends on: 026 (mirror_circuit_projection_memberships, mirror_region_circuits, mirror_region_connections)
--
-- Deterministic cross validation between circuit_to_projection and projection_to_circuit memberships.
-- Does NOT write final_* or kg_*; does NOT call LLM.

CREATE TABLE IF NOT EXISTS mirror_circuit_projection_cross_validation_runs (
    id                              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    scope_json                      JSONB NOT NULL DEFAULT '{}'::jsonb,
    resource_id                     UUID REFERENCES atlas_resources(id) ON DELETE SET NULL,
    batch_id                        UUID REFERENCES import_batches(id) ON DELETE SET NULL,
    source_atlas                    TEXT,
    source_version                  TEXT,
    granularity_level               TEXT,
    granularity_family              TEXT,
    status                          TEXT NOT NULL DEFAULT 'created',
    membership_count                INTEGER NOT NULL DEFAULT 0,
    circuit_supported_count         INTEGER NOT NULL DEFAULT 0,
    projection_supported_count      INTEGER NOT NULL DEFAULT 0,
    bidirectionally_supported_count INTEGER NOT NULL DEFAULT 0,
    conflict_count                  INTEGER NOT NULL DEFAULT 0,
    insufficient_evidence_count     INTEGER NOT NULL DEFAULT 0,
    updated_membership_count        INTEGER NOT NULL DEFAULT 0,
    dry_run                         BOOLEAN NOT NULL DEFAULT false,
    apply_updates                   BOOLEAN NOT NULL DEFAULT false,
    error_message                   TEXT,
    started_at                      TIMESTAMPTZ,
    finished_at                     TIMESTAMPTZ,
    created_at                      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT chk_mirror_cp_cross_run_status CHECK (
        status IN (
            'created', 'running', 'succeeded', 'partially_succeeded', 'failed', 'cancelled'
        )
    )
);

CREATE INDEX IF NOT EXISTS idx_mirror_cp_cross_runs_status
    ON mirror_circuit_projection_cross_validation_runs (status);
CREATE INDEX IF NOT EXISTS idx_mirror_cp_cross_runs_resource
    ON mirror_circuit_projection_cross_validation_runs (resource_id);
CREATE INDEX IF NOT EXISTS idx_mirror_cp_cross_runs_batch
    ON mirror_circuit_projection_cross_validation_runs (batch_id);
CREATE INDEX IF NOT EXISTS idx_mirror_cp_cross_runs_atlas_granularity
    ON mirror_circuit_projection_cross_validation_runs (source_atlas, granularity_level);
CREATE INDEX IF NOT EXISTS idx_mirror_cp_cross_runs_created
    ON mirror_circuit_projection_cross_validation_runs (created_at DESC);

CREATE TABLE IF NOT EXISTS mirror_circuit_projection_cross_validation_results (
    id                                  UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    run_id                              UUID NOT NULL REFERENCES mirror_circuit_projection_cross_validation_runs(id) ON DELETE CASCADE,
    circuit_id                          UUID NOT NULL REFERENCES mirror_region_circuits(id) ON DELETE CASCADE,
    projection_id                       UUID NOT NULL REFERENCES mirror_region_connections(id) ON DELETE CASCADE,
    circuit_to_projection_membership_id UUID REFERENCES mirror_circuit_projection_memberships(id) ON DELETE SET NULL,
    projection_to_circuit_membership_id UUID REFERENCES mirror_circuit_projection_memberships(id) ON DELETE SET NULL,
    validation_status                   TEXT NOT NULL,
    support_level                       TEXT NOT NULL DEFAULT 'unknown',
    agreement_score                     NUMERIC,
    source_step_agreement               BOOLEAN,
    target_step_agreement               BOOLEAN,
    direction_agreement                 BOOLEAN,
    scope_agreement                     BOOLEAN,
    conflict_reason                     TEXT,
    details_json                        JSONB NOT NULL DEFAULT '{}'::jsonb,
    resource_id                         UUID REFERENCES atlas_resources(id) ON DELETE SET NULL,
    batch_id                            UUID REFERENCES import_batches(id) ON DELETE SET NULL,
    source_atlas                        TEXT,
    granularity_level                   TEXT,
    granularity_family                  TEXT,
    created_at                          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT chk_mirror_cp_cross_result_validation_status CHECK (
        validation_status IN (
            'bidirectionally_supported',
            'circuit_supported_only',
            'projection_supported_only',
            'conflict',
            'insufficient_evidence',
            'unknown'
        )
    ),
    CONSTRAINT chk_mirror_cp_cross_result_support_level CHECK (
        support_level IN ('strong', 'moderate', 'weak', 'conflicting', 'unknown')
    )
);

CREATE INDEX IF NOT EXISTS idx_mirror_cp_cross_results_run
    ON mirror_circuit_projection_cross_validation_results (run_id);
CREATE INDEX IF NOT EXISTS idx_mirror_cp_cross_results_circuit
    ON mirror_circuit_projection_cross_validation_results (circuit_id);
CREATE INDEX IF NOT EXISTS idx_mirror_cp_cross_results_projection
    ON mirror_circuit_projection_cross_validation_results (projection_id);
CREATE INDEX IF NOT EXISTS idx_mirror_cp_cross_results_forward_membership
    ON mirror_circuit_projection_cross_validation_results (circuit_to_projection_membership_id);
CREATE INDEX IF NOT EXISTS idx_mirror_cp_cross_results_reverse_membership
    ON mirror_circuit_projection_cross_validation_results (projection_to_circuit_membership_id);
CREATE INDEX IF NOT EXISTS idx_mirror_cp_cross_results_status
    ON mirror_circuit_projection_cross_validation_results (validation_status);
CREATE INDEX IF NOT EXISTS idx_mirror_cp_cross_results_resource
    ON mirror_circuit_projection_cross_validation_results (resource_id);
CREATE INDEX IF NOT EXISTS idx_mirror_cp_cross_results_batch
    ON mirror_circuit_projection_cross_validation_results (batch_id);
CREATE INDEX IF NOT EXISTS idx_mirror_cp_cross_results_atlas_granularity
    ON mirror_circuit_projection_cross_validation_results (source_atlas, granularity_level);
