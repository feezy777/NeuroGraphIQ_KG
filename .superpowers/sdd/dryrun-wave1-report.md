# Dry Run Wave 1 — Implementation Report

## Summary

Two tasks completed: backend token estimation + sample pack execution, and frontend cleanup of 5 dry run blocks.

---

## Task A: Backend — Token Estimation + Optional Sample Pack

### A.1 Schema (`llm_composite_workflow.py`)
- Added `dry_run_sample_pack: bool = False` to `CompositeWorkflowRunRequest` (line 83)

### A.2 Schema (`llm_extraction.py`)
- Added `estimated_input_tokens: int | None = None` and `estimated_output_tokens: int | None = None` to `SameGranularityConnectionExtractionResponse`

### A.3 Connection Extraction Service (`llm_connection_extraction_service.py`)
- Added `estimated_input_tokens` and `estimated_output_tokens` fields to `ConnectionExtractionResult` dataclass
- Replaced the dry_run early-return block with token estimation using `estimate_prompt_tokens` from `field_completion_prompt_engineering`

### A.4 Composite Workflow Service (`llm_composite_workflow_service.py`)
- Added sample pack execution in `run_connection_with_function_workflow`: when `request.dry_run` and `request.dry_run_sample_pack`, calls the LLM provider directly, parses response, normalizes payload, and stores first 3 projections + raw text preview in `execution_summary.dry_run_sample`

---

## Task B: Frontend — Delete 5 Dry Run Blocks

| # | Workbench | Lines Removed |
|---|-----------|---------------|
| 1 | `CircuitToStepsWorkbench` | useState, checkbox, `!dryRun` guard, `dry_run: previewOnly` from API call, disabled condition |
| 2 | `CircuitStepsToProjectionsWorkbench` | useState, checkbox, `!dryRun` guard, `dry_run: previewOnly` from API call, disabled condition |
| 3 | `ProjectionToFunctionsWorkbench` | useState, checkbox, `!dryRun` guard, `dry_run: previewOnly` from API call, disabled condition |
| 4 | `ProjectionsToCircuitsWorkbench` | useState, checkbox, `!dryRun` guard, `dry_run: previewOnly` from API call, disabled condition |
| 5 | `CircuitProjectionCrossValidationWorkbench` | useState, checkbox, `effectiveDryRun` simplified, `dry_run` column, `disabled={dryRun}` removed |

---

## Verification

### Backend Tests
```
1000 passed, 4 failed, 9 skipped, 26 warnings in 5.54s
```
The 4 failures are pre-existing (test assertions against non-existent endpoints returning 404 instead of 422) — unrelated to these changes.

### Frontend Build
```
✓ built in 1.42s
```
Zero TypeScript errors.

---

## Files Modified

### Backend
- `backend/app/schemas/llm_composite_workflow.py`
- `backend/app/schemas/llm_extraction.py`
- `backend/app/services/llm_connection_extraction_service.py`
- `backend/app/services/llm_composite_workflow_service.py`

### Frontend
- `frontend/src/pages/LlmExtractionPage.tsx`
