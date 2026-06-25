-- Mirror KG Schema Foundation (Step 2)
-- Manual execution only; application does NOT auto-run this file.
--
-- Depends on: 001–009, 021 (llm_extraction_runs, llm_extraction_items)
--
-- Adds Mirror KG tables for connection/function/circuit/triple/evidence candidates.
-- Does NOT write final_* or kg_*.

-- Shared status CHECK values reused across mirror entity tables.

CREATE TABLE IF NOT EXISTS mirror_region_connections (
    id                          UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    source_region_candidate_id  UUID REFERENCES candidate_brain_regions(id) ON DELETE SET NULL,
    target_region_candidate_id  UUID REFERENCES candidate_brain_regions(id) ON DELETE SET NULL,
    source_region_final_id      UUID,
    target_region_final_id      UUID,
    resource_id                 UUID REFERENCES atlas_resources(id) ON DELETE SET NULL,
    batch_id                    UUID REFERENCES import_batches(id) ON DELETE SET NULL,
    llm_run_id                  UUID REFERENCES llm_extraction_runs(id) ON DELETE SET NULL,
    llm_item_id                 UUID REFERENCES llm_extraction_items(id) ON DELETE SET NULL,
    granularity_level           TEXT NOT NULL,
    granularity_family          TEXT,
    source_atlas                TEXT NOT NULL,
    source_version              TEXT,
    connection_type             TEXT NOT NULL,
    directionality              TEXT NOT NULL DEFAULT 'unknown',
    strength                    TEXT,
    modality                    TEXT,
    confidence                  NUMERIC,
    evidence_text               TEXT,
    uncertainty_reason          TEXT,
    mirror_status               TEXT NOT NULL DEFAULT 'llm_suggested',
    review_status               TEXT NOT NULL DEFAULT 'pending',
    promotion_status            TEXT NOT NULL DEFAULT 'not_promoted',
    raw_payload_json            JSONB NOT NULL DEFAULT '{}'::jsonb,
    normalized_payload_json     JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_by                  TEXT,
    updated_by                  TEXT,
    created_at                  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at                  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT chk_mirror_connection_type CHECK (
        connection_type IN (
            'structural_connection', 'functional_connectivity', 'effective_connectivity',
            'projection', 'association', 'coactivation', 'uncertain_connection', 'unknown'
        )
    ),
    CONSTRAINT chk_mirror_connection_directionality CHECK (
        directionality IN ('directed', 'undirected', 'bidirectional', 'unknown')
    ),
    CONSTRAINT chk_mirror_connection_mirror_status CHECK (
        mirror_status IN (
            'llm_suggested', 'rule_checked', 'human_review_pending', 'human_approved',
            'human_rejected', 'promoted_to_final', 'superseded'
        )
    ),
    CONSTRAINT chk_mirror_connection_review_status CHECK (
        review_status IN ('pending', 'approved', 'rejected', 'needs_revision', 'not_required')
    ),
    CONSTRAINT chk_mirror_connection_promotion_status CHECK (
        promotion_status IN ('not_promoted', 'promoted', 'failed', 'blocked')
    )
);

