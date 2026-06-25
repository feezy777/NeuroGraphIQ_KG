-- Mirror Macro Clinical Alignment Schema Foundation (Step 8.6)
-- Manual execution only; application does NOT auto-run this file.
--
-- Depends on: 022 (mirror_region_circuits, mirror_region_connections), 021 (llm_extraction_*)
--
-- Adds circuit_step, projection_function, circuit_projection_membership, dual_model_verification.
-- mirror_region_connections retains table name; macro_clinical semantic = projection.
-- Does NOT write final_* or kg_*.

CREATE TABLE IF NOT EXISTS mirror_circuit_steps (
    id                      UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    circuit_id              UUID NOT NULL REFERENCES mirror_region_circuits(id) ON DELETE CASCADE,
    region_candidate_id     UUID REFERENCES candidate_brain_regions(id) ON DELETE SET NULL,
    region_final_id         UUID,
    resource_id             UUID REFERENCES atlas_resources(id) ON DELETE SET NULL,
    batch_id                UUID REFERENCES import_batches(id) ON DELETE SET NULL,
    llm_run_id              UUID REFERENCES llm_extraction_runs(id) ON DELETE SET NULL,
    llm_item_id             UUID REFERENCES llm_extraction_items(id) ON DELETE SET NULL,
    granularity_level       TEXT NOT NULL,
    granularity_family      TEXT,
    source_atlas            TEXT NOT NULL,
    source_version          TEXT,
    step_order              INTEGER NOT NULL,
    step_name               TEXT NOT NULL,
    step_type               TEXT NOT NULL DEFAULT 'unknown',
    role                    TEXT NOT NULL DEFAULT 'unknown',
    description             TEXT,
    confidence              NUMERIC,
    evidence_text           TEXT,
    uncertainty_reason      TEXT,
    mirror_status           TEXT NOT NULL DEFAULT 'llm_suggested',
    review_status           TEXT NOT NULL DEFAULT 'pending',
    promotion_status        TEXT NOT NULL DEFAULT 'not_promoted',
    raw_payload_json        JSONB NOT NULL DEFAULT '{}'::jsonb,
    normalized_payload_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_by              TEXT,
    updated_by              TEXT,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT chk_mirror_circuit_step_order CHECK (step_order >= 0),
    CONSTRAINT chk_mirror_circuit_step_type CHECK (
        step_type IN (
            'region', 'region_group', 'relay', 'hub', 'modulator',
            'functional_stage', 'unknown'
        )
    ),
    CONSTRAINT chk_mirror_circuit_step_role CHECK (
        role IN (
            'source', 'target', 'relay', 'hub', 'modulator', 'participant', 'unknown'
        )
    ),
    CONSTRAINT chk_mirror_circuit_step_mirror_status CHECK (
        mirror_status IN (
            'llm_suggested', 'rule_checked', 'human_review_pending', 'human_approved',
            'human_rejected', 'promoted_to_final', 'superseded'
        )
    ),
    CONSTRAINT chk_mirror_circuit_step_review_status CHECK (
        review_status IN ('pending', 'approved', 'rejected', 'needs_revision', 'not_required')
    ),
    CONSTRAINT chk_mirror_circuit_step_promotion_status CHECK (
        promotion_status IN ('not_promoted', 'promoted', 'failed', 'blocked')
    ),
    CONSTRAINT uq_mirror_circuit_steps_circuit_order UNIQUE (circuit_id, step_order)
);

