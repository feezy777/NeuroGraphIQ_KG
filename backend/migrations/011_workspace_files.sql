-- Migration 011: Workspace Public Files
-- Adds workspace_files table for staging files without resource_id binding.
-- Also adds source_workspace_file_id to resource_files to track attach provenance.
--
-- Workspace files CANNOT directly enter import_batch_files.
-- They must go through attach-to-resource → resource_files first.
-- Does NOT reference final_*, kg_*, raw_aal3_region_labels, candidate_brain_regions.
--
-- Manual execution only; application does NOT auto-run this file.

BEGIN;

-- ─── 1. workspace_files ───────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS workspace_files (
    id                   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    workspace_file_code  TEXT UNIQUE,
    original_filename    TEXT NOT NULL,
    safe_filename        TEXT NOT NULL,
    stored_filename      TEXT NOT NULL,
    storage_path         TEXT NOT NULL,
    file_ext             TEXT NOT NULL DEFAULT '',
    mime_type            TEXT,
    file_type            TEXT NOT NULL DEFAULT 'other',
    file_role            TEXT NOT NULL DEFAULT 'unknown',
    file_size_bytes      BIGINT NOT NULL DEFAULT 0,
    sha256               TEXT NOT NULL,
    status               TEXT NOT NULL DEFAULT 'active'
                             CHECK (status IN ('active', 'archived', 'deleted')),
    description          TEXT,
    remark               TEXT,
    uploaded_by          TEXT,
    source               TEXT NOT NULL DEFAULT 'workspace_upload',
    created_at           TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at           TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    archived_at          TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_workspace_files_sha256     ON workspace_files(sha256);
CREATE INDEX IF NOT EXISTS idx_workspace_files_status     ON workspace_files(status);
CREATE INDEX IF NOT EXISTS idx_workspace_files_file_type  ON workspace_files(file_type);
CREATE INDEX IF NOT EXISTS idx_workspace_files_file_role  ON workspace_files(file_role);
CREATE INDEX IF NOT EXISTS idx_workspace_files_created_at ON workspace_files(created_at);

-- ─── 2. Add source_workspace_file_id to resource_files ───────────────────────
-- Tracks which workspace file a resource_file was attached from.
-- Nullable: existing resource_files rows are unaffected.
ALTER TABLE resource_files
    ADD COLUMN IF NOT EXISTS source_workspace_file_id UUID
        REFERENCES workspace_files(id) ON DELETE SET NULL;

CREATE INDEX IF NOT EXISTS idx_resource_files_workspace_source
    ON resource_files(source_workspace_file_id)
    WHERE source_workspace_file_id IS NOT NULL;

COMMIT;