CREATE TABLE IF NOT EXISTS mirror_region_functions (
    id                      UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    region_candidate_id     UUID REFERENCES candidate_brain_regions(id) ON DELETE SET NULL,
    region_final_id         UUID,
    resource_id             UUID REFERENCES atlas_resources(id) ON DELETE SET NULL,
    batch_id                UUID REFERENCES import_batches(id) ON DELETE SET NULL,
    llm_run_id              UUID REFERENCES llm_extraction_runs(id) ON DELETE SET NULL,
    llm_item_id             UUID REFERENCES llm_extraction_items(id) ON DELETE SET NULL,
    granularity_level       TEXT NOT NULL,
    granularity_family        TEXT,
    source_atlas              TEXT NOT NULL,
    source_version            TEXT,
    function_term             TEXT NOT NULL,
    function_category         TEXT NOT NULL DEFAULT 'unknown',
    relation_type             TEXT NOT NULL DEFAULT 'associated_with',
    confidence                NUMERIC,
    evidence_text             TEXT,
    uncertainty_reason        TEXT,
    mirror_status             TEXT NOT NULL DEFAULT 'llm_suggested',
    review_status             TEXT NOT NULL DEFAULT 'pending',
    promotion_status          TEXT NOT NULL DEFAULT 'not_promoted',
    raw_payload_json          JSONB NOT NULL DEFAULT '{}'::jsonb,
    normalized_payload_json   JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_by                TEXT,
    updated_by                TEXT,
    created_at                TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at                TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT chk_mirror_function_category CHECK (
        function_category IN (
            'motor', 'sensory', 'visual', 'auditory', 'language', 'memory', 'emotion',
            'executive_control', 'attention', 'autonomic', 'default_mode', 'salience',
            'reward', 'cognitive', 'unknown'
        )
    ),
    CONSTRAINT chk_mirror_function_relation_type CHECK (
        relation_type IN (
            'involved_in', 'associated_with', 'necessary_for', 'modulates',
            'participates_in', 'uncertain_association', 'unknown'
        )
    ),
    CONSTRAINT chk_mirror_function_mirror_status CHECK (
        mirror_status IN (
            'llm_suggested', 'rule_checked', 'human_review_pending', 'human_approved',
            'human_rejected', 'promoted_to_final', 'superseded'
        )
    ),
    CONSTRAINT chk_mirror_function_review_status CHECK (
        review_status IN ('pending', 'approved', 'rejected', 'needs_revision', 'not_required')
    ),
    CONSTRAINT chk_mirror_function_promotion_status CHECK (
        promotion_status IN ('not_promoted', 'promoted', 'failed', 'blocked')
    )
);

CREATE TABLE IF NOT EXISTS mirror_region_circuits (
    id                      UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    resource_id             UUID REFERENCES atlas_resources(id) ON DELETE SET NULL,
    batch_id                UUID REFERENCES import_batches(id) ON DELETE SET NULL,
    llm_run_id              UUID REFERENCES llm_extraction_runs(id) ON DELETE SET NULL,
    llm_item_id             UUID REFERENCES llm_extraction_items(id) ON DELETE SET NULL,
    granularity_level       TEXT NOT NULL,
    granularity_family        TEXT,
    source_atlas              TEXT NOT NULL,
    source_version            TEXT,
    circuit_name              TEXT NOT NULL,
    circuit_type              TEXT NOT NULL DEFAULT 'unknown',
    function_association      TEXT,
    description               TEXT,
    confidence                NUMERIC,
    evidence_text             TEXT,
    uncertainty_reason        TEXT,
    mirror_status             TEXT NOT NULL DEFAULT 'llm_suggested',
    review_status             TEXT NOT NULL DEFAULT 'pending',
    promotion_status          TEXT NOT NULL DEFAULT 'not_promoted',
    raw_payload_json          JSONB NOT NULL DEFAULT '{}'::jsonb,
    normalized_payload_json   JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_by                TEXT,
    updated_by                TEXT,
    created_at                TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at                TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT chk_mirror_circuit_type CHECK (
        circuit_type IN (
            'sensory_circuit', 'motor_circuit', 'limbic_circuit', 'cognitive_control_circuit',
            'default_mode_related', 'salience_related', 'memory_related', 'reward_related',
            'language_related', 'attention_related', 'uncertain_circuit', 'unknown'
        )
    ),
    CONSTRAINT chk_mirror_circuit_mirror_status CHECK (
        mirror_status IN (
            'llm_suggested', 'rule_checked', 'human_review_pending', 'human_approved',
            'human_rejected', 'promoted_to_final', 'superseded'
        )
    ),
    CONSTRAINT chk_mirror_circuit_review_status CHECK (
        review_status IN ('pending', 'approved', 'rejected', 'needs_revision', 'not_required')
    ),
    CONSTRAINT chk_mirror_circuit_promotion_status CHECK (
        promotion_status IN ('not_promoted', 'promoted', 'failed', 'blocked')
    )
);

