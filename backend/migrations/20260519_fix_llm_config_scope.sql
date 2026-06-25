-- Revision: 20260519_fix_llm_config_scope
-- Repair llm_configs rows violating chk_global_or_task (do not drop the constraint).

-- Orphan rows created as "global" but stored with is_global=false and task_id=null
UPDATE llm_configs
SET is_global = TRUE,
    updated_at = NOW()
WHERE task_id IS NULL
  AND is_global = FALSE;

-- Rows linked to a task but incorrectly marked global
UPDATE llm_configs
SET is_global = FALSE,
    updated_at = NOW()
WHERE task_id IS NOT NULL
  AND is_global = TRUE;
