-- MVP 2 Step 8.15 — Final macro_clinical schema and controlled promotion
-- Manual execution only; application does NOT auto-run this file.
--
-- Depends on: 025, 026, 029
-- Writes final_* in workbench DB only. Does NOT write kg_* or external NeuroGraphIQ_KG_V3.

-- Extend legacy final tables with macro_clinical provenance columns (idempotent)
ALTER TABLE final_region_circuits ADD COLUMN IF NOT EXISTS final_uid TEXT;
ALTER TABLE final_region_circuits ADD COLUMN IF NOT EXISTS source_mirror_type TEXT DEFAULT 'circuit';
ALTER TABLE final_region_circuits ADD COLUMN IF NOT EXISTS promotion_run_id UUID;
ALTER TABLE final_region_circuits ADD COLUMN IF NOT EXISTS validation_summary_json JSONB NOT NULL DEFAULT '{}'::jsonb;
ALTER TABLE final_region_circuits ADD COLUMN IF NOT EXISTS review_summary_json JSONB NOT NULL DEFAULT '{}'::jsonb;
ALTER TABLE final_region_circuits ADD COLUMN IF NOT EXISTS cross_validation_summary_json JSONB NOT NULL DEFAULT '{}'::jsonb;
ALTER TABLE final_region_circuits ADD COLUMN IF NOT EXISTS dual_model_summary_json JSONB NOT NULL DEFAULT '{}'::jsonb;
ALTER TABLE final_region_circuits ADD COLUMN IF NOT EXISTS provenance_json JSONB NOT NULL DEFAULT '{}'::jsonb;

ALTER TABLE final_region_functions ADD COLUMN IF NOT EXISTS final_uid TEXT;
ALTER TABLE final_region_functions ADD COLUMN IF NOT EXISTS source_mirror_type TEXT DEFAULT 'region_function';
ALTER TABLE final_region_functions ADD COLUMN IF NOT EXISTS promotion_run_id UUID;
ALTER TABLE final_region_functions ADD COLUMN IF NOT EXISTS validation_summary_json JSONB NOT NULL DEFAULT '{}'::jsonb;
ALTER TABLE final_region_functions ADD COLUMN IF NOT EXISTS review_summary_json JSONB NOT NULL DEFAULT '{}'::jsonb;
ALTER TABLE final_region_functions ADD COLUMN IF NOT EXISTS cross_validation_summary_json JSONB NOT NULL DEFAULT '{}'::jsonb;
ALTER TABLE final_region_functions ADD COLUMN IF NOT EXISTS dual_model_summary_json JSONB NOT NULL DEFAULT '{}'::jsonb;
ALTER TABLE final_region_functions ADD COLUMN IF NOT EXISTS provenance_json JSONB NOT NULL DEFAULT '{}'::jsonb;

ALTER TABLE final_kg_triples ADD COLUMN IF NOT EXISTS final_uid TEXT;
ALTER TABLE final_kg_triples ADD COLUMN IF NOT EXISTS source_mirror_type TEXT DEFAULT 'triple';
ALTER TABLE final_kg_triples ADD COLUMN IF NOT EXISTS promotion_run_id UUID;
ALTER TABLE final_kg_triples ADD COLUMN IF NOT EXISTS validation_summary_json JSONB NOT NULL DEFAULT '{}'::jsonb;
ALTER TABLE final_kg_triples ADD COLUMN IF NOT EXISTS review_summary_json JSONB NOT NULL DEFAULT '{}'::jsonb;
ALTER TABLE final_kg_triples ADD COLUMN IF NOT EXISTS cross_validation_summary_json JSONB NOT NULL DEFAULT '{}'::jsonb;
ALTER TABLE final_kg_triples ADD COLUMN IF NOT EXISTS dual_model_summary_json JSONB NOT NULL DEFAULT '{}'::jsonb;
ALTER TABLE final_kg_triples ADD COLUMN IF NOT EXISTS provenance_json JSONB NOT NULL DEFAULT '{}'::jsonb;
ALTER TABLE final_kg_triples ADD COLUMN IF NOT EXISTS source_final_projection_id UUID;
ALTER TABLE final_kg_triples ADD COLUMN IF NOT EXISTS source_final_projection_function_id UUID;
ALTER TABLE final_kg_triples ADD COLUMN IF NOT EXISTS source_final_membership_id UUID;