CREATE TABLE IF NOT EXISTS mirror_circuit_regions (
    id                  UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    circuit_id          UUID NOT NULL REFERENCES mirror_region_circuits(id) ON DELETE CASCADE,
    region_candidate_id UUID REFERENCES candidate_brain_regions(id) ON DELETE SET NULL,
    region_final_id     UUID,
    role                TEXT NOT NULL DEFAULT 'participant',
    sort_order          INTEGER NOT NULL DEFAULT 0,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT chk_mirror_circuit_region_role CHECK (
        role IN ('participant', 'source', 'target', 'hub', 'relay', 'modulator', 'unknown')
    )
);

CREATE TABLE IF NOT EXISTS mirror_kg_triples (
    id                          UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    subject_type                TEXT NOT NULL,
    subject_id                  UUID,
    subject_label               TEXT NOT NULL,
    predicate                   TEXT NOT NULL,
    object_type                 TEXT NOT NULL,
    object_id                   UUID,
    object_label                TEXT NOT NULL,
    triple_scope                TEXT NOT NULL DEFAULT 'same_granularity',
    resource_id                 UUID REFERENCES atlas_resources(id) ON DELETE SET NULL,
    batch_id                    UUID REFERENCES import_batches(id) ON DELETE SET NULL,
    llm_run_id                  UUID REFERENCES llm_extraction_runs(id) ON DELETE SET NULL,
    llm_item_id                 UUID REFERENCES llm_extraction_items(id) ON DELETE SET NULL,
    source_mirror_connection_id UUID REFERENCES mirror_region_connections(id) ON DELETE SET NULL,
    source_mirror_function_id   UUID REFERENCES mirror_region_functions(id) ON DELETE SET NULL,
    source_mirror_circuit_id    UUID REFERENCES mirror_region_circuits(id) ON DELETE SET NULL,
    granularity_level           TEXT NOT NULL,
    granularity_family          TEXT,
    source_atlas                TEXT NOT NULL,
    source_version              TEXT,
    confidence                  NUMERIC,
    evidence_text               TEXT,
    uncertainty_reason          TEXT,
    mirror_status               TEXT NOT NULL DEFAULT 'llm_suggested',
    review_status               TEXT NOT NULL DEFAULT 'pending',
    promotion_status            TEXT NOT NULL DEFAULT 'not_promoted',
    raw_payload_json            JSONB NOT NULL DEFAULT '{}'::jsonb,
    normalized_payload_json     JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_by                  TEXT,
    updated_by                  TEXT,
    created_at                  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at                  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT chk_mirror_triple_subject_type CHECK (
        subject_type IN (
            'region_candidate', 'region_final', 'connection', 'circuit',
            'function', 'term', 'literal', 'unknown'
        )
    ),
    CONSTRAINT chk_mirror_triple_object_type CHECK (
        object_type IN (
            'region_candidate', 'region_final', 'connection', 'circuit',
            'function', 'term', 'literal', 'unknown'
        )
    ),
    CONSTRAINT chk_mirror_triple_scope CHECK (
        triple_scope IN ('same_granularity', 'cross_granularity_mapping', 'evidence_link', 'unknown')
    ),
    CONSTRAINT chk_mirror_triple_mirror_status CHECK (
        mirror_status IN (
            'llm_suggested', 'rule_checked', 'human_review_pending', 'human_approved',
            'human_rejected', 'promoted_to_final', 'superseded'
        )
    ),
    CONSTRAINT chk_mirror_triple_review_status CHECK (
        review_status IN ('pending', 'approved', 'rejected', 'needs_revision', 'not_required')
    ),
    CONSTRAINT chk_mirror_triple_promotion_status CHECK (
        promotion_status IN ('not_promoted', 'promoted', 'failed', 'blocked')
    )
);

