-- MVP 2 Step 9 — Mirror KG Promotion to Final KG
-- Manual execution only; application does NOT auto-run this file.
--
-- Depends on: 022_mirror_kg_schema.sql, 024_mirror_kg_human_review.sql
-- Writes final_* tables in current workbench DB only. Does NOT write kg_*.

CREATE TABLE IF NOT EXISTS final_region_connections (
    id                          UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    source_mirror_connection_id UUID NULL REFERENCES mirror_region_connections(id) ON DELETE SET NULL,
    source_region_candidate_id  UUID NULL REFERENCES candidate_brain_regions(id) ON DELETE SET NULL,
    target_region_candidate_id  UUID NULL REFERENCES candidate_brain_regions(id) ON DELETE SET NULL,
    source_region_final_id      UUID NULL,
    target_region_final_id      UUID NULL,
    resource_id                 UUID NULL REFERENCES atlas_resources(id) ON DELETE SET NULL,
    batch_id                    UUID NULL REFERENCES import_batches(id) ON DELETE SET NULL,
    llm_run_id                  UUID NULL,
    llm_item_id                 UUID NULL,
    review_record_id            UUID NULL REFERENCES mirror_human_review_records(id) ON DELETE SET NULL,
    promotion_record_id         UUID NULL,
    granularity_level           TEXT NOT NULL,
    granularity_family        TEXT NULL,
    source_atlas                TEXT NOT NULL,
    source_version              TEXT NULL,
    connection_type             TEXT NOT NULL,
    directionality              TEXT NOT NULL DEFAULT 'unknown',
    strength                    TEXT NULL,
    modality                    TEXT NULL,
    confidence                  NUMERIC NULL,
    evidence_text               TEXT NULL,
    uncertainty_reason          TEXT NULL,
    final_status                TEXT NOT NULL DEFAULT 'active',
    raw_payload_json            JSONB NOT NULL DEFAULT '{}'::jsonb,
    normalized_payload_json     JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at                  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at                  TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT chk_final_connection_status CHECK (final_status IN ('active', 'deprecated', 'superseded'))
);

CREATE TABLE IF NOT EXISTS final_region_functions (
    id                          UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    source_mirror_function_id   UUID NULL REFERENCES mirror_region_functions(id) ON DELETE SET NULL,
    region_candidate_id         UUID NULL REFERENCES candidate_brain_regions(id) ON DELETE SET NULL,
    region_final_id             UUID NULL,
    resource_id                 UUID NULL REFERENCES atlas_resources(id) ON DELETE SET NULL,
    batch_id                    UUID NULL REFERENCES import_batches(id) ON DELETE SET NULL,
    llm_run_id                  UUID NULL,
    llm_item_id                 UUID NULL,
    review_record_id            UUID NULL REFERENCES mirror_human_review_records(id) ON DELETE SET NULL,
    promotion_record_id         UUID NULL,
    granularity_level           TEXT NOT NULL,
    granularity_family          TEXT NULL,
    source_atlas                TEXT NOT NULL,
    source_version              TEXT NULL,
    function_term               TEXT NOT NULL,
    function_category           TEXT NOT NULL DEFAULT 'unknown',
    relation_type               TEXT NOT NULL DEFAULT 'associated_with',
    confidence                  NUMERIC NULL,
    evidence_text               TEXT NULL,
    uncertainty_reason          TEXT NULL,
    final_status                TEXT NOT NULL DEFAULT 'active',
    raw_payload_json            JSONB NOT NULL DEFAULT '{}'::jsonb,
    normalized_payload_json     JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at                  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at                  TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT chk_final_function_status CHECK (final_status IN ('active', 'deprecated', 'superseded'))
);

