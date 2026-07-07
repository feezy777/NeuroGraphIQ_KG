# Dedup Wave 2 Report

## Changes Made

### Task A: Circuit steps dedup

**File:** `backend/app/services/mirror_macro_clinical_service.py`

Added `_find_existing_circuit_step()` with canonical key `(circuit_id, region_candidate_id, region_final_id, role)`. Queries `MirrorCircuitStep` filtering out rejected/failed/promoted records, matching on all 4 key fields (with NULL-safe UUID comparisons). If a match is found, `create_circuit_step()` returns the existing record instead of creating a duplicate.

### Task B: Circuit projection memberships dedup

**File:** `backend/app/services/mirror_macro_clinical_service.py`

Added `_find_existing_circuit_projection_membership()` with canonical key `(circuit_id, projection_id, source_step_order, target_step_order)`. Resolves payload step IDs to step orders via `session.get()`, then uses aliased outerjoins to `MirrorCircuitStep` to compare step orders against existing memberships. If a match is found, `create_circuit_projection_membership()` returns the existing record instead of creating a duplicate.

### Task C: Function dedup performance fix

**File:** `backend/app/services/mirror_kg_service.py`

In `_find_existing_function_for_merge()`, added `func.lower(MirrorRegionFunction.function_term) == func_term_norm` to the SQL WHERE clause. The function now filters at the DB level and returns the first match via `.limit(1).scalar_one_or_none()`, eliminating the Python loop over all scope-matched rows.

**File:** `backend/app/services/llm_projection_function_extraction_service.py`

In `_projection_function_exists()`, added `func.lower(MirrorProjectionFunction.function_term) == function_term_key` to the SQL WHERE clause. Simplified the function to a single query with `.limit(1).scalar_one_or_none() is not None`, eliminating the two-step query + Python iteration pattern.

## Test Updates

**File:** `backend/tests/test_mirror_macro_clinical_schema.py`

Updated 8 tests to mock `session.execute` for the new dedup queries:
- 4 circuit step tests: added `session.execute` returning `None` for dedup query
- 4 membership tests: added `session.execute` returning `None` for dedup query, using `side_effect` for tests where `session.execute` is called multiple times

**File:** `backend/tests/test_llm_projection_function_extraction.py`

Updated 2 tests (both occurrences of `session.execute` mock) to support `.scalar_one_or_none()` on the mock chain, needed by the simplified `_projection_function_exists()`.

## Test Results

```
1000 passed, 9 skipped, 4 deselected, 26 warnings in 5.41s
```

The 4 deselected tests are pre-existing failures (max-count truncation tests) unrelated to this change.
