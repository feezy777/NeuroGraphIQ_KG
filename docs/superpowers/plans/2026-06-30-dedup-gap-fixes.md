# Fix All Dedup Gaps

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development.

**Goal:** Add write-time dedup to 5 mirror entity types that currently have none, plus fix function dedup performance.

**Architecture:** Each task adds `_find_existing_*_for_merge()` + modifies `create_*()` in `mirror_kg_service.py` (or `mirror_macro_clinical_service.py`), following the connection/function/circuit merge pattern already established.

**Tech Stack:** Python 3.11+, SQLAlchemy async

## Global Constraints
- All backend tests must pass: `pytest tests/ -q --ignore=tests/test_llm_field_completion.py`
- Follow existing merge pattern: `_find_existing_X_for_merge()` → confidence compare → update-or-create
- Canonical keys must match what LLM extraction in-session dedup uses

---

### Task 1: Mirror triples dedup

**File:** `backend/app/services/mirror_kg_service.py`

Add `_find_existing_triple_for_merge()` near line 852 (`create_mirror_triple`). Canonical key:
```python
(subject_type, str(subject_id), predicate, object_type, str(object_id), triple_scope)
```
Query `MirrorKgTriple` filtering out blocked/failed/rejected. Check match on the 6-field key. If exists: skip (triples are deterministic, no confidence to compare). If not: create.

Also add to the triple creation path in `llm_to_mirror_service.py` (`create_mirror_triples_from_llm_item`).

### Task 2: Mirror projection functions dedup

**File:** `backend/app/services/mirror_macro_clinical_service.py`

Search for `create_projection_function`. Add `_find_existing_projection_function()` with canonical key:
```python
(projection_id, function_term_key, function_category, relation_type)
```
Confidence-based merge (same pattern as mirror_region_functions).

### Task 3: Mirror circuit functions dedup

**File:** `backend/app/services/mirror_macro_clinical_service.py`

Search for `create_circuit_function`. Add `_find_existing_circuit_function()` with canonical key:
```python
(circuit_id, function_term_key, function_domain, function_role, effect_type)
```
Confidence-based merge. Also add `session_seen` set in `llm_circuit_function_extraction_service.py > upsert_mirror_circuit_function`.

### Task 4: Mirror circuit steps dedup

**File:** `backend/app/services/mirror_macro_clinical_service.py`

Search for `create_circuit_step`. Enhance existing `DuplicateStepOrderError` check to also detect same content at different step_order:
```python
(circuit_id, region_candidate_id, region_final_id, role_in_circuit)
```
Add `_find_existing_circuit_step()` and merge.

### Task 5: Mirror circuit projection memberships dedup

**File:** `backend/app/services/mirror_macro_clinical_service.py`

Search for `create_circuit_projection_membership`. Add `_find_existing_membership()` with key:
```python
(circuit_id, projection_id, source_step_order, target_step_order, membership_confidence)
```
Skip if exists (memberships are derived, no confidence merge needed).

### Task 6: Function dedup performance fix

**Files:** `backend/app/services/mirror_kg_service.py`, `backend/app/services/llm_projection_function_extraction_service.py`

In `_function_exists()` and `_projection_function_exists()`: add DB-level filtering for `function_term` using `func.lower(MirrorRegionFunction.function_term) == func.lower(function_term_key)` so the query filters at DB level instead of loading all rows into Python.

### Task 7: Verify full test suite

```bash
cd backend && .venv/Scripts/python.exe -m pytest tests/ -q --ignore=tests/test_llm_field_completion.py
```
All tests must pass.