CREATE TABLE IF NOT EXISTS mirror_projection_functions (
    id                      UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    projection_id           UUID NOT NULL REFERENCES mirror_region_connections(id) ON DELETE CASCADE,
    resource_id             UUID REFERENCES atlas_resources(id) ON DELETE SET NULL,
    batch_id                UUID REFERENCES import_batches(id) ON DELETE SET NULL,
    llm_run_id              UUID REFERENCES llm_extraction_runs(id) ON DELETE SET NULL,
    llm_item_id             UUID REFERENCES llm_extraction_items(id) ON DELETE SET NULL,
    granularity_level       TEXT NOT NULL,
    granularity_family      TEXT,
    source_atlas            TEXT NOT NULL,
    source_version          TEXT,
    function_term           TEXT NOT NULL,
    function_category       TEXT NOT NULL DEFAULT 'unknown',
    relation_type           TEXT NOT NULL DEFAULT 'associated_with',
    confidence              NUMERIC,
    evidence_text           TEXT,
    uncertainty_reason      TEXT,
    mirror_status           TEXT NOT NULL DEFAULT 'llm_suggested',
    review_status           TEXT NOT NULL DEFAULT 'pending',
    promotion_status        TEXT NOT NULL DEFAULT 'not_promoted',
    raw_payload_json        JSONB NOT NULL DEFAULT '{}'::jsonb,
    normalized_payload_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_by              TEXT,
    updated_by              TEXT,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT chk_mirror_projection_function_category CHECK (
        function_category IN (
            'motor', 'sensory', 'visual', 'auditory', 'language', 'memory', 'emotion',
            'executive_control', 'attention', 'autonomic', 'default_mode', 'salience',
            'reward', 'cognitive', 'unknown'
        )
    ),
    CONSTRAINT chk_mirror_projection_function_relation_type CHECK (
        relation_type IN (
            'involved_in', 'associated_with', 'necessary_for', 'modulates',
            'participates_in', 'uncertain_association', 'unknown'
        )
    ),
    CONSTRAINT chk_mirror_projection_function_mirror_status CHECK (
        mirror_status IN (
            'llm_suggested', 'rule_checked', 'human_review_pending', 'human_approved',
            'human_rejected', 'promoted_to_final', 'superseded'
        )
    ),
    CONSTRAINT chk_mirror_projection_function_review_status CHECK (
        review_status IN ('pending', 'approved', 'rejected', 'needs_revision', 'not_required')
    ),
    CONSTRAINT chk_mirror_projection_function_promotion_status CHECK (
        promotion_status IN ('not_promoted', 'promoted', 'failed', 'blocked')
    )
);

CREATE TABLE IF NOT EXISTS mirror_circuit_projection_memberships (
    id                      UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    circuit_id              UUID NOT NULL REFERENCES mirror_region_circuits(id) ON DELETE CASCADE,
    projection_id           UUID NOT NULL REFERENCES mirror_region_connections(id) ON DELETE CASCADE,
    source_step_id          UUID REFERENCES mirror_circuit_steps(id) ON DELETE SET NULL,
    target_step_id          UUID REFERENCES mirror_circuit_steps(id) ON DELETE SET NULL,
    resource_id             UUID REFERENCES atlas_resources(id) ON DELETE SET NULL,
    batch_id                UUID REFERENCES import_batches(id) ON DELETE SET NULL,
    llm_run_id              UUID REFERENCES llm_extraction_runs(id) ON DELETE SET NULL,
    llm_item_id             UUID REFERENCES llm_extraction_items(id) ON DELETE SET NULL,
    granularity_level       TEXT NOT NULL,
    granularity_family      TEXT,
    source_atlas            TEXT NOT NULL,
    source_version          TEXT,
    step_order              INTEGER,
    role_in_circuit         TEXT NOT NULL DEFAULT 'unknown',
    source_method           TEXT NOT NULL DEFAULT 'unknown',
    verification_status     TEXT NOT NULL DEFAULT 'unverified',
    confidence              NUMERIC,
    evidence_text           TEXT,
    uncertainty_reason      TEXT,
    mirror_status           TEXT NOT NULL DEFAULT 'llm_suggested',
    review_status           TEXT NOT NULL DEFAULT 'pending',
    promotion_status        TEXT NOT NULL DEFAULT 'not_promoted',
    raw_payload_json        JSONB NOT NULL DEFAULT '{}'::jsonb,
    normalized_payload_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_by              TEXT,
    updated_by              TEXT,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT chk_mirror_membership_role_in_circuit CHECK (
        role_in_circuit IN (
            'main_path', 'feedback', 'feedforward', 'modulatory', 'relay',
            'parallel_branch', 'unknown'
        )
    ),
    CONSTRAINT chk_mirror_membership_source_method CHECK (
        source_method IN (
            'circuit_to_projection', 'projection_to_circuit', 'dual_model_consensus',
            'human_curated', 'deterministic', 'unknown'
        )
    ),
    CONSTRAINT chk_mirror_membership_verification_status CHECK (
        verification_status IN (
            'unverified', 'circuit_supported', 'projection_supported',
            'bidirectionally_supported', 'model_conflict', 'human_approved',
            'human_rejected', 'unknown'
        )
    ),
    CONSTRAINT chk_mirror_membership_mirror_status CHECK (
        mirror_status IN (
            'llm_suggested', 'rule_checked', 'human_review_pending', 'human_approved',
            'human_rejected', 'promoted_to_final', 'superseded'
        )
    ),
    CONSTRAINT chk_mirror_membership_review_status CHECK (
        review_status IN ('pending', 'approved', 'rejected', 'needs_revision', 'not_required')
    ),
    CONSTRAINT chk_mirror_membership_promotion_status CHECK (
        promotion_status IN ('not_promoted', 'promoted', 'failed', 'blocked')
    ),
    CONSTRAINT uq_mirror_circuit_projection_membership UNIQUE (
        circuit_id, projection_id, source_step_id, target_step_id
    )
);

