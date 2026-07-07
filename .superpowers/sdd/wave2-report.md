# Wave 2 Report: Mirror KG Service Merge + Evidence Dedup

**Status: DONE**

## Summary

Implemented 3 gaps in `mirror_kg_service.py`:

### Task A: Confidence-based merge for functions (DONE)

- Added `_find_existing_function_for_merge()` — queries `MirrorRegionFunction` filtering out rejected/failed/promoted records, matches on `region_candidate_id + function_category + relation_type + atlas + granularity`, then iterates results checking `function_term.strip().lower()` equality.
- Modified `create_mirror_function()` to call the merge helper before creating. If existing found with `pending`/`needs_review` status and new confidence > existing confidence, updates fields in-place and records merge provenance. Otherwise creates fresh.

### Task B: Confidence-based merge for circuits (DONE)

- Added `_find_existing_circuit_for_merge()` — queries `MirrorRegionCircuit` filtering out rejected/failed/promoted records, matches on `circuit_type + atlas + granularity`, then checks `circuit_name` (case-insensitive) and region set equality (compares `MirrorCircuitRegion` rows via `_load_circuit_regions`).
- Modified `create_mirror_circuit()` to call the merge helper before creating. Same confidence-based merge pattern as connections and functions. Preserves circuit_region creation for fresh records.

### Task C: Evidence dedup (DONE)

- Added `_evidence_text_hash()` helper computing SHA-256 hex digest of evidence text.
- Added `_find_existing_evidence()` — queries `MirrorEvidenceRecord` by `evidence_target_type` + `evidence_target_id`, then matches `_evidence_text_hash()` to find identical evidence text.
- Modified `create_mirror_evidence()` to check for existing match before INSERT. If found, returns existing record without creating duplicate.

### Test Updates

Fixed 5 unit tests that broke due to new find functions (same patching pattern used by existing `test_create_mirror_connection_service_defaults`):
- `test_create_mirror_function_service` — patch `_find_existing_function_for_merge`
- `test_create_mirror_circuit_with_regions` — patch `_find_existing_circuit_for_merge`
- `test_create_mirror_evidence_service` — patch `_find_existing_evidence`
- `test_llm_item_to_mirror_function_success` — patch `_find_existing_function_for_merge`
- `test_create_circuit_for_membership_fixtures` — patch `_find_existing_circuit_for_merge`

### Verification

- `tests/ -q --ignore=tests/test_llm_field_completion.py -k "mirror or evidence"`: **225 passed, 1 failed** (the 1 failure is pre-existing `test_mirror_kg_service_still_works` — confirmed broken on original code via `git stash`)
- Full suite (excluding pre-existing LLM projection test failures): **947 passed, 9 skipped, 1 pre-existing failure**
- **Zero regressions** introduced.

### Files Changed

| File | Change |
|------|--------|
| `backend/app/services/mirror_kg_service.py` | Added 3 merge helpers + evidence dedup, modified 3 create functions |
| `backend/tests/test_mirror_kg_schema.py` | Added `patch` wrappers for 4 tests |
| `backend/tests/test_mirror_macro_clinical_schema.py` | Added `patch` import + wrapper for 1 test |