ALTER TABLE final_evidence_records ADD COLUMN IF NOT EXISTS final_uid TEXT;
ALTER TABLE final_evidence_records ADD COLUMN IF NOT EXISTS source_mirror_type TEXT DEFAULT 'evidence';
ALTER TABLE final_evidence_records ADD COLUMN IF NOT EXISTS mirror_target_type TEXT;
ALTER TABLE final_evidence_records ADD COLUMN IF NOT EXISTS mirror_target_id UUID;
ALTER TABLE final_evidence_records ADD COLUMN IF NOT EXISTS final_target_type TEXT;
ALTER TABLE final_evidence_records ADD COLUMN IF NOT EXISTS final_target_id UUID;
ALTER TABLE final_evidence_records ADD COLUMN IF NOT EXISTS promotion_run_id UUID;
ALTER TABLE final_evidence_records ADD COLUMN IF NOT EXISTS provenance_json JSONB NOT NULL DEFAULT '{}'::jsonb;

CREATE UNIQUE INDEX IF NOT EXISTS uq_final_region_circuits_final_uid ON final_region_circuits (final_uid) WHERE final_uid IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS uq_final_region_functions_final_uid ON final_region_functions (final_uid) WHERE final_uid IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS uq_final_kg_triples_final_uid ON final_kg_triples (final_uid) WHERE final_uid IS NOT NULL;

-- Macro clinical projection table (distinct from legacy final_region_connections)
CREATE TABLE IF NOT EXISTS final_projections (
    id                          UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    final_uid                   TEXT UNIQUE NOT NULL,
    source_mirror_type          TEXT NOT NULL DEFAULT 'projection',
    source_mirror_id            UUID NOT NULL REFERENCES mirror_region_connections(id) ON DELETE RESTRICT,
    promotion_run_id            UUID,
    promotion_record_id         UUID,
    resource_id                 UUID REFERENCES atlas_resources(id) ON DELETE SET NULL,
    batch_id                    UUID REFERENCES import_batches(id) ON DELETE SET NULL,
    source_atlas                TEXT NOT NULL,
    source_version              TEXT,
    granularity_level           TEXT NOT NULL,
    granularity_family          TEXT,
    source_region_candidate_id  UUID REFERENCES candidate_brain_regions(id) ON DELETE SET NULL,
    target_region_candidate_id  UUID REFERENCES candidate_brain_regions(id) ON DELETE SET NULL,
    projection_type             TEXT NOT NULL,
    directionality              TEXT NOT NULL DEFAULT 'unknown',
    strength                    TEXT,
    modality                    TEXT,
    confidence                  NUMERIC,
    evidence_text               TEXT,
    uncertainty_reason          TEXT,
    validation_summary_json     JSONB NOT NULL DEFAULT '{}'::jsonb,
    review_summary_json         JSONB NOT NULL DEFAULT '{}'::jsonb,
    cross_validation_summary_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    dual_model_summary_json     JSONB NOT NULL DEFAULT '{}'::jsonb,
    provenance_json             JSONB NOT NULL DEFAULT '{}'::jsonb,
    final_status                TEXT NOT NULL DEFAULT 'active',
    created_at                  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at                  TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT chk_final_projection_status CHECK (final_status IN ('active', 'deprecated', 'superseded'))
);

