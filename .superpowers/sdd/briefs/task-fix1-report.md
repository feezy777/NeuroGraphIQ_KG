# Task Fix Report: `consecutive_parse_failures` Reset Bug

## Bug

In `backend/app/services/llm_connection_extraction_service.py`, the `_process_one_pack` closure (around original line 1367) contained `consecutive_parse_failures = 0` **without a `nonlocal` declaration**. This created a new local variable inside the closure scope that shadowed the outer variable. Consequently:

- The outer `consecutive_parse_failures` variable was **never reset to 0**.
- The fail-fast mechanism accumulated parse errors across the **entire run** instead of resetting after a successful pack.
- With the default threshold of 5, any 5 parse errors anywhere in the run would trigger fail-fast — not 5 *consecutive* parse errors.

## Changes Made

### Change 1: Removed useless local assignment inside closure
- **File**: `backend/app/services/llm_connection_extraction_service.py`
- **What**: Deleted `consecutive_parse_failures = 0` (was inside `_process_one_pack` closure)
- **Why**: This line had no effect on the outer variable (no `nonlocal`), only created a throwaway local.

### Change 2: Fixed accumulation logic to enforce consecutive semantics
- **File**: `backend/app/services/llm_connection_extraction_service.py`
- **Before**: `consecutive_parse_failures += _pf`
- **After**:
  ```python
  if _pf > 0:
      consecutive_parse_failures += _pf
  else:
      consecutive_parse_failures = 0
  ```
- **Why**: When a pack succeeds (`_pf == 0`), the counter now resets to 0, restoring the intended "consecutive" semantics.

## Verification

- Ran `pytest tests/test_connection_parse_diagnostics.py tests/test_debug_single_pack_pipeline.py -q`
- **Result**: 17 passed, 0 failed
