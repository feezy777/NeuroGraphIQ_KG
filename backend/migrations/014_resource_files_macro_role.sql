-- Extend resource_files.file_role CHECK to include Macro96 pool source role.
-- Manual execution only; application does NOT auto-run this file.

ALTER TABLE resource_files DROP CONSTRAINT IF EXISTS chk_resource_files_file_role;

ALTER TABLE resource_files ADD CONSTRAINT chk_resource_files_file_role CHECK (
    file_role IN (
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
