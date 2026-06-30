-- 036: Add region name columns to mirror_region_connections
-- Manual execution only; the app does not auto-run this file.

ALTER TABLE mirror_region_connections
  ADD COLUMN IF NOT EXISTS source_region_name_cn VARCHAR(256),
  ADD COLUMN IF NOT EXISTS source_region_name_en VARCHAR(256),
  ADD COLUMN IF NOT EXISTS target_region_name_cn VARCHAR(256),
  ADD COLUMN IF NOT EXISTS target_region_name_en VARCHAR(256);

COMMENT ON COLUMN mirror_region_connections.source_region_name_cn IS 'Source brain region Chinese name at extraction time';
COMMENT ON COLUMN mirror_region_connections.source_region_name_en IS 'Source brain region English name at extraction time';
COMMENT ON COLUMN mirror_region_connections.target_region_name_cn IS 'Target brain region Chinese name at extraction time';
COMMENT ON COLUMN mirror_region_connections.target_region_name_en IS 'Target brain region English name at extraction time';

-- Backfill existing rows from candidate_brain_regions
UPDATE mirror_region_connections mc
SET
  source_region_name_cn = src.cn_name,
  source_region_name_en = src.en_name,
  target_region_name_cn = tgt.cn_name,
  target_region_name_en = tgt.en_name
FROM candidate_brain_regions src, candidate_brain_regions tgt
WHERE mc.source_region_candidate_id = src.id
  AND mc.target_region_candidate_id = tgt.id
  AND mc.source_region_name_cn IS NULL;