CREATE TABLE IF NOT EXISTS final_circuit_steps (
    id                          UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    final_uid                   TEXT UNIQUE NOT NULL,
    source_mirror_type          TEXT NOT NULL DEFAULT 'circuit_step',
    source_mirror_id            UUID NOT NULL REFERENCES mirror_circuit_steps(id) ON DELETE RESTRICT,
    promotion_run_id            UUID,
    promotion_record_id         UUID,
    final_circuit_id            UUID NOT NULL REFERENCES final_region_circuits(id) ON DELETE CASCADE,
    mirror_circuit_id           UUID NOT NULL REFERENCES mirror_region_circuits(id) ON DELETE SET NULL,
    region_candidate_id         UUID REFERENCES candidate_brain_regions(id) ON DELETE SET NULL,
    resource_id                 UUID REFERENCES atlas_resources(id) ON DELETE SET NULL,
    batch_id                    UUID REFERENCES import_batches(id) ON DELETE SET NULL,
    source_atlas                TEXT NOT NULL,
    source_version              TEXT,
    granularity_level           TEXT NOT NULL,
    granularity_family          TEXT,
    step_order                  INTEGER NOT NULL,
    step_name                   TEXT NOT NULL,
    step_type                   TEXT NOT NULL DEFAULT 'unknown',
    role                        TEXT NOT NULL DEFAULT 'unknown',
    description                 TEXT,
    confidence                  NUMERIC,
    evidence_text               TEXT,
    uncertainty_reason          TEXT,
    validation_summary_json     JSONB NOT NULL DEFAULT '{}'::jsonb,
    review_summary_json         JSONB NOT NULL DEFAULT '{}'::jsonb,
    dual_model_summary_json     JSONB NOT NULL DEFAULT '{}'::jsonb,
    provenance_json             JSONB NOT NULL DEFAULT '{}'::jsonb,
    final_status                TEXT NOT NULL DEFAULT 'active',
    created_at                  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at                  TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT chk_final_circuit_step_status CHECK (final_status IN ('active', 'deprecated', 'superseded')),
    CONSTRAINT uq_final_circuit_steps_circuit_order UNIQUE (final_circuit_id, step_order)
);

CREATE TABLE IF NOT EXISTS final_circuit_functions (
    id                          UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    final_uid                   TEXT UNIQUE NOT NULL,
    source_mirror_type          TEXT NOT NULL,
    source_mirror_id            UUID NOT NULL,
    promotion_run_id            UUID,
    promotion_record_id         UUID,
    final_circuit_id            UUID NOT NULL REFERENCES final_region_circuits(id) ON DELETE CASCADE,
    mirror_circuit_id           UUID REFERENCES mirror_region_circuits(id) ON DELETE SET NULL,
    resource_id                 UUID REFERENCES atlas_resources(id) ON DELETE SET NULL,
    batch_id                    UUID REFERENCES import_batches(id) ON DELETE SET NULL,
    source_atlas                TEXT NOT NULL,
    source_version              TEXT,
    granularity_level           TEXT NOT NULL,
    granularity_family          TEXT,
    function_term               TEXT NOT NULL,
    function_category           TEXT NOT NULL DEFAULT 'unknown',
    relation_type               TEXT NOT NULL DEFAULT 'associated_with',
    confidence                  NUMERIC,
    evidence_text               TEXT,
    uncertainty_reason          TEXT,
    validation_summary_json     JSONB NOT NULL DEFAULT '{}'::jsonb,
    review_summary_json         JSONB NOT NULL DEFAULT '{}'::jsonb,
    dual_model_summary_json     JSONB NOT NULL DEFAULT '{}'::jsonb,
    provenance_json             JSONB NOT NULL DEFAULT '{}'::jsonb,
    final_status                TEXT NOT NULL DEFAULT 'active',
    created_at                  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at                  TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT chk_final_circuit_function_status CHECK (final_status IN ('active', 'deprecated', 'superseded'))
);

