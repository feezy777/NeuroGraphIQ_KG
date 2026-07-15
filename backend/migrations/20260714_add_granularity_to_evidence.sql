-- Add granularity_level to mirror_evidence_records for global granularity isolation
-- Populated from atlas_resources.granularity_level via resource_id

ALTER TABLE mirror_evidence_records ADD COLUMN IF NOT EXISTS granularity_level TEXT;

UPDATE mirror_evidence_records e
SET granularity_level = r.granularity_level
FROM atlas_resources r
WHERE e.resource_id = r.id AND e.granularity_level IS NULL;

CREATE INDEX IF NOT EXISTS idx_mirror_evidence_granularity
    ON mirror_evidence_records (granularity_level);
