-- 039: extraction_mode support for composite workflows + usage history

ALTER TABLE llm_usage_history ADD COLUMN IF NOT EXISTS extraction_mode VARCHAR(32);

COMMENT ON COLUMN llm_usage_history.extraction_mode IS
    'extraction_mode from the composite workflow request: balanced, exhaustive, or region_centered';