CREATE TABLE IF NOT EXISTS final_projection_functions (
    id                          UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    final_uid                   TEXT UNIQUE NOT NULL,
    source_mirror_type          TEXT NOT NULL DEFAULT 'projection_function',
    source_mirror_id            UUID NOT NULL REFERENCES mirror_projection_functions(id) ON DELETE RESTRICT,
    promotion_run_id            UUID,
    promotion_record_id         UUID,
    final_projection_id         UUID NOT NULL REFERENCES final_projections(id) ON DELETE CASCADE,
    mirror_projection_id        UUID NOT NULL REFERENCES mirror_region_connections(id) ON DELETE SET NULL,
    resource_id                 UUID REFERENCES atlas_resources(id) ON DELETE SET NULL,
    batch_id                    UUID REFERENCES import_batches(id) ON DELETE SET NULL,
    source_atlas                TEXT NOT NULL,
    source_version              TEXT,
    granularity_level           TEXT NOT NULL,
    granularity_family          TEXT,
    function_term               TEXT NOT NULL,
    function_category           TEXT NOT NULL DEFAULT 'unknown',
    relation_type               TEXT NOT NULL DEFAULT 'associated_with',
    confidence                  NUMERIC,
    evidence_text               TEXT,
    uncertainty_reason          TEXT,
    validation_summary_json     JSONB NOT NULL DEFAULT '{}'::jsonb,
    review_summary_json         JSONB NOT NULL DEFAULT '{}'::jsonb,
    dual_model_summary_json     JSONB NOT NULL DEFAULT '{}'::jsonb,
    provenance_json             JSONB NOT NULL DEFAULT '{}'::jsonb,
    final_status                TEXT NOT NULL DEFAULT 'active',
    created_at                  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at                  TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT chk_final_projection_function_status CHECK (final_status IN ('active', 'deprecated', 'superseded'))
);

CREATE TABLE IF NOT EXISTS final_circuit_projection_memberships (
    id                          UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    final_uid                   TEXT UNIQUE NOT NULL,
    source_mirror_type          TEXT NOT NULL DEFAULT 'circuit_projection_membership',
    source_mirror_id            UUID NOT NULL REFERENCES mirror_circuit_projection_memberships(id) ON DELETE RESTRICT,
    promotion_run_id            UUID,
    promotion_record_id         UUID,
    final_circuit_id            UUID NOT NULL REFERENCES final_region_circuits(id) ON DELETE CASCADE,
    final_projection_id         UUID NOT NULL REFERENCES final_projections(id) ON DELETE CASCADE,
    final_source_step_id        UUID REFERENCES final_circuit_steps(id) ON DELETE SET NULL,
    final_target_step_id        UUID REFERENCES final_circuit_steps(id) ON DELETE SET NULL,
    mirror_circuit_id           UUID NOT NULL REFERENCES mirror_region_circuits(id) ON DELETE SET NULL,
    mirror_projection_id        UUID NOT NULL REFERENCES mirror_region_connections(id) ON DELETE SET NULL,
    mirror_source_step_id       UUID REFERENCES mirror_circuit_steps(id) ON DELETE SET NULL,
    mirror_target_step_id       UUID REFERENCES mirror_circuit_steps(id) ON DELETE SET NULL,
    resource_id                 UUID REFERENCES atlas_resources(id) ON DELETE SET NULL,
    batch_id                    UUID REFERENCES import_batches(id) ON DELETE SET NULL,
    source_atlas                TEXT NOT NULL,
    source_version              TEXT,
    granularity_level           TEXT NOT NULL,
    granularity_family          TEXT,
    step_order                  INTEGER,
    role_in_circuit             TEXT NOT NULL DEFAULT 'unknown',
    source_method               TEXT NOT NULL DEFAULT 'unknown',
    verification_status         TEXT NOT NULL DEFAULT 'unverified',
    confidence                  NUMERIC,
    evidence_text               TEXT,
    uncertainty_reason          TEXT,
    validation_summary_json     JSONB NOT NULL DEFAULT '{}'::jsonb,
    review_summary_json         JSONB NOT NULL DEFAULT '{}'::jsonb,
    cross_validation_summary_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    dual_model_summary_json     JSONB NOT NULL DEFAULT '{}'::jsonb,
    provenance_json             JSONB NOT NULL DEFAULT '{}'::jsonb,
    final_status                TEXT NOT NULL DEFAULT 'active',
    created_at                  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at                  TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT chk_final_membership_status CHECK (final_status IN ('active', 'deprecated', 'superseded'))
);