CREATE TABLE IF NOT EXISTS mirror_dual_model_verification_runs (
    id                              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    verification_task_type          TEXT NOT NULL,
    model_a_provider                TEXT NOT NULL DEFAULT 'deepseek',
    model_a_name                    TEXT,
    model_a_run_id                  UUID REFERENCES llm_extraction_runs(id) ON DELETE SET NULL,
    model_b_provider                TEXT NOT NULL DEFAULT 'kimi',
    model_b_name                    TEXT,
    model_b_run_id                  UUID REFERENCES llm_extraction_runs(id) ON DELETE SET NULL,
    scope_json                      JSONB NOT NULL DEFAULT '{}'::jsonb,
    resource_id                     UUID REFERENCES atlas_resources(id) ON DELETE SET NULL,
    batch_id                        UUID REFERENCES import_batches(id) ON DELETE SET NULL,
    source_atlas                    TEXT,
    source_version                  TEXT,
    granularity_level               TEXT,
    granularity_family              TEXT,
    status                          TEXT NOT NULL DEFAULT 'created',
    object_count                    INTEGER NOT NULL DEFAULT 0,
    consensus_supported_count       INTEGER NOT NULL DEFAULT 0,
    consensus_rejected_count        INTEGER NOT NULL DEFAULT 0,
    model_conflict_count            INTEGER NOT NULL DEFAULT 0,
    insufficient_information_count  INTEGER NOT NULL DEFAULT 0,
    needs_human_review_count        INTEGER NOT NULL DEFAULT 0,
    dry_run                         BOOLEAN NOT NULL DEFAULT false,
    error_message                   TEXT,
    started_at                      TIMESTAMPTZ,
    finished_at                     TIMESTAMPTZ,
    created_at                      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT chk_mirror_dual_model_run_task_type CHECK (
        verification_task_type IN (
            'circuit_projection_membership', 'projection_function', 'circuit_step',
            'circuit', 'projection', 'triple', 'unknown'
        )
    ),
    CONSTRAINT chk_mirror_dual_model_run_status CHECK (
        status IN (
            'created', 'running', 'succeeded', 'partially_succeeded', 'failed', 'cancelled'
        )
    )
);

