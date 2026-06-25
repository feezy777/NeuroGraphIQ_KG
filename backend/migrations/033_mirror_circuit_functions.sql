-- Mirror Circuit Function Foundation (Step 10.6.1)
-- Manual execution only; application does NOT auto-run this file.
--
-- Depends on: 022 (mirror_region_circuits), 021 (llm_extraction_*), 026 (mirror macro clinical pattern)
--
-- Adds mirror_circuit_functions aligned to macro_clinical.circuit_function formal fields (documented).
-- Does NOT write macro_clinical.* / final_* / kg_*.

CREATE TABLE IF NOT EXISTS mirror_circuit_functions (
    id                      UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    circuit_id              UUID NOT NULL REFERENCES mirror_region_circuits(id) ON DELETE CASCADE,
    resource_id             UUID REFERENCES atlas_resources(id) ON DELETE SET NULL,
    batch_id                UUID REFERENCES import_batches(id) ON DELETE SET NULL,
    llm_run_id              UUID REFERENCES llm_extraction_runs(id) ON DELETE SET NULL,
    llm_item_id             UUID REFERENCES llm_extraction_items(id) ON DELETE SET NULL,
    primary_evidence_id     UUID,
    external_code           TEXT,
    granularity_level       TEXT NOT NULL,
    granularity_family      TEXT,
    source_atlas            TEXT NOT NULL,
    source_version          TEXT,
    function_term_en        TEXT,
    function_term_cn        TEXT,
    function_domain         TEXT,
    function_role           TEXT,
    effect_type             TEXT,
    confidence_score        NUMERIC,
    evidence_level          TEXT,
    description             TEXT,
    remark                  TEXT,
    attributes              JSONB NOT NULL DEFAULT '{}'::jsonb,
    source_db               TEXT,
    status                  TEXT DEFAULT 'active',
    mirror_status           TEXT NOT NULL DEFAULT 'llm_suggested',
    review_status           TEXT NOT NULL DEFAULT 'pending',
    validation_status       TEXT,
    promotion_status        TEXT NOT NULL DEFAULT 'not_promoted',
    confidence              NUMERIC,
    evidence_text           TEXT,
    provenance              TEXT,
    uncertainty_reason      TEXT,
    raw_payload_json        JSONB NOT NULL DEFAULT '{}'::jsonb,
    normalized_payload_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_by              TEXT,
    updated_by              TEXT,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT chk_mirror_circuit_function_status CHECK (
        status IS NULL OR status IN ('active', 'inactive', 'deprecated', 'candidate', 'unknown')
    ),
    CONSTRAINT chk_mirror_circuit_function_mirror_status CHECK (
        mirror_status IN (
            'llm_suggested', 'rule_checked', 'human_review_pending', 'human_approved',
            'human_rejected', 'promoted_to_final', 'superseded'
        )
    ),
    CONSTRAINT chk_mirror_circuit_function_review_status CHECK (
        review_status IN ('pending', 'approved', 'rejected', 'needs_revision', 'not_required')
    ),
    CONSTRAINT chk_mirror_circuit_function_promotion_status CHECK (
        promotion_status IN ('not_promoted', 'promoted', 'failed', 'blocked')
    )
);

CREATE INDEX IF NOT EXISTS idx_mirror_circuit_functions_circuit_id
    ON mirror_circuit_functions(circuit_id);
CREATE INDEX IF NOT EXISTS idx_mirror_circuit_functions_batch_id
    ON mirror_circuit_functions(batch_id);
CREATE INDEX IF NOT EXISTS idx_mirror_circuit_functions_resource_id
    ON mirror_circuit_functions(resource_id);
CREATE INDEX IF NOT EXISTS idx_mirror_circuit_functions_review_status
    ON mirror_circuit_functions(review_status);
CREATE INDEX IF NOT EXISTS idx_mirror_circuit_functions_promotion_status
    ON mirror_circuit_functions(promotion_status);
CREATE INDEX IF NOT EXISTS idx_mirror_circuit_functions_status
    ON mirror_circuit_functions(status);
CREATE INDEX IF NOT EXISTS idx_mirror_circuit_functions_function_domain
    ON mirror_circuit_functions(function_domain);
CREATE INDEX IF NOT EXISTS idx_mirror_circuit_functions_function_role
    ON mirror_circuit_functions(function_role);
CREATE INDEX IF NOT EXISTS idx_mirror_circuit_functions_llm_run
    ON mirror_circuit_functions(llm_run_id);
CREATE INDEX IF NOT EXISTS idx_mirror_circuit_functions_atlas_granularity
    ON mirror_circuit_functions(source_atlas, granularity_level);

COMMENT ON TABLE mirror_circuit_functions IS
    'Mirror KG circuit-level function candidates (macro_clinical.circuit_function alignment)';

-- Rollback (manual):
-- DROP TABLE IF EXISTS mirror_circuit_functions CASCADE;
