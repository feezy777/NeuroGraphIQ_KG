# Fix LLM Response Parsing + DB Write Pipeline Gaps

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Fix 6 gaps in the LLM→parse→normalize→write→visibility pipeline identified during audit.

**Architecture:** Each task fixes one specific gap independently. All changes are in `backend/app/services/`. No new files.

**Tech Stack:** Python 3.11+, SQLAlchemy async, Pydantic v2

## Global Constraints

- All backend tests must pass: `pytest tests/ -q --ignore=tests/test_llm_field_completion.py`
- No new dependencies
- Follow existing patterns (connection extraction is the reference implementation)
- Use `LlmJsonParseError` for JSON parse failures, `json.JSONDecodeError` as base

---

### Task 1: P0 — Add parse retry to function extraction

**File:** `backend/app/services/llm_function_extraction_service.py`

Replace lines 628-636 (single parse attempt with broad `except Exception`):

```python
    elif response.parsed_json is None:
        raw_text = response.raw_text or ""
        parsed = None
        last_error = None
        for attempt in range(max_provider_attempts):
            try:
                parsed = parse_function_completion_response(raw_text)
                if parsed is not None:
                    break
            except (json.JSONDecodeError, ValueError, TypeError) as exc:
                last_error = str(exc)
                if attempt < max_provider_attempts - 1:
                    response = await provider.complete_json(
                        model=resolved_model,
                        system_prompt=system_prompt,
                        user_prompt=user_prompt,
                        temperature=temperature,
                        max_tokens=max_tokens,
                    )
                    raw_text = response.raw_text or ""
                    item.raw_response_text = raw_text
                    run.usage_json = response.usage.as_dict() if response.usage else {}
        if parsed is None:
            item.status = LlmItemStatus.failed
            item.error_message = f"failed to parse model JSON after {max_provider_attempts} attempts: {last_error}"
            run.status = LlmRunStatus.failed
            run.error_count = 1
        else:
            response.parsed_json = parsed
```

Also add `import json` and `max_provider_attempts = 2` near the top of the function (before the `provider = get_llm_provider` call, around line 607).

---

### Task 2: P0 — Add parse retry to circuit extraction

**File:** `backend/app/services/llm_circuit_extraction_service.py`

Find the circuit extraction provider call (around line 1022: `provider.complete_json(...)`). Add retry logic identical to Task 1 but using `parse_circuit_completion_response`.

Add `import json` and `max_provider_attempts = 2`. Wrap lines 1028-1052 (the parse attempt + error handling) with the same retry loop pattern from Task 1.

---

### Task 3: P0 — Add confidence-based merge for functions in mirror_kg_service

**File:** `backend/app/services/mirror_kg_service.py`

Add `_find_existing_function_for_merge` function (mirrors `_find_existing_connection_for_merge` at line 91).

```python
async def _find_existing_function_for_merge(
    session: AsyncSession,
    *,
    region_candidate_id: uuid.UUID,
    function_term_key: str,
    function_category: str,
    relation_type: str,
    source_atlas: str | None = None,
    granularity_level: str | None = None,
) -> MirrorRegionFunction | None:
    """Find an existing mergeable function by canonical dedup key."""
    query = select(MirrorRegionFunction).where(
        MirrorRegionFunction.promotion_status.notin_(
            [MirrorPromotionStatus.blocked, MirrorPromotionStatus.failed]
        ),
        MirrorRegionFunction.review_status != MirrorReviewStatus.rejected,
        MirrorRegionFunction.mirror_status != MirrorStatus.superseded,
        MirrorRegionFunction.region_candidate_id == region_candidate_id,
        MirrorRegionFunction.function_category == function_category,
        MirrorRegionFunction.relation_type == relation_type,
    )
    if source_atlas:
        query = query.where(MirrorRegionFunction.source_atlas == source_atlas)
    if granularity_level:
        query = query.where(MirrorRegionFunction.granularity_level == granularity_level)
    result = await session.execute(query)
    for row in result.scalars():
        if (row.function_term or "").strip().lower() == function_term_key:
            return row
    return None
```

Modify `create_mirror_function` (around line 397) to call `_find_existing_function_for_merge` before creating. If existing found and new confidence > existing confidence, update existing (same pattern as `create_mirror_connection` lines 226-280). Otherwise create new.

---

### Task 4: P0 — Add confidence-based merge for circuits in mirror_kg_service

**File:** `backend/app/services/mirror_kg_service.py`

Add `_find_existing_circuit_for_merge` and modify `create_mirror_circuit` with merge logic (same pattern as Task 3).

---

### Task 5: P1 — Add evidence dedup

**File:** `backend/app/services/mirror_kg_service.py`

In the evidence creation helper (or in each `persist_*_mirror_records`), add a check for existing evidence with same `target_type`, `target_id`, and `evidence_text` hash before creating new `MirrorEvidenceRecord`.

---

### Task 6: P1 — Fix circuit dedup to not rely solely on normalized_payload_json

**File:** `backend/app/services/llm_circuit_extraction_service.py`

In `_circuit_exists` (around line 663), add fallback: if `normalized_payload_json` is empty/None, derive `involved_region_candidate_ids` from the SQLAlchemy relationship `circuit.regions` instead.

---

### Task 7: P2 — Remove dead allowed_connection_types parameter

**File:** `backend/app/services/llm_extraction_prompt_engineering.py`

In `normalize_projection_extraction_response` (line 415): remove `del allowed_connection_types` line and the unused `allowed_connection_types` parameter entirely.

Update callers: `llm_connection_extraction_service.py` and `llm_composite_workflow_service.py` — remove the argument.

---

### Task 8: P2 — Replace broad except Exception with specific types

**Files:**
- `backend/app/services/llm_function_extraction_service.py` line 631
- `backend/app/services/llm_circuit_extraction_service.py` line 1045
- `backend/app/services/llm_connection_extraction_service.py` line 1324

Replace `except Exception` with `except (json.JSONDecodeError, ValueError, TypeError, KeyError)` in all three files.

---

### Task 9: Verify — run full test suite

```bash
cd backend && .venv/Scripts/python.exe -m pytest tests/ -q --ignore=tests/test_llm_field_completion.py
```
All tests must pass.
