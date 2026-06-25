-- MVP 2 Step 8.13 — Extend mirror_rule_validation_results.target_type for macro_clinical objects
-- Manual execution only; application does NOT auto-run this file.
--
-- Depends on: 023_mirror_kg_rule_validation.sql, 026_mirror_macro_clinical_alignment_schema.sql,
--             027_mirror_circuit_projection_cross_validation.sql

ALTER TABLE mirror_rule_validation_results
    DROP CONSTRAINT IF EXISTS chk_mirror_validation_results_target_type;

ALTER TABLE mirror_rule_validation_results
    ADD CONSTRAINT chk_mirror_validation_results_target_type CHECK (
        target_type IN (
            'connection',
            'function',
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
