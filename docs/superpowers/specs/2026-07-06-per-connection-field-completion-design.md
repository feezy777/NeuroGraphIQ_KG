# Per-Connection Field Completion Redesign

**Date**: 2026-07-06  
**Status**: Approved  
**Model**: One LLM call per connection, all 11 fields at once

## Problem

Current field completion uses per-field batching (5 connections per field per LLM call), resulting in ~11,000 LLM calls for 5,124 connections. Each call only fills one field, ignoring cross-field consistency.

## Design

### Prompt Template

- **System**: neuroscientist annotating brain connectivity
- **User per connection**: source/target names, atlas, current metadata → LLM infers all 11 fields
- **Output**: flat JSON `{"projection_type": "...", "directionality": "...", ...}`

### Execution Model

| Item | Old | New |
|------|-----|-----|
| Unit | Per field, 5 connections/batch | Per connection, 11 fields |
| LLM calls | ~11,000 | 5,124 |
| Fields/call | 1 | 11 |
| Est. time | 6-16 hours | ~4 hours |

### Architecture

```
execute_field_completion_background()
  → _execute_field_completion_core()
    → apply_deterministic_fields()  (unchanged)
    → execute_per_connection_fields()  ← NEW: replaces execute_batched_llm_fields
       └── For each connection:
           1. Build prompt with existing field values as context
           2. One LLM call → all 11 fields
           3. Apply each field via apply_field_update
           4. Commit progress after each connection
    → finalize
```

### Unchanged

- `apply_deterministic_fields` — deterministic field resolution
- `apply_field_update` — write logic (overlay + direct)
- `overwrite_with_review` policy — overwrite existing values
- Progress tracking — `summary_json` updates after each connection
- Frontend defaults — `all_enrichable_fields` + `overwrite_with_review`
