-- Extend import_batch_files.file_role_in_batch CHECK for Macro96 pool source role.
-- Manual execution only; application does NOT auto-run this file.

ALTER TABLE import_batch_files DROP CONSTRAINT IF EXISTS chk_import_batch_files_role;

ALTER TABLE import_batch_files ADD CONSTRAINT chk_import_batch_files_role CHECK (
    file_role_in_batch IN (
        'primary_atlas_volume',
        'label_dictionary',
        'documentation',
        'ontology_source',
        'connectivity_source',
        'evidence_source',
        'metadata',
        'auxiliary',
        'macro_region_pool_source',
        'unknown'
    )
);