CREATE TABLE IF NOT EXISTS mirror_dual_model_verification_results (
    id                          UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    run_id                      UUID NOT NULL REFERENCES mirror_dual_model_verification_runs(id) ON DELETE CASCADE,
    object_type                 TEXT NOT NULL,
    object_id                   UUID NOT NULL,
    model_a_provider            TEXT NOT NULL,
    model_a_decision            TEXT NOT NULL,
    model_a_confidence          NUMERIC,
    model_a_payload_json        JSONB NOT NULL DEFAULT '{}'::jsonb,
    model_b_provider            TEXT NOT NULL,
    model_b_decision            TEXT NOT NULL,
    model_b_confidence          NUMERIC,
    model_b_payload_json        JSONB NOT NULL DEFAULT '{}'::jsonb,
    consensus_status            TEXT NOT NULL,
    consensus_score             NUMERIC,
    conflict_summary            TEXT,
    recommended_review_priority   TEXT NOT NULL DEFAULT 'normal',
    evidence_text               TEXT,
    uncertainty_reason          TEXT,
    resource_id                 UUID REFERENCES atlas_resources(id) ON DELETE SET NULL,
    batch_id                    UUID REFERENCES import_batches(id) ON DELETE SET NULL,
    source_atlas                TEXT,
    granularity_level           TEXT,
    granularity_family          TEXT,
    created_at                  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT chk_mirror_dual_model_result_object_type CHECK (
        object_type IN (
            'circuit_projection_membership', 'projection_function', 'circuit_step',
            'circuit', 'projection', 'triple', 'unknown'
        )
    ),
    CONSTRAINT chk_mirror_dual_model_result_model_a_decision CHECK (
        model_a_decision IN (
            'support', 'reject', 'uncertain', 'insufficient_information', 'unknown'
        )
    ),
    CONSTRAINT chk_mirror_dual_model_result_model_b_decision CHECK (
        model_b_decision IN (
            'support', 'reject', 'uncertain', 'insufficient_information', 'unknown'
        )
    ),
    CONSTRAINT chk_mirror_dual_model_result_consensus_status CHECK (
        consensus_status IN (
            'consensus_supported', 'consensus_rejected', 'model_conflict',
            'insufficient_information', 'needs_human_review', 'unknown'
        )
    ),
    CONSTRAINT chk_mirror_dual_model_result_review_priority CHECK (
        recommended_review_priority IN ('low', 'normal', 'high', 'urgent')
    )
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_mirror_circuit_steps_circuit ON mirror_circuit_steps(circuit_id);
CREATE INDEX IF NOT EXISTS idx_mirror_circuit_steps_region_candidate ON mirror_circuit_steps(region_candidate_id);
CREATE INDEX IF NOT EXISTS idx_mirror_circuit_steps_resource ON mirror_circuit_steps(resource_id);
CREATE INDEX IF NOT EXISTS idx_mirror_circuit_steps_batch ON mirror_circuit_steps(batch_id);
CREATE INDEX IF NOT EXISTS idx_mirror_circuit_steps_atlas_granularity ON mirror_circuit_steps(source_atlas, granularity_level);
CREATE INDEX IF NOT EXISTS idx_mirror_circuit_steps_status ON mirror_circuit_steps(mirror_status, review_status, promotion_status);
CREATE INDEX IF NOT EXISTS idx_mirror_circuit_steps_order ON mirror_circuit_steps(circuit_id, step_order);

CREATE INDEX IF NOT EXISTS idx_mirror_projection_functions_projection ON mirror_projection_functions(projection_id);
CREATE INDEX IF NOT EXISTS idx_mirror_projection_functions_resource ON mirror_projection_functions(resource_id);
CREATE INDEX IF NOT EXISTS idx_mirror_projection_functions_batch ON mirror_projection_functions(batch_id);
CREATE INDEX IF NOT EXISTS idx_mirror_projection_functions_atlas_granularity ON mirror_projection_functions(source_atlas, granularity_level);
CREATE INDEX IF NOT EXISTS idx_mirror_projection_functions_function_term ON mirror_projection_functions(function_term);
CREATE INDEX IF NOT EXISTS idx_mirror_projection_functions_status ON mirror_projection_functions(mirror_status, review_status, promotion_status);

CREATE INDEX IF NOT EXISTS idx_mirror_circuit_projection_memberships_circuit ON mirror_circuit_projection_memberships(circuit_id);
CREATE INDEX IF NOT EXISTS idx_mirror_circuit_projection_memberships_projection ON mirror_circuit_projection_memberships(projection_id);
CREATE INDEX IF NOT EXISTS idx_mirror_circuit_projection_memberships_source_step ON mirror_circuit_projection_memberships(source_step_id);
CREATE INDEX IF NOT EXISTS idx_mirror_circuit_projection_memberships_target_step ON mirror_circuit_projection_memberships(target_step_id);
CREATE INDEX IF NOT EXISTS idx_mirror_circuit_projection_memberships_resource ON mirror_circuit_projection_memberships(resource_id);
CREATE INDEX IF NOT EXISTS idx_mirror_circuit_projection_memberships_batch ON mirror_circuit_projection_memberships(batch_id);
CREATE INDEX IF NOT EXISTS idx_mirror_circuit_projection_memberships_atlas_granularity ON mirror_circuit_projection_memberships(source_atlas, granularity_level);
CREATE INDEX IF NOT EXISTS idx_mirror_circuit_projection_memberships_verification ON mirror_circuit_projection_memberships(verification_status);
CREATE INDEX IF NOT EXISTS idx_mirror_circuit_projection_memberships_status ON mirror_circuit_projection_memberships(mirror_status, review_status, promotion_status);

CREATE INDEX IF NOT EXISTS idx_mirror_dual_model_verification_runs_task ON mirror_dual_model_verification_runs(verification_task_type);
CREATE INDEX IF NOT EXISTS idx_mirror_dual_model_verification_runs_status ON mirror_dual_model_verification_runs(status);
CREATE INDEX IF NOT EXISTS idx_mirror_dual_model_verification_runs_resource ON mirror_dual_model_verification_runs(resource_id);
CREATE INDEX IF NOT EXISTS idx_mirror_dual_model_verification_runs_batch ON mirror_dual_model_verification_runs(batch_id);
CREATE INDEX IF NOT EXISTS idx_mirror_dual_model_verification_runs_atlas_granularity ON mirror_dual_model_verification_runs(source_atlas, granularity_level);
CREATE INDEX IF NOT EXISTS idx_mirror_dual_model_verification_runs_created ON mirror_dual_model_verification_runs(created_at DESC);

CREATE INDEX IF NOT EXISTS idx_mirror_dual_model_verification_results_run ON mirror_dual_model_verification_results(run_id);
CREATE INDEX IF NOT EXISTS idx_mirror_dual_model_verification_results_object ON mirror_dual_model_verification_results(object_type, object_id);
CREATE INDEX IF NOT EXISTS idx_mirror_dual_model_verification_results_consensus ON mirror_dual_model_verification_results(consensus_status);
CREATE INDEX IF NOT EXISTS idx_mirror_dual_model_verification_results_priority ON mirror_dual_model_verification_results(recommended_review_priority);
CREATE INDEX IF NOT EXISTS idx_mirror_dual_model_verification_results_resource ON mirror_dual_model_verification_results(resource_id);
CREATE INDEX IF NOT EXISTS idx_mirror_dual_model_verification_results_batch ON mirror_dual_model_verification_results(batch_id);
CREATE INDEX IF NOT EXISTS idx_mirror_dual_model_verification_results_atlas_granularity ON mirror_dual_model_verification_results(source_atlas, granularity_level);

COMMENT ON TABLE mirror_region_connections IS 'Mirror KG connection candidates; macro_clinical semantic = projection';
COMMENT ON TABLE mirror_circuit_steps IS 'Ordered circuit steps (macro_clinical circuit_step)';
COMMENT ON TABLE mirror_projection_functions IS 'Projection/connection function (macro_clinical projection_function)';
COMMENT ON TABLE mirror_circuit_projection_memberships IS 'circuit contains projection / projection belongs_to circuit';
COMMENT ON TABLE mirror_dual_model_verification_runs IS 'Dual-model verification run metadata (no auto-approve/promote)';
COMMENT ON TABLE mirror_dual_model_verification_results IS 'Per-object DeepSeek/Kimi consensus or conflict record';
