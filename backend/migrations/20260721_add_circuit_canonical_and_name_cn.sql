-- Migration: Add canonical_start_region_id, canonical_end_region_id, name_cn to mirror_region_circuits
-- Date: 2026-07-21
-- Purpose: Enable circuit-to-final-region mapping (canonical IDs) and Chinese name support.

BEGIN;

-- Add columns to mirror_region_circuits
ALTER TABLE mirror_region_circuits
    ADD COLUMN IF NOT EXISTS name_cn VARCHAR(512),
    ADD COLUMN IF NOT EXISTS canonical_start_region_id UUID,
    ADD COLUMN IF NOT EXISTS canonical_end_region_id UUID;

-- Foreign key constraints (optional — NULL allowed, cascade on delete)
ALTER TABLE mirror_region_circuits
    ADD CONSTRAINT fk_circuit_canonical_start_region
        FOREIGN KEY (canonical_start_region_id)
        REFERENCES final_brain_regions(id)
        ON DELETE SET NULL,
    ADD CONSTRAINT fk_circuit_canonical_end_region
        FOREIGN KEY (canonical_end_region_id)
        REFERENCES final_brain_regions(id)
        ON DELETE SET NULL;

-- Index for lookups
CREATE INDEX IF NOT EXISTS idx_circuit_canonical_start ON mirror_region_circuits(canonical_start_region_id);
CREATE INDEX IF NOT EXISTS idx_circuit_canonical_end ON mirror_region_circuits(canonical_end_region_id);
CREATE INDEX IF NOT EXISTS idx_circuit_name_cn ON mirror_region_circuits(name_cn);

COMMIT;
