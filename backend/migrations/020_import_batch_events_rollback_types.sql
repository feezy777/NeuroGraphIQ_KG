-- Extend import_batch_events event_type CHECK with rollback lifecycle events.
-- Manual execution only; application does NOT auto-run this file.
--
-- Depends on: 003..017 (cumulative event types).

ALTER TABLE import_batch_events
    DROP CONSTRAINT IF EXISTS chk_import_batch_events_type;

ALTER TABLE import_batch_events
    ADD CONSTRAINT chk_import_batch_events_type CHECK (
        event_type IN (
            -- 003 originals
            'created',
            'file_attached',
            'status_changed',
            'cancelled',
            'failed',
            'completed',
            'note',

            -- 004 parse lifecycle (AAL3 / generic raw parse)
            'parse_started',
            'parse_succeeded',
            'parse_failed',

            -- 005 candidate generation lifecycle
            'candidate_generation_started',
            'candidate_generation_succeeded',
            'candidate_generation_failed',

            -- 006 rule validation lifecycle
            'rule_validation_started',
            'rule_validation_succeeded',
            'rule_validation_failed',

            -- 017 Macro96 parse lifecycle
            'parse_macro96_started',
            'parse_macro96_succeeded',
            'parse_macro96_failed',

            -- 020 rollback lifecycle (new)
            'rollback_started',
            'rollback_succeeded',
            'rollback_failed'
        )
    );
