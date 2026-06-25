-- Migration 010: File Normalization Runs + Intermediate Artifacts
-- Creates two tables for unified intermediate state management in the File Center.
-- Does NOT reference final_*, kg_*, raw_aal3_region_labels, candidate_brain_regions.

BEGIN;

-- ─── 1. file_normalization_runs ───────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS file_normalization_runs (
    id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    run_code          TEXT UNIQUE NOT NULL,
    resource_id       UUID NOT NULL REFERENCES atlas_resources(id) ON DELETE RESTRICT,
    file_id           UUID NOT NULL REFERENCES resource_files(id) ON DELETE RESTRICT,
    file_sha256       TEXT,
    original_filename TEXT,
    file_type         TEXT,
    file_role         TEXT,
    normalizer_key    TEXT NOT NULL,
    normalizer_version TEXT NOT NULL DEFAULT 'v1',
    status            TEXT NOT NULL CHECK (status IN (
                          'created', 'running', 'succeeded', 'failed', 'partial_failed'
                      )),
    artifact_count    INTEGER NOT NULL DEFAULT 0,
    warning_count     INTEGER NOT NULL DEFAULT 0,
    error_message     TEXT,
    started_at        TIMESTAMPTZ,
    finished_at       TIMESTAMPTZ,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at        TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_file_norm_runs_file_id        ON file_normalization_runs(file_id);
CREATE INDEX IF NOT EXISTS idx_file_norm_runs_resource_id    ON file_normalization_runs(resource_id);
CREATE INDEX IF NOT EXISTS idx_file_norm_runs_status         ON file_normalization_runs(status);
CREATE INDEX IF NOT EXISTS idx_file_norm_runs_normalizer_key ON file_normalization_runs(normalizer_key);
CREATE INDEX IF NOT EXISTS idx_file_norm_runs_created_at     ON file_normalization_runs(created_at);

-- ─── 2. file_intermediate_artifacts ──────────────────────────────────────────
CREATE TABLE IF NOT EXISTS file_intermediate_artifacts (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    run_id           UUID NOT NULL REFERENCES file_normalization_runs(id) ON DELETE CASCADE,
    resource_id      UUID NOT NULL,
    file_id          UUID NOT NULL,
    artifact_key     TEXT NOT NULL,
    artifact_kind    TEXT NOT NULL CHECK (artifact_kind IN (
                         'label_table', 'text_document', 'json_document', 'tabular_data',
                         'ontology_document', 'image_metadata', 'nifti_metadata',
                         'connectivity_matrix_metadata', 'binary_metadata', 'unsupported'
                     )),
    schema_version   TEXT NOT NULL DEFAULT 'intermediate_v1',
    source_format    TEXT CHECK (source_format IN (
                         'xml', 'json', 'csv', 'tsv', 'txt', 'nifti',
                         'image', 'pdf', 'ontology', 'binary', 'unknown'
                     )),
    row_count        INTEGER,
    content_jsonb    JSONB,
    preview_jsonb    JSONB,
    metadata_jsonb   JSONB,
    warnings_jsonb   JSONB,
    status           TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'archived', 'failed')),
    created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at       TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_file_interm_art_file_id       ON file_intermediate_artifacts(file_id);
CREATE INDEX IF NOT EXISTS idx_file_interm_art_resource_id   ON file_intermediate_artifacts(resource_id);
CREATE INDEX IF NOT EXISTS idx_file_interm_art_run_id        ON file_intermediate_artifacts(run_id);
CREATE INDEX IF NOT EXISTS idx_file_interm_art_artifact_kind ON file_intermediate_artifacts(artifact_kind);
CREATE INDEX IF NOT EXISTS idx_file_interm_art_status        ON file_intermediate_artifacts(status);
CREATE INDEX IF NOT EXISTS idx_file_interm_art_created_at    ON file_intermediate_artifacts(created_at);

COMMIT;
