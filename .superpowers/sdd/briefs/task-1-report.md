# Task 1 Report: Fix 1-3 — audit 递增 + retry + error_message 传播

## Status: DONE

## Changes Made

All 6 surgical changes in `backend/app/services/llm_connection_extraction_service.py`:

1. **Location 1 (transport_error retry)**: Changed `break` to `continue` at line 1262 — transport errors now retry instead of aborting the pack.
2. **Location 2 (empty_response retry)**: Changed `break` to `continue` at line 1284 — empty responses now retry instead of aborting the pack.
3. **Location 3 (transport/empty audit counters)**: Added `audit.processed_pack_count += 1` and `audit.failed_pack_count += 1` before the else-branch return (transport/empty path).
4. **Location 4 (parse_error audit counters)**: Added `audit.processed_pack_count += 1` and `audit.failed_pack_count += 1` in the parse_error block.
5. **Location 5 (success audit counters)**: Added `audit.processed_pack_count += 1` with conditional `audit.succeeded_pack_count += 1` / `audit.no_connection_pack_count += 1` before the success return.
6. **Location 6 (error_message propagation)**: Added `run.error_message = item.error_message` after `item.error_message` assignment in the semantic failure block.

## Test Results

- `pytest tests/test_connection_parse_diagnostics.py tests/test_debug_single_pack_pipeline.py -q` — **15 passed** (no regressions)
- `pytest tests/test_llm_composite_workflow.py -q` — **23 passed** (no regressions)

## Concerns

None. All 6 edits were exact code replacements as specified in the brief. All existing tests continue to pass.