CREATE TABLE IF NOT EXISTS final_region_circuits (
    id                          UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    source_mirror_circuit_id    UUID NULL REFERENCES mirror_region_circuits(id) ON DELETE SET NULL,
    resource_id                 UUID NULL REFERENCES atlas_resources(id) ON DELETE SET NULL,
    batch_id                    UUID NULL REFERENCES import_batches(id) ON DELETE SET NULL,
    llm_run_id                  UUID NULL,
    llm_item_id                 UUID NULL,
    review_record_id            UUID NULL REFERENCES mirror_human_review_records(id) ON DELETE SET NULL,
    promotion_record_id         UUID NULL,
    granularity_level           TEXT NOT NULL,
    granularity_family          TEXT NULL,
    source_atlas                TEXT NOT NULL,
    source_version              TEXT NULL,
    circuit_name                TEXT NOT NULL,
    circuit_type                TEXT NOT NULL DEFAULT 'unknown',
    function_association        TEXT NULL,
    description                 TEXT NULL,
    confidence                  NUMERIC NULL,
    evidence_text               TEXT NULL,
    uncertainty_reason          TEXT NULL,
    final_status                TEXT NOT NULL DEFAULT 'active',
    raw_payload_json            JSONB NOT NULL DEFAULT '{}'::jsonb,
    normalized_payload_json     JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at                  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at                  TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT chk_final_circuit_status CHECK (final_status IN ('active', 'deprecated', 'superseded'))
);