CREATE TABLE IF NOT EXISTS mirror_evidence_records (
    id                      UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    evidence_target_type    TEXT NOT NULL,
    evidence_target_id      UUID NOT NULL,
    resource_id             UUID REFERENCES atlas_resources(id) ON DELETE SET NULL,
    batch_id                UUID REFERENCES import_batches(id) ON DELETE SET NULL,
    llm_run_id              UUID REFERENCES llm_extraction_runs(id) ON DELETE SET NULL,
    llm_item_id             UUID REFERENCES llm_extraction_items(id) ON DELETE SET NULL,
    evidence_type           TEXT NOT NULL DEFAULT 'llm_explanation',
    evidence_text           TEXT NOT NULL,
    source_document_id      UUID,
    source_reference_text   TEXT,
    citation_json           JSONB NOT NULL DEFAULT '{}'::jsonb,
    confidence              NUMERIC,
    uncertainty_reason      TEXT,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT chk_mirror_evidence_target_type CHECK (
        evidence_target_type IN (
            'mirror_connection', 'mirror_function', 'mirror_circuit', 'mirror_triple', 'unknown'
        )
    ),
    CONSTRAINT chk_mirror_evidence_type CHECK (
        evidence_type IN (
            'llm_explanation', 'literature', 'curated_database',
            'manual_note', 'rule_validation', 'unknown'
        )
    )
);

-- mirror_region_connections indexes
CREATE INDEX IF NOT EXISTS idx_mirror_conn_source_candidate ON mirror_region_connections (source_region_candidate_id);
CREATE INDEX IF NOT EXISTS idx_mirror_conn_target_candidate ON mirror_region_connections (target_region_candidate_id);
CREATE INDEX IF NOT EXISTS idx_mirror_conn_resource ON mirror_region_connections (resource_id);
CREATE INDEX IF NOT EXISTS idx_mirror_conn_batch ON mirror_region_connections (batch_id);
CREATE INDEX IF NOT EXISTS idx_mirror_conn_llm_run ON mirror_region_connections (llm_run_id);
CREATE INDEX IF NOT EXISTS idx_mirror_conn_llm_item ON mirror_region_connections (llm_item_id);
CREATE INDEX IF NOT EXISTS idx_mirror_conn_source_atlas ON mirror_region_connections (source_atlas);
CREATE INDEX IF NOT EXISTS idx_mirror_conn_granularity ON mirror_region_connections (granularity_level);
CREATE INDEX IF NOT EXISTS idx_mirror_conn_mirror_status ON mirror_region_connections (mirror_status);
CREATE INDEX IF NOT EXISTS idx_mirror_conn_review_status ON mirror_region_connections (review_status);

-- mirror_region_functions indexes
CREATE INDEX IF NOT EXISTS idx_mirror_func_region_candidate ON mirror_region_functions (region_candidate_id);
CREATE INDEX IF NOT EXISTS idx_mirror_func_resource ON mirror_region_functions (resource_id);
CREATE INDEX IF NOT EXISTS idx_mirror_func_batch ON mirror_region_functions (batch_id);
CREATE INDEX IF NOT EXISTS idx_mirror_func_llm_run ON mirror_region_functions (llm_run_id);
CREATE INDEX IF NOT EXISTS idx_mirror_func_llm_item ON mirror_region_functions (llm_item_id);
CREATE INDEX IF NOT EXISTS idx_mirror_func_term ON mirror_region_functions (function_term);
CREATE INDEX IF NOT EXISTS idx_mirror_func_category ON mirror_region_functions (function_category);
CREATE INDEX IF NOT EXISTS idx_mirror_func_source_atlas ON mirror_region_functions (source_atlas);
CREATE INDEX IF NOT EXISTS idx_mirror_func_granularity ON mirror_region_functions (granularity_level);
CREATE INDEX IF NOT EXISTS idx_mirror_func_mirror_status ON mirror_region_functions (mirror_status);
CREATE INDEX IF NOT EXISTS idx_mirror_func_review_status ON mirror_region_functions (review_status);

