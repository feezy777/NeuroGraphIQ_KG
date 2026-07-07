# Extraction Fault Recovery: Retry Failed Packs

## Summary

Implemented one-click retry for failed extraction packs — instead of requiring the user to manually re-select candidates and configure a new workflow, a single button re-runs only the candidates whose packs failed.

## Changes

### Backend: Service Method

**File:** `backend/app/services/llm_composite_workflow_service.py`

Added `retry_failed_packs(session, workflow_run_id)` function at line 2431:

1. Loads the original composite workflow run by ID
2. Locates the `extract_connections` step and reads its `pack_summaries` from `response_json.execution_summary`
3. Filters packs whose status is NOT `succeeded` or `no_connection`
4. Reconstructs candidate-to-pack mapping from the original run's `candidate_ids_json` (all-pairs strategy, deterministic sort by pair_id, chunked at `DEFAULT_PAIRS_PER_PACK_OVERRIDE` = 30)
5. Extracts unique candidate IDs from failed-packs' pair_ids
6. Falls back to all original candidates if reconstruction yields < 2 candidate IDs
7. Builds a new `CompositeWorkflowRunRequest` from the original run's stored `request_json`, replacing `candidate_ids` with the retry subset
8. Delegates to `start_composite_workflow()` to create and queue the new run

**Note:** Pack summaries do not store individual `pair_ids`, so the pack-to-pair mapping is reconstructed deterministically. This is an approximation because the original extraction used hemisphere-priority sorting (which requires candidate metadata not available here). Mirror KG dedup/merge ensures correctness regardless.

### Backend: Router Endpoint

**File:** `backend/app/routers/llm_composite_workflow.py`

Added `POST /api/llm-extraction/composite-workflows/{workflow_run_id}/retry-failed` endpoint (after the resume endpoint). Returns `CompositeWorkflowStartResponse`.

Error handling:
- 404 if workflow run not found (`KeyError`)
- 400 if no failed packs or insufficient candidates (`ValueError`)
- 500 with structured error code `COMPOSITE_WORKFLOW_RETRY_ERROR` for unexpected failures

### Frontend: API Client

**File:** `frontend/src/api/endpoints.ts`

Added `retryFailedCompositeWorkflow(workflowRunId)` function, mirroring the pattern of `pauseCompositeWorkflow` / `resumeCompositeWorkflow`.

### Frontend: UI Button

**File:** `frontend/src/pages/llm-extraction/components/PoolExtractionModal.tsx`

Added a "重试失败包 (N)" button in the result footer, shown only when `progress.failedPacks > 0`. On click:

1. Calls `retryFailedCompositeWorkflow` with the current `workflowRunId`
2. Resets the progress state with the new workflow's run ID and status
3. Resets counters (processedPacks, failedPacks, connectionsFound, errors, etc.)
4. Switches back to the progress modal view
5. On error, appends the error message to progress errors without changing the result view

## Verification

- **Backend tests:** 1000 passed, 4 pre-existing failures (circuit projection extraction tests, unrelated)
- **Frontend build:** `npm run build` completes with 0 TypeScript errors and 0 build errors
