-- Add canonical_id column to brain region tables (meaningful ID, not replacing PK)
ALTER TABLE candidate_brain_regions ADD COLUMN IF NOT EXISTS canonical_id VARCHAR(256);
CREATE INDEX IF NOT EXISTS idx_candidate_br_canonical ON candidate_brain_regions(canonical_id);

-- Auto-populate from atlas + label / region name
-- Pattern: {atlas}_{label_or_name}
UPDATE candidate_brain_regions
SET canonical_id = COALESCE(
    source_atlas || '_' || COALESCE(label_code, std_name, en_name, cn_name),
    source_atlas || '_' || COALESCE(std_name, en_name, cn_name),
    'unknown'
)
WHERE canonical_id IS NULL;

-- Add canonical_id to atlas_labels for reference
ALTER TABLE atlas_labels ADD COLUMN IF NOT EXISTS canonical_id VARCHAR(256);
UPDATE atlas_labels
SET canonical_id = atlas_name || '_' || label_name
WHERE canonical_id IS NULL;
