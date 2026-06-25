-- Macro96 Candidate Generation — relax source_raw_label_id FK, add source_raw_table
-- Manual execution only; application does NOT auto-run this file.
--
-- Context:
--   candidate_brain_regions.source_raw_label_id previously FK'd only to
--   raw_aal3_region_labels. Macro96 candidates reference raw_macro96_region_rows.id.
--   Drop the FK; add source_raw_table to record which raw table the UUID came from.
--
-- Does NOT reference final_* or kg_* tables.
-- Does NOT generate mapping, rule validation, review, or promotion.

-- Drop AAL3-only FK on source_raw_label_id
ALTER TABLE candidate_brain_regions
    DROP CONSTRAINT IF EXISTS candidate_brain_regions_source_raw_label_id_fkey;

-- Add source_raw_table to distinguish raw origin
ALTER TABLE candidate_brain_regions
    ADD COLUMN IF NOT EXISTS source_raw_table VARCHAR(128);

-- Backfill existing AAL3 candidates
UPDATE candidate_brain_regions
SET source_raw_table = 'raw_aal3_region_labels'
WHERE source_raw_table IS NULL;

-- Enforce NOT NULL after backfill
ALTER TABLE candidate_brain_regions
    ALTER COLUMN source_raw_table SET NOT NULL;

-- Default for new rows (AAL3 path still sets explicitly; Macro96 sets raw_macro96_region_rows)
ALTER TABLE candidate_brain_regions
    ALTER COLUMN source_raw_table SET DEFAULT 'raw_aal3_region_labels';
