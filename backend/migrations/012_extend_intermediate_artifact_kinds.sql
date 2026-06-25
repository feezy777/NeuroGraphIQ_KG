-- Migration 012: Extend intermediate artifact_kind and source_format enums
-- Adds spreadsheet_workbook, macro_region_table, pdf_metadata, document_metadata.
-- Does NOT modify migrations 001–011.

BEGIN;

ALTER TABLE file_intermediate_artifacts
    DROP CONSTRAINT IF EXISTS file_intermediate_artifacts_artifact_kind_check;

ALTER TABLE file_intermediate_artifacts
    ADD CONSTRAINT file_intermediate_artifacts_artifact_kind_check
    CHECK (artifact_kind IN (
        'label_table', 'text_document', 'json_document', 'tabular_data',
        'ontology_document', 'image_metadata', 'nifti_metadata',
        'connectivity_matrix_metadata', 'binary_metadata', 'unsupported',
        'spreadsheet_workbook', 'macro_region_table', 'pdf_metadata', 'document_metadata'
    ));

ALTER TABLE file_intermediate_artifacts
    DROP CONSTRAINT IF EXISTS file_intermediate_artifacts_source_format_check;

ALTER TABLE file_intermediate_artifacts
    ADD CONSTRAINT file_intermediate_artifacts_source_format_check
    CHECK (source_format IS NULL OR source_format IN (
        'xml', 'json', 'csv', 'tsv', 'txt', 'nifti',
        'image', 'pdf', 'ontology', 'binary', 'unknown',
        'xlsx', 'xls', 'document'
    ));

COMMIT;
