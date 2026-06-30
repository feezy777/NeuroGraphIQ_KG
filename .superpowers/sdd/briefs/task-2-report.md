# Task 2 Report: build_execution_summary compact 参数

## Status
DONE

## Commit Hash
`7ea90ad`

## Files Changed
- `backend/app/services/llm_connection_parse_diagnostics.py` — added `_strip_prompt_preview` helper, short-circuit in `compact_pack_summaries`, `compact: bool = True` param on `build_execution_summary`
- `backend/app/services/llm_connection_extraction_service.py` — pass `compact=False` at final call site (line 1680)

## Changes Summary

1. **`_strip_prompt_preview` helper** added before `compact_pack_summaries` — returns a copy of a trace dict without the `prompt_preview` key.

2. **Short-circuit in `compact_pack_summaries`** — when `len(finalized) <= max_recent`, returns all finalized traces as-is without the filtering/merging logic. This avoids unnecessary processing when all traces fit within the compact window.

3. **`compact: bool = True` parameter on `build_execution_summary`**:
   - `compact=True` (default): identical to previous behavior — calls `compact_pack_summaries`, recalculates counts from pack_traces (needed because compacted summaries may be truncated).
   - `compact=False`: keeps all pack traces but strips `prompt_preview` from each via `_strip_prompt_preview`. Trusts audit object fields directly (`failed_pack_count`, `processed_pack_count`, `succeeded_pack_count`, `provider_success_count`) instead of recalculating — these are accurate after Task 1's fix. Only `response_received_count` and `in_flight_pack_count` are computed from traces since they are not audit fields.

4. **Final call site updated** — `build_execution_summary(audit, pack_traces, compact=False, extra=...)` at line 1680 of `extraction_service.py` preserves full history (with prompt_preview stripped) for the final summary stored on the run and item.

## Test Results

- `tests/test_connection_parse_diagnostics.py`: 8 passed, 0 failed — no regressions
- `tests/test_llm_composite_workflow.py`: 23 passed, 0 failed — no regressions

## Design Decisions

- The `compact` parameter name intentionally shadows the old local variable (`compact = compact_pack_summaries(...)`) — this is safe because the old local variable was only used within the function body and the new parameter serves the same purpose at a higher level.
- When `compact=False`, `failed_pack_count` is not recomputed from traces; the audit's value is trusted. This is correct because the audit tracks `parse_error_count` and `schema_error_count` incrementally during execution and is accurate after Task 1's fix.