CREATE TABLE IF NOT EXISTS final_circuit_regions (
    id                              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    final_circuit_id                UUID NOT NULL REFERENCES final_region_circuits(id) ON DELETE CASCADE,
    source_mirror_circuit_region_id UUID NULL,
    region_candidate_id             UUID NULL REFERENCES candidate_brain_regions(id) ON DELETE SET NULL,
    region_final_id                 UUID NULL,
    role                            TEXT NOT NULL DEFAULT 'participant',
    sort_order                      INTEGER NOT NULL DEFAULT 0,
    created_at                      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS final_kg_triples (
    id                          UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    source_mirror_triple_id     UUID NULL REFERENCES mirror_kg_triples(id) ON DELETE SET NULL,
    subject_type                TEXT NOT NULL,
    subject_id                  UUID NULL,
    subject_label               TEXT NOT NULL,
    predicate                   TEXT NOT NULL,
    object_type                 TEXT NOT NULL,
    object_id                   UUID NULL,
    object_label                TEXT NOT NULL,
    triple_scope                TEXT NOT NULL DEFAULT 'same_granularity',
    resource_id                 UUID NULL REFERENCES atlas_resources(id) ON DELETE SET NULL,
    batch_id                    UUID NULL REFERENCES import_batches(id) ON DELETE SET NULL,
    llm_run_id                  UUID NULL,
    llm_item_id                 UUID NULL,
    review_record_id            UUID NULL REFERENCES mirror_human_review_records(id) ON DELETE SET NULL,
    promotion_record_id         UUID NULL,
    source_final_connection_id  UUID NULL REFERENCES final_region_connections(id) ON DELETE SET NULL,
    source_final_function_id    UUID NULL REFERENCES final_region_functions(id) ON DELETE SET NULL,
    source_final_circuit_id     UUID NULL REFERENCES final_region_circuits(id) ON DELETE SET NULL,
    source_mirror_connection_id UUID NULL,
    source_mirror_function_id   UUID NULL,
    source_mirror_circuit_id    UUID NULL,
    granularity_level           TEXT NOT NULL,
    granularity_family            TEXT NULL,
    source_atlas                TEXT NOT NULL,
    source_version              TEXT NULL,
    confidence                  NUMERIC NULL,
    evidence_text               TEXT NULL,
    uncertainty_reason          TEXT NULL,
    final_status                TEXT NOT NULL DEFAULT 'active',
    raw_payload_json            JSONB NOT NULL DEFAULT '{}'::jsonb,
    normalized_payload_json     JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at                  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at                  TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT chk_final_triple_status CHECK (final_status IN ('active', 'deprecated', 'superseded'))
);

CREATE TABLE IF NOT EXISTS final_evidence_records (
    id                      UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    evidence_target_type    TEXT NOT NULL,
    evidence_target_id      UUID NOT NULL,
    source_mirror_evidence_id UUID NULL REFERENCES mirror_evidence_records(id) ON DELETE SET NULL,
    resource_id             UUID NULL REFERENCES atlas_resources(id) ON DELETE SET NULL,
    batch_id                UUID NULL REFERENCES import_batches(id) ON DELETE SET NULL,
    llm_run_id              UUID NULL,
    llm_item_id             UUID NULL,
    review_record_id        UUID NULL REFERENCES mirror_human_review_records(id) ON DELETE SET NULL,
    promotion_record_id     UUID NULL,
    evidence_type           TEXT NOT NULL DEFAULT 'llm_explanation',
    evidence_text           TEXT NOT NULL,
    source_document_id      UUID NULL,
    source_reference_text   TEXT NULL,
    citation_json           JSONB NOT NULL DEFAULT '{}'::jsonb,
    confidence              NUMERIC NULL,
    uncertainty_reason      TEXT NULL,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT chk_final_evidence_target_type CHECK (
        evidence_target_type IN ('final_connection', 'final_function', 'final_circuit', 'final_triple', 'unknown')
    )
);

CREATE TABLE IF NOT EXISTS mirror_promotion_runs (
    id                      UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    target_types            TEXT[] NOT NULL DEFAULT ARRAY[]::TEXT[],
    scope_json              JSONB NOT NULL DEFAULT '{}'::jsonb,
    resource_id             UUID NULL REFERENCES atlas_resources(id) ON DELETE SET NULL,
    batch_id                UUID NULL REFERENCES import_batches(id) ON DELETE SET NULL,
    source_atlas            TEXT NULL,
    source_version          TEXT NULL,
    granularity_level       TEXT NULL,
    granularity_family      TEXT NULL,
    status                  TEXT NOT NULL DEFAULT 'created',
    object_count            INTEGER NOT NULL DEFAULT 0,
    eligible_count          INTEGER NOT NULL DEFAULT 0,
    promoted_count          INTEGER NOT NULL DEFAULT 0,
    skipped_duplicate_count INTEGER NOT NULL DEFAULT 0,
    skipped_ineligible_count INTEGER NOT NULL DEFAULT 0,
    failed_count            INTEGER NOT NULL DEFAULT 0,
    dry_run                 BOOLEAN NOT NULL DEFAULT false,
    confirmation_text       TEXT NULL,
    required_confirmation   TEXT NULL,
    operator                TEXT NULL,
    reason                  TEXT NULL,
    error_message           TEXT NULL,
    started_at              TIMESTAMPTZ NULL,
    finished_at             TIMESTAMPTZ NULL,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT chk_mirror_promotion_runs_status CHECK (
        status IN ('created', 'running', 'succeeded', 'partially_succeeded', 'failed', 'cancelled')
    )
);

CREATE TABLE IF NOT EXISTS mirror_promotion_records (
    id                  UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    run_id              UUID NOT NULL REFERENCES mirror_promotion_runs(id) ON DELETE CASCADE,
    target_type         TEXT NOT NULL,
    mirror_target_id    UUID NOT NULL,
    final_target_type   TEXT NULL,
    final_target_id     UUID NULL,
    review_record_id    UUID NULL REFERENCES mirror_human_review_records(id) ON DELETE SET NULL,
    status              TEXT NOT NULL,
    message             TEXT NULL,
    before_mirror_json  JSONB NOT NULL DEFAULT '{}'::jsonb,
    after_mirror_json   JSONB NOT NULL DEFAULT '{}'::jsonb,
    final_object_json   JSONB NOT NULL DEFAULT '{}'::jsonb,
    resource_id         UUID NULL REFERENCES atlas_resources(id) ON DELETE SET NULL,
    batch_id            UUID NULL REFERENCES import_batches(id) ON DELETE SET NULL,
    source_atlas        TEXT NULL,
    granularity_level   TEXT NULL,
    granularity_family  TEXT NULL,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT chk_mirror_promotion_records_target_type CHECK (
        target_type IN ('connection', 'function', 'circuit', 'triple')
    ),
    CONSTRAINT chk_mirror_promotion_records_final_type CHECK (
        final_target_type IS NULL OR final_target_type IN (
            'final_connection', 'final_function', 'final_circuit', 'final_triple'
        )
    ),
    CONSTRAINT chk_mirror_promotion_records_status CHECK (
        status IN ('promoted', 'skipped_duplicate', 'skipped_ineligible', 'failed')
    )
);

CREATE INDEX IF NOT EXISTS idx_final_connection_mirror ON final_region_connections (source_mirror_connection_id);
CREATE INDEX IF NOT EXISTS idx_final_connection_src ON final_region_connections (source_region_candidate_id);
CREATE INDEX IF NOT EXISTS idx_final_connection_tgt ON final_region_connections (target_region_candidate_id);
CREATE INDEX IF NOT EXISTS idx_final_connection_resource ON final_region_connections (resource_id);
CREATE INDEX IF NOT EXISTS idx_final_connection_batch ON final_region_connections (batch_id);
CREATE INDEX IF NOT EXISTS idx_final_connection_atlas ON final_region_connections (source_atlas);
CREATE INDEX IF NOT EXISTS idx_final_connection_gran ON final_region_connections (granularity_level);
CREATE INDEX IF NOT EXISTS idx_final_connection_type ON final_region_connections (connection_type);
CREATE INDEX IF NOT EXISTS idx_final_connection_status ON final_region_connections (final_status);

CREATE INDEX IF NOT EXISTS idx_final_function_mirror ON final_region_functions (source_mirror_function_id);
CREATE INDEX IF NOT EXISTS idx_final_function_region ON final_region_functions (region_candidate_id);
CREATE INDEX IF NOT EXISTS idx_final_function_resource ON final_region_functions (resource_id);
CREATE INDEX IF NOT EXISTS idx_final_function_batch ON final_region_functions (batch_id);
CREATE INDEX IF NOT EXISTS idx_final_function_atlas ON final_region_functions (source_atlas);
CREATE INDEX IF NOT EXISTS idx_final_function_gran ON final_region_functions (granularity_level);
CREATE INDEX IF NOT EXISTS idx_final_function_term ON final_region_functions (function_term);
CREATE INDEX IF NOT EXISTS idx_final_function_category ON final_region_functions (function_category);
CREATE INDEX IF NOT EXISTS idx_final_function_status ON final_region_functions (final_status);

CREATE INDEX IF NOT EXISTS idx_final_circuit_mirror ON final_region_circuits (source_mirror_circuit_id);
CREATE INDEX IF NOT EXISTS idx_final_circuit_resource ON final_region_circuits (resource_id);
CREATE INDEX IF NOT EXISTS idx_final_circuit_batch ON final_region_circuits (batch_id);
CREATE INDEX IF NOT EXISTS idx_final_circuit_atlas ON final_region_circuits (source_atlas);
CREATE INDEX IF NOT EXISTS idx_final_circuit_gran ON final_region_circuits (granularity_level);
CREATE INDEX IF NOT EXISTS idx_final_circuit_name ON final_region_circuits (circuit_name);
CREATE INDEX IF NOT EXISTS idx_final_circuit_type ON final_region_circuits (circuit_type);
CREATE INDEX IF NOT EXISTS idx_final_circuit_status ON final_region_circuits (final_status);

CREATE INDEX IF NOT EXISTS idx_final_circuit_region_circuit ON final_circuit_regions (final_circuit_id);
CREATE INDEX IF NOT EXISTS idx_final_circuit_region_region ON final_circuit_regions (region_candidate_id);
CREATE INDEX IF NOT EXISTS idx_final_circuit_region_role ON final_circuit_regions (role);

CREATE INDEX IF NOT EXISTS idx_final_triple_mirror ON final_kg_triples (source_mirror_triple_id);
CREATE INDEX IF NOT EXISTS idx_final_triple_subject ON final_kg_triples (subject_type, subject_id);
CREATE INDEX IF NOT EXISTS idx_final_triple_object ON final_kg_triples (object_type, object_id);
CREATE INDEX IF NOT EXISTS idx_final_triple_predicate ON final_kg_triples (predicate);
CREATE INDEX IF NOT EXISTS idx_final_triple_resource ON final_kg_triples (resource_id);
CREATE INDEX IF NOT EXISTS idx_final_triple_batch ON final_kg_triples (batch_id);
CREATE INDEX IF NOT EXISTS idx_final_triple_atlas ON final_kg_triples (source_atlas);
CREATE INDEX IF NOT EXISTS idx_final_triple_gran ON final_kg_triples (granularity_level);
CREATE INDEX IF NOT EXISTS idx_final_triple_status ON final_kg_triples (final_status);

CREATE INDEX IF NOT EXISTS idx_final_evidence_target ON final_evidence_records (evidence_target_type, evidence_target_id);
CREATE INDEX IF NOT EXISTS idx_final_evidence_mirror ON final_evidence_records (source_mirror_evidence_id);
CREATE INDEX IF NOT EXISTS idx_final_evidence_resource ON final_evidence_records (resource_id);
CREATE INDEX IF NOT EXISTS idx_final_evidence_batch ON final_evidence_records (batch_id);
CREATE INDEX IF NOT EXISTS idx_final_evidence_promotion ON final_evidence_records (promotion_record_id);

CREATE INDEX IF NOT EXISTS idx_mirror_promotion_runs_status ON mirror_promotion_runs (status);
CREATE INDEX IF NOT EXISTS idx_mirror_promotion_runs_resource ON mirror_promotion_runs (resource_id);
CREATE INDEX IF NOT EXISTS idx_mirror_promotion_runs_batch ON mirror_promotion_runs (batch_id);
CREATE INDEX IF NOT EXISTS idx_mirror_promotion_runs_atlas ON mirror_promotion_runs (source_atlas);
CREATE INDEX IF NOT EXISTS idx_mirror_promotion_runs_gran ON mirror_promotion_runs (granularity_level);
CREATE INDEX IF NOT EXISTS idx_mirror_promotion_runs_created ON mirror_promotion_runs (created_at);

CREATE INDEX IF NOT EXISTS idx_mirror_promotion_records_run ON mirror_promotion_records (run_id);
CREATE INDEX IF NOT EXISTS idx_mirror_promotion_records_target ON mirror_promotion_records (target_type, mirror_target_id);
CREATE INDEX IF NOT EXISTS idx_mirror_promotion_records_final ON mirror_promotion_records (final_target_type, final_target_id);
CREATE INDEX IF NOT EXISTS idx_mirror_promotion_records_review ON mirror_promotion_records (review_record_id);
CREATE INDEX IF NOT EXISTS idx_mirror_promotion_records_status ON mirror_promotion_records (status);
CREATE INDEX IF NOT EXISTS idx_mirror_promotion_records_resource ON mirror_promotion_records (resource_id);
CREATE INDEX IF NOT EXISTS idx_mirror_promotion_records_batch ON mirror_promotion_records (batch_id);
CREATE INDEX IF NOT EXISTS idx_mirror_promotion_records_atlas ON mirror_promotion_records (source_atlas);

DROP TRIGGER IF EXISTS trg_final_region_connections_updated_at ON final_region_connections;
CREATE TRIGGER trg_final_region_connections_updated_at
    BEFORE UPDATE ON final_region_connections
    FOR EACH ROW EXECUTE FUNCTION update_updated_at();

DROP TRIGGER IF EXISTS trg_final_region_functions_updated_at ON final_region_functions;
CREATE TRIGGER trg_final_region_functions_updated_at
    BEFORE UPDATE ON final_region_functions
    FOR EACH ROW EXECUTE FUNCTION update_updated_at();

DROP TRIGGER IF EXISTS trg_final_region_circuits_updated_at ON final_region_circuits;
CREATE TRIGGER trg_final_region_circuits_updated_at
    BEFORE UPDATE ON final_region_circuits
    FOR EACH ROW EXECUTE FUNCTION update_updated_at();

DROP TRIGGER IF EXISTS trg_final_kg_triples_updated_at ON final_kg_triples;
CREATE TRIGGER trg_final_kg_triples_updated_at
    BEFORE UPDATE ON final_kg_triples
    FOR EACH ROW EXECUTE FUNCTION update_updated_at();
