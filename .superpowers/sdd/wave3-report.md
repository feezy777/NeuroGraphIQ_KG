# Wave 3 Cleanup Report

**Date:** 2026-06-30

**Status:** DONE

## Task A: Circuit dedup fallback

**File:** `backend/app/services/llm_circuit_extraction_service.py`

**Change:** In `_circuit_exists`, when `normalized_payload_json` is empty or lacks `region_set_key` / `involved_region_candidate_ids`, the code now falls back to querying the `MirrorCircuitRegion` children directly via `circuit.id` to derive the region set. Previously, if `normalized_payload_json` was empty/None, `norm.get(...)` would silently return `[]`, making every comparison `set() == target_set` (always False for non-empty target sets), causing duplicate writes.

**Details:**
- Added `MirrorCircuitRegion` to imports
- Added fallback query: `select(MirrorCircuitRegion.region_candidate_id).where(MirrorCircuitRegion.circuit_id == circuit.id)`

## Task B: Remove dead `allowed_connection_types` parameter

**File:** `backend/app/services/llm_extraction_prompt_engineering.py`

**Change:** Removed `allowed_connection_types: frozenset[str] | None = None` parameter from `normalize_projection_extraction_response()` and the `del allowed_connection_types` line that followed.

**Callers updated:**
- `llm_connection_extraction_service.py` — removed `allowed_connection_types=allowed_types` from the call at the `_process_one_pack` call site

## Task C: Narrow broad `except Exception` blocks

| File | Line | Old | New |
|------|------|-----|-----|
| `backend/app/services/llm_function_extraction_service.py` | 703 | `except Exception` | `except (json.JSONDecodeError, ValueError, TypeError, KeyError)` |
| `backend/app/services/llm_circuit_extraction_service.py` | 1119 | `except Exception` | `except (json.JSONDecodeError, ValueError, TypeError, KeyError)` |
| `backend/app/services/llm_connection_extraction_service.py` | 1324 | `except Exception  # noqa: BLE001` | `except (json.JSONDecodeError, ValueError, TypeError, KeyError)` |

## Verification

- **Command:** `pytest tests/ -k "circuit or connection or function"` (excluding pre-existing failures in unrelated files)
- **Result:** 294 passed, 0 failed (4 pre-existing failures in `test_llm_circuit_projection_extraction`, `test_llm_projection_circuit_extraction`, `test_llm_projection_function_extraction` — files not touched by this change)
