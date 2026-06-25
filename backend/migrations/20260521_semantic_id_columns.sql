-- Semantic ID migration phase 1: audit map + cn_description / remark on KG tables.
-- PK type change (UUID -> VARCHAR) is applied by semantic_id_migration_service.py.

CREATE TABLE IF NOT EXISTS kg_id_migration_map (
    id              BIGSERIAL PRIMARY KEY,
    table_name      VARCHAR(128) NOT NULL,
    old_id          VARCHAR(128) NOT NULL,
    new_id          VARCHAR(128) NOT NULL,
    migrated_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    remark          TEXT,
    UNIQUE (table_name, old_id)
);

CREATE INDEX IF NOT EXISTS idx_kg_id_migration_map_new ON kg_id_migration_map (table_name, new_id);

-- Workbench coarse / atlas tables
ALTER TABLE evidence_sources ADD COLUMN IF NOT EXISTS cn_description TEXT;
ALTER TABLE evidence_sources ADD COLUMN IF NOT EXISTS remark TEXT;
ALTER TABLE evidence_items ADD COLUMN IF NOT EXISTS cn_description TEXT;
ALTER TABLE evidence_items ADD COLUMN IF NOT EXISTS remark TEXT;
ALTER TABLE coarse_brain_regions ADD COLUMN IF NOT EXISTS cn_description TEXT;
ALTER TABLE coarse_brain_regions ADD COLUMN IF NOT EXISTS remark TEXT;
ALTER TABLE coarse_brain_region_aliases ADD COLUMN IF NOT EXISTS cn_description TEXT;
ALTER TABLE coarse_brain_region_aliases ADD COLUMN IF NOT EXISTS remark TEXT;
ALTER TABLE coarse_brain_region_relations ADD COLUMN IF NOT EXISTS cn_description TEXT;
ALTER TABLE coarse_brain_region_relations ADD COLUMN IF NOT EXISTS remark TEXT;
ALTER TABLE atlas_resources ADD COLUMN IF NOT EXISTS cn_description TEXT;
ALTER TABLE atlas_resources ADD COLUMN IF NOT EXISTS remark TEXT;
ALTER TABLE atlas_labels ADD COLUMN IF NOT EXISTS cn_description TEXT;
ALTER TABLE atlas_labels ADD COLUMN IF NOT EXISTS remark TEXT;
ALTER TABLE coarse_region_atlas_mappings ADD COLUMN IF NOT EXISTS cn_description TEXT;
ALTER TABLE coarse_region_atlas_mappings ADD COLUMN IF NOT EXISTS remark TEXT;
ALTER TABLE coarse_region_connections ADD COLUMN IF NOT EXISTS cn_description TEXT;
ALTER TABLE coarse_region_connections ADD COLUMN IF NOT EXISTS remark TEXT;
ALTER TABLE coarse_circuits ADD COLUMN IF NOT EXISTS cn_description TEXT;
ALTER TABLE coarse_circuits ADD COLUMN IF NOT EXISTS remark TEXT;
ALTER TABLE coarse_circuit_steps ADD COLUMN IF NOT EXISTS cn_description TEXT;
ALTER TABLE coarse_circuit_steps ADD COLUMN IF NOT EXISTS remark TEXT;
ALTER TABLE coarse_region_function_annotations ADD COLUMN IF NOT EXISTS cn_description TEXT;
ALTER TABLE coarse_region_function_annotations ADD COLUMN IF NOT EXISTS remark TEXT;

-- Formal final_* tables (same DB or candidate DB — run on each DB that has them)
ALTER TABLE final_evidence_sources ADD COLUMN IF NOT EXISTS cn_description TEXT;
ALTER TABLE final_evidence_sources ADD COLUMN IF NOT EXISTS remark TEXT;
ALTER TABLE final_evidence_items ADD COLUMN IF NOT EXISTS cn_description TEXT;
ALTER TABLE final_evidence_items ADD COLUMN IF NOT EXISTS remark TEXT;
ALTER TABLE final_coarse_brain_regions ADD COLUMN IF NOT EXISTS cn_description TEXT;
ALTER TABLE final_coarse_brain_regions ADD COLUMN IF NOT EXISTS remark TEXT;
ALTER TABLE final_coarse_brain_region_aliases ADD COLUMN IF NOT EXISTS cn_description TEXT;
ALTER TABLE final_coarse_brain_region_aliases ADD COLUMN IF NOT EXISTS remark TEXT;
ALTER TABLE final_coarse_brain_region_relations ADD COLUMN IF NOT EXISTS cn_description TEXT;
ALTER TABLE final_coarse_brain_region_relations ADD COLUMN IF NOT EXISTS remark TEXT;
ALTER TABLE final_atlas_resources ADD COLUMN IF NOT EXISTS cn_description TEXT;
ALTER TABLE final_atlas_resources ADD COLUMN IF NOT EXISTS remark TEXT;
ALTER TABLE final_atlas_labels ADD COLUMN IF NOT EXISTS cn_description TEXT;
ALTER TABLE final_atlas_labels ADD COLUMN IF NOT EXISTS remark TEXT;
ALTER TABLE final_coarse_region_atlas_mappings ADD COLUMN IF NOT EXISTS cn_description TEXT;
ALTER TABLE final_coarse_region_atlas_mappings ADD COLUMN IF NOT EXISTS remark TEXT;
ALTER TABLE final_coarse_region_connections ADD COLUMN IF NOT EXISTS cn_description TEXT;
ALTER TABLE final_coarse_region_connections ADD COLUMN IF NOT EXISTS remark TEXT;
ALTER TABLE final_coarse_circuits ADD COLUMN IF NOT EXISTS cn_description TEXT;
ALTER TABLE final_coarse_circuits ADD COLUMN IF NOT EXISTS remark TEXT;
ALTER TABLE final_coarse_circuit_steps ADD COLUMN IF NOT EXISTS cn_description TEXT;
ALTER TABLE final_coarse_circuit_steps ADD COLUMN IF NOT EXISTS remark TEXT;
ALTER TABLE final_coarse_region_function_annotations ADD COLUMN IF NOT EXISTS cn_description TEXT;
ALTER TABLE final_coarse_region_function_annotations ADD COLUMN IF NOT EXISTS remark TEXT;
