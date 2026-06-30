-- 037: Add 'cancelled' to llm_extraction_items.status CHECK constraint
-- The cleanup service sets items to 'cancelled' during composite workflow cancel.
-- The original constraint only allowed: created, running, succeeded, failed, skipped, needs_review.

ALTER TABLE llm_extraction_items
    DROP CONSTRAINT IF EXISTS chk_llm_extraction_item_status;

ALTER TABLE llm_extraction_items
    ADD CONSTRAINT chk_llm_extraction_item_status CHECK (
        status IN ('created', 'running', 'succeeded', 'failed', 'skipped', 'needs_review', 'cancelled')
    );
