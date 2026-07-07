-- 040_model_tier_mirror_status.sql
-- Add model-tier mirror_status values: llm_v4_pro, llm_reasoner, llm_kimi

ALTER TABLE mirror_region_connections DROP CONSTRAINT IF EXISTS chk_mirror_connection_mirror_status;
ALTER TABLE mirror_region_connections ADD CONSTRAINT chk_mirror_connection_mirror_status CHECK (
    mirror_status = ANY (ARRAY[
        'llm_suggested', 'llm_v4_pro', 'llm_reasoner', 'llm_kimi',
        'rule_checked', 'human_review_pending', 'human_approved',
        'human_rejected', 'promoted_to_final', 'superseded'
    ])
);

ALTER TABLE mirror_region_functions DROP CONSTRAINT IF EXISTS chk_mirror_function_mirror_status;
ALTER TABLE mirror_region_functions ADD CONSTRAINT chk_mirror_function_mirror_status CHECK (
    mirror_status = ANY (ARRAY[
        'llm_suggested', 'llm_v4_pro', 'llm_reasoner', 'llm_kimi',
        'rule_checked', 'human_review_pending', 'human_approved',
        'human_rejected', 'promoted_to_final', 'superseded'
    ])
);

ALTER TABLE mirror_region_circuits DROP CONSTRAINT IF EXISTS chk_mirror_circuit_mirror_status;
ALTER TABLE mirror_region_circuits ADD CONSTRAINT chk_mirror_circuit_mirror_status CHECK (
    mirror_status = ANY (ARRAY[
        'llm_suggested', 'llm_v4_pro', 'llm_reasoner', 'llm_kimi',
        'rule_checked', 'human_review_pending', 'human_approved',
        'human_rejected', 'promoted_to_final', 'superseded'
    ])
);

ALTER TABLE mirror_kg_triples DROP CONSTRAINT IF EXISTS chk_mirror_triple_mirror_status;
ALTER TABLE mirror_kg_triples ADD CONSTRAINT chk_mirror_triple_mirror_status CHECK (
    mirror_status = ANY (ARRAY[
        'llm_suggested', 'llm_v4_pro', 'llm_reasoner', 'llm_kimi',
        'rule_checked', 'human_review_pending', 'human_approved',
        'human_rejected', 'promoted_to_final', 'superseded'
    ])
);

ALTER TABLE mirror_circuit_steps DROP CONSTRAINT IF EXISTS chk_mirror_circuit_step_mirror_status;
ALTER TABLE mirror_circuit_steps ADD CONSTRAINT chk_mirror_circuit_step_mirror_status CHECK (
    mirror_status = ANY (ARRAY[
        'llm_suggested', 'llm_v4_pro', 'llm_reasoner', 'llm_kimi',
        'rule_checked', 'human_review_pending', 'human_approved',
        'human_rejected', 'promoted_to_final', 'superseded'
    ])
);

ALTER TABLE mirror_projection_functions DROP CONSTRAINT IF EXISTS chk_mirror_projection_function_mirror_status;
ALTER TABLE mirror_projection_functions ADD CONSTRAINT chk_mirror_projection_function_mirror_status CHECK (
    mirror_status = ANY (ARRAY[
        'llm_suggested', 'llm_v4_pro', 'llm_reasoner', 'llm_kimi',
        'rule_checked', 'human_review_pending', 'human_approved',
        'human_rejected', 'promoted_to_final', 'superseded'
    ])
);

ALTER TABLE mirror_circuit_projection_memberships DROP CONSTRAINT IF EXISTS chk_mirror_membership_mirror_status;
ALTER TABLE mirror_circuit_projection_memberships ADD CONSTRAINT chk_mirror_membership_mirror_status CHECK (
    mirror_status = ANY (ARRAY[
        'llm_suggested', 'llm_v4_pro', 'llm_reasoner', 'llm_kimi',
        'rule_checked', 'human_review_pending', 'human_approved',
        'human_rejected', 'promoted_to_final', 'superseded'
    ])
);

ALTER TABLE mirror_circuit_functions DROP CONSTRAINT IF EXISTS chk_mirror_circuit_function_mirror_status;
ALTER TABLE mirror_circuit_functions ADD CONSTRAINT chk_mirror_circuit_function_mirror_status CHECK (
    mirror_status = ANY (ARRAY[
        'llm_suggested', 'llm_v4_pro', 'llm_reasoner', 'llm_kimi',
        'rule_checked', 'human_review_pending', 'human_approved',
        'human_rejected', 'promoted_to_final', 'superseded'
    ])
);
