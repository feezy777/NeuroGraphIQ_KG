# Dedup Wave 1 Report: 3 Dedup Gaps Fixed

**Status:** DONE
**Date:** 2026-06-30

---

## Task A: Mirror triples dedup

**File modified:** `backend/app/services/mirror_kg_service.py`

- Added `_find_existing_triple_for_merge(session, payload)` — queries `MirrorKgTriple` filtering out rejected/failed/promoted/superseded, matching on all 6 canonical key fields (`subject_type`, `subject_id`, `predicate`, `object_type`, `object_id`, `triple_scope`) with NULL-safe UUID comparison.
- Modified `create_mirror_triple()` to call the find function before creating. If existing found, returns existing (skip). Triples are deterministic — no confidence merge needed.
- `llm_to_mirror_service.py`'s `create_mirror_triples_from_llm_item()` already goes through `create_mirror_triple`, so it benefits automatically.

## Task B: Mirror projection functions dedup

**File modified:** `backend/app/services/mirror_macro_clinical_service.py`

- Added `_find_existing_projection_function_for_merge(session, payload)` — matches on canonical key `(projection_id, function_term_key, function_category, relation_type)` with case-insensitive `function_term` comparison, excluding rejected/failed/promoted records.
- Modified `create_projection_function()`: if existing found and new `confidence > old confidence`, updates fields (confidence, evidence_text, uncertainty_reason, llm_run_id, llm_item_id, mirror_status). Otherwise returns existing (skip).

## Task C: Mirror circuit functions dedup

**File modified:** `backend/app/services/mirror_macro_clinical_service.py`

- Added `_find_existing_circuit_function_for_merge(session, payload)` — matches on canonical key `(circuit_id, function_term_key, function_domain, function_role, effect_type)` with case-insensitive `function_term_en` comparison, excluding rejected/failed/promoted records.
- Modified `create_circuit_function()`: if existing found and new `confidence > old confidence`, updates all function fields. Otherwise returns existing (skip).

**File modified:** `backend/app/services/llm_circuit_function_extraction_service.py`

- Added `_circuit_function_merge_key(circuit_id, fn)` — canonical key helper with effect_type.
- Added `_session_seen` set to `upsert_mirror_circuit_function()` — prevents duplicates within a single LLM response before flush is visible.
- Updated call site to create and pass `session_seen` set per function batch.

## Test Files Modified

- `tests/test_mirror_kg_schema.py` — patched `_find_existing_triple_for_merge` in `test_create_mirror_triple_service`.
- `tests/test_mirror_macro_clinical_schema.py` — patched `_find_existing_projection_function_for_merge` in `test_create_projection_function_service` and `_find_existing_connection_for_merge` in `test_mirror_kg_service_still_works`.

## Verification

```
tests/test_mirror_kg_schema.py + tests/test_mirror_macro_clinical_schema.py — 43 passed, 2 warnings
Full suite — 1078 passed, 8 failed (all 8 pre-existing, confirmed on clean master)
```
