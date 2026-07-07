# Wave 1 Report: JSON Parse Retry for Function & Circuit Extraction

**Status:** DONE

## Changes Made

### Task A: Function extraction — `llm_function_extraction_service.py`
- **File:** `backend/app/services/llm_function_extraction_service.py`
- Replaced the single-attempt `try/except` block (lines 628-638) with a retry loop (`max_provider_attempts = 2`) that catches `json.JSONDecodeError`, `ValueError`, and `TypeError`.
- On failure of the first parse attempt, the provider `complete_json()` call is re-invoked before the second parse attempt.
- On persistent failure, the item/run are marked `failed` with a message stating the number of attempts and the last error.
- `import json` was already present at line 9.

### Task B: Circuit extraction — `llm_circuit_extraction_service.py`
- **File:** `backend/app/services/llm_circuit_extraction_service.py`
- Applied the identical retry pattern using `parse_circuit_completion_response()`.
- Same `max_provider_attempts = 2` loop structure, re-calling `provider.complete_json(...)` on retry.
- `import json` was already present at line 9.

## Verification
- `tests/test_llm_function_extraction.py` — passed
- `tests/test_llm_circuit_extraction.py` — passed
- **Total: 33 passed, 2 warnings** (pre-existing FastAPI deprecation warnings only, no test failures)
