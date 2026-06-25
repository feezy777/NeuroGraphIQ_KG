-- One-off cleanup: remove all import batches + pipeline downstream data in e2e DB.
-- Also removes test/e2e/debug atlas_resources and their files.
-- Manual run: psql -h 127.0.0.1 -U postgres -d neurographiq_kg_v3_mvp1_e2e -f backend/scripts/cleanup_test_batches.sql

BEGIN;

DELETE FROM promotion_records;
DELETE FROM final_brain_regions;
DELETE FROM candidate_review_records;
DELETE FROM candidate_rule_validation_results;
DELETE FROM rule_validation_runs;
DELETE FROM candidate_llm_extractions;
DELETE FROM candidate_brain_regions;
DELETE FROM candidate_generation_runs;
DELETE FROM raw_macro96_region_rows;
DELETE FROM raw_aal3_region_labels;
DELETE FROM raw_parse_runs;

DELETE FROM import_batch_events;
DELETE FROM import_batch_files;
DELETE FROM import_batches;

DELETE FROM file_intermediate_artifacts;
DELETE FROM file_normalization_runs;

DELETE FROM resource_files
WHERE resource_id IN (
  SELECT id FROM atlas_resources
  WHERE resource_code LIKE '%e2e%'
     OR resource_code LIKE 'test\_%' ESCAPE '\'
     OR resource_code LIKE 'debug\_%' ESCAPE '\'
);

DELETE FROM atlas_resources
WHERE resource_code LIKE '%e2e%'
   OR resource_code LIKE 'test\_%' ESCAPE '\'
   OR resource_code LIKE 'debug\_%' ESCAPE '\';

COMMIT;