CREATE TABLE IF NOT EXISTS final_macro_clinical_promotion_runs (
    id                  UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    scope_json          JSONB NOT NULL DEFAULT '{}'::jsonb,
    target_types        TEXT[] NOT NULL DEFAULT ARRAY[]::TEXT[],
    dry_run             BOOLEAN NOT NULL DEFAULT false,
    confirm_text        TEXT,
    status              TEXT NOT NULL DEFAULT 'created',
    candidate_count     INTEGER NOT NULL DEFAULT 0,
    eligible_count      INTEGER NOT NULL DEFAULT 0,
    promoted_count      INTEGER NOT NULL DEFAULT 0,
    skipped_count       INTEGER NOT NULL DEFAULT 0,
    failed_count        INTEGER NOT NULL DEFAULT 0,
    blocked_count       INTEGER NOT NULL DEFAULT 0,
    duplicate_count     INTEGER NOT NULL DEFAULT 0,
    risk_flag_count     INTEGER NOT NULL DEFAULT 0,
    error_message       TEXT,
    started_at          TIMESTAMPTZ,
    finished_at         TIMESTAMPTZ,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    created_by          TEXT,
    CONSTRAINT chk_final_mc_promotion_run_status CHECK (
        status IN ('created', 'running', 'succeeded', 'partially_succeeded', 'failed', 'cancelled')
    )
);

CREATE TABLE IF NOT EXISTS final_macro_clinical_promotion_records (
    id                          UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    run_id                      UUID NOT NULL REFERENCES final_macro_clinical_promotion_runs(id) ON DELETE CASCADE,
    target_type                 TEXT NOT NULL,
    mirror_object_id            UUID NOT NULL,
    final_table                 TEXT,
    final_object_id             UUID,
    action                      TEXT NOT NULL,
    reason                      TEXT,
    eligibility_status          TEXT NOT NULL,
    risk_flags                  TEXT[] NOT NULL DEFAULT ARRAY[]::TEXT[],
    validation_summary_json     JSONB NOT NULL DEFAULT '{}'::jsonb,
    review_summary_json         JSONB NOT NULL DEFAULT '{}'::jsonb,
    cross_validation_summary_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    dual_model_summary_json     JSONB NOT NULL DEFAULT '{}'::jsonb,
    duplicate_of_final_id       UUID,
    error_message               TEXT,
    created_at                  TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT chk_final_mc_promotion_record_action CHECK (
        action IN ('promoted', 'skipped', 'blocked', 'duplicate', 'failed', 'dry_run_preview')
    )
);

CREATE INDEX IF NOT EXISTS idx_final_projections_mirror ON final_projections (source_mirror_id);
CREATE INDEX IF NOT EXISTS idx_final_projections_atlas ON final_projections (source_atlas, granularity_level);
CREATE INDEX IF NOT EXISTS idx_final_circuit_steps_mirror ON final_circuit_steps (source_mirror_id);
CREATE INDEX IF NOT EXISTS idx_final_circuit_steps_circuit ON final_circuit_steps (final_circuit_id);
CREATE INDEX IF NOT EXISTS idx_final_projection_functions_mirror ON final_projection_functions (source_mirror_id);
CREATE INDEX IF NOT EXISTS idx_final_memberships_mirror ON final_circuit_projection_memberships (source_mirror_id);
CREATE INDEX IF NOT EXISTS idx_final_mc_promotion_runs_status ON final_macro_clinical_promotion_runs (status);
CREATE INDEX IF NOT EXISTS idx_final_mc_promotion_records_run ON final_macro_clinical_promotion_records (run_id);
CREATE INDEX IF NOT EXISTS idx_final_mc_promotion_records_mirror ON final_macro_clinical_promotion_records (target_type, mirror_object_id);
