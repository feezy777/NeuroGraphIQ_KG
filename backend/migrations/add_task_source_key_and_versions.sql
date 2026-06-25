-- Add source_key to import_tasks and version snapshots for rollback.
-- Run against workbench DB: psql -U postgres -d neurographiq_kg_v3_wb -f add_task_source_key_and_versions.sql

ALTER TABLE import_tasks
    ADD COLUMN IF NOT EXISTS source_key VARCHAR(100);

CREATE INDEX IF NOT EXISTS idx_import_tasks_source_key ON import_tasks(source_key);

-- Backfill from file_registry.source_code where possible
UPDATE import_tasks t
SET source_key = f.source_code
FROM file_registry f
WHERE t.input_file_id = f.id
  AND t.source_key IS NULL
  AND f.source_code IS NOT NULL;

-- Default legacy rows without file to aal3 parser context
UPDATE import_tasks
SET source_key = 'aal3'
WHERE source_key IS NULL AND resource_type = 'aal3';

CREATE TABLE IF NOT EXISTS import_task_versions (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    task_id         UUID NOT NULL REFERENCES import_tasks(id) ON DELETE CASCADE,
    version_number  INTEGER NOT NULL,
    label           VARCHAR(200),
    status_at_save  import_status,
    snapshot        JSONB NOT NULL,
    region_count    INTEGER DEFAULT 0,
    connection_count INTEGER DEFAULT 0,
    term_count      INTEGER DEFAULT 0,
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (task_id, version_number)
);

CREATE INDEX IF NOT EXISTS idx_import_task_versions_task_id ON import_task_versions(task_id);
