-- 034: Add region_name_cn / region_name_en to mirror_region_functions
-- Manual execution only; the app does not auto-run this file.

ALTER TABLE mirror_region_functions
  ADD COLUMN IF NOT EXISTS region_name_cn VARCHAR(256),
  ADD COLUMN IF NOT EXISTS region_name_en VARCHAR(256);

COMMENT ON COLUMN mirror_region_functions.region_name_cn IS 'Candidate brain region Chinese name at extraction time';
COMMENT ON COLUMN mirror_region_functions.region_name_en IS 'Candidate brain region English name at extraction time';
