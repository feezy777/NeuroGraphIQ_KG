-- MVP 2 Step 8.14 — Extend mirror_human_review_records for macro_clinical targets and signal actions
-- Manual execution only; application does NOT auto-run this file.
--
-- Depends on: 024_mirror_kg_human_review.sql, 026/027/028 macro_clinical migrations

ALTER TABLE mirror_human_review_records
    DROP CONSTRAINT IF EXISTS chk_mirror_review_target_type;

ALTER TABLE mirror_human_review_records
    ADD CONSTRAINT chk_mirror_review_target_type CHECK (
        target_type IN (
            'connection',
            'function',
            'region_function',
            'circuit',
            'triple',
            'projection',
            'circuit_step',
            'projection_function',
            'circuit_projection_membership',
            'circuit_projection_cross_validation_result',
            'dual_model_verification_result'
        )
    );

ALTER TABLE mirror_human_review_records
    DROP CONSTRAINT IF EXISTS chk_mirror_review_action;

ALTER TABLE mirror_human_review_records
    ADD CONSTRAINT chk_mirror_review_action CHECK (
        action IN (
            'approve',
            'reject',
            'needs_revision',
            'edit',
            'comment',
            'accept_signal',
            'dismiss_signal',
            'flag_for_followup'
        )
    );