-- mirror_region_circuits indexes
CREATE INDEX IF NOT EXISTS idx_mirror_circuit_resource ON mirror_region_circuits (resource_id);
CREATE INDEX IF NOT EXISTS idx_mirror_circuit_batch ON mirror_region_circuits (batch_id);
CREATE INDEX IF NOT EXISTS idx_mirror_circuit_llm_run ON mirror_region_circuits (llm_run_id);
CREATE INDEX IF NOT EXISTS idx_mirror_circuit_llm_item ON mirror_region_circuits (llm_item_id);
CREATE INDEX IF NOT EXISTS idx_mirror_circuit_name ON mirror_region_circuits (circuit_name);
CREATE INDEX IF NOT EXISTS idx_mirror_circuit_type ON mirror_region_circuits (circuit_type);
CREATE INDEX IF NOT EXISTS idx_mirror_circuit_source_atlas ON mirror_region_circuits (source_atlas);
CREATE INDEX IF NOT EXISTS idx_mirror_circuit_granularity ON mirror_region_circuits (granularity_level);
CREATE INDEX IF NOT EXISTS idx_mirror_circuit_mirror_status ON mirror_region_circuits (mirror_status);
CREATE INDEX IF NOT EXISTS idx_mirror_circuit_review_status ON mirror_region_circuits (review_status);

-- mirror_circuit_regions indexes
CREATE INDEX IF NOT EXISTS idx_mirror_circuit_regions_circuit ON mirror_circuit_regions (circuit_id);
CREATE INDEX IF NOT EXISTS idx_mirror_circuit_regions_candidate ON mirror_circuit_regions (region_candidate_id);
CREATE INDEX IF NOT EXISTS idx_mirror_circuit_regions_role ON mirror_circuit_regions (role);

-- mirror_kg_triples indexes
CREATE INDEX IF NOT EXISTS idx_mirror_triple_subject ON mirror_kg_triples (subject_type, subject_id);
CREATE INDEX IF NOT EXISTS idx_mirror_triple_object ON mirror_kg_triples (object_type, object_id);
CREATE INDEX IF NOT EXISTS idx_mirror_triple_predicate ON mirror_kg_triples (predicate);
CREATE INDEX IF NOT EXISTS idx_mirror_triple_resource ON mirror_kg_triples (resource_id);
CREATE INDEX IF NOT EXISTS idx_mirror_triple_batch ON mirror_kg_triples (batch_id);
CREATE INDEX IF NOT EXISTS idx_mirror_triple_llm_run ON mirror_kg_triples (llm_run_id);
CREATE INDEX IF NOT EXISTS idx_mirror_triple_llm_item ON mirror_kg_triples (llm_item_id);
CREATE INDEX IF NOT EXISTS idx_mirror_triple_source_atlas ON mirror_kg_triples (source_atlas);
CREATE INDEX IF NOT EXISTS idx_mirror_triple_granularity ON mirror_kg_triples (granularity_level);
CREATE INDEX IF NOT EXISTS idx_mirror_triple_mirror_status ON mirror_kg_triples (mirror_status);
CREATE INDEX IF NOT EXISTS idx_mirror_triple_review_status ON mirror_kg_triples (review_status);

-- mirror_evidence_records indexes
CREATE INDEX IF NOT EXISTS idx_mirror_evidence_target ON mirror_evidence_records (evidence_target_type, evidence_target_id);
CREATE INDEX IF NOT EXISTS idx_mirror_evidence_llm_run ON mirror_evidence_records (llm_run_id);
CREATE INDEX IF NOT EXISTS idx_mirror_evidence_llm_item ON mirror_evidence_records (llm_item_id);
CREATE INDEX IF NOT EXISTS idx_mirror_evidence_resource ON mirror_evidence_records (resource_id);
CREATE INDEX IF NOT EXISTS idx_mirror_evidence_batch ON mirror_evidence_records (batch_id);
