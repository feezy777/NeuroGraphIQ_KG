-- Add granularity_level to raw and candidate tables for global granularity isolation
-- Populated from atlas_resources.granularity_level via resource_id

-- 1. candidate_brain_regions
ALTER TABLE candidate_brain_regions ADD COLUMN IF NOT EXISTS granularity_level VARCHAR(64);

UPDATE candidate_brain_regions c
SET granularity_level = r.granularity_level
FROM atlas_resources r
WHERE c.resource_id = r.id AND c.granularity_level IS NULL;

-- 2. raw_macro96_region_rows
ALTER TABLE raw_macro96_region_rows ADD COLUMN IF NOT EXISTS granularity_level VARCHAR(64);

UPDATE raw_macro96_region_rows m
SET granularity_level = r.granularity_level
FROM atlas_resources r
WHERE m.resource_id = r.id AND m.granularity_level IS NULL;
