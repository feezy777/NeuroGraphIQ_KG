# P0: Extraction Fault Recovery + Cost Visibility

> **For agentic workers:** Use superpowers:subagent-driven-development.

**Goal:** Allow retrying failed packs without full re-run, and show real-time token usage + cost during extraction.

**Architecture:** Two independent features: (A) backend retry endpoint + frontend button, (B) frontend cost display reading existing backend token data.

**Tech Stack:** FastAPI + React 18 + TypeScript

## Global Constraints

- Build: `cd frontend && npm run build` must pass with 0 TypeScript errors
- Tests: `cd backend && .venv/Scripts/python.exe -m pytest tests/ -q --ignore=tests/test_llm_field_completion.py` must pass
- No new dependencies
- DeepSeek pricing (CN region): deepseek-chat ¥1/M input tokens, ¥2/M output tokens; deepseek-reasoner ¥4/M input, ¥16/M output. deepseek-v4-pro: same as chat.

---

### Task 1: Backend — retry-failed endpoint

**Files:**
- Modify: `backend/app/routers/llm_composite_workflow.py`
- Modify: `backend/app/services/llm_composite_workflow_service.py`

**Interfaces:**
- Produces: `POST /api/llm-extraction/composite-workflows/{run_id}/retry-failed` returning `CompositeWorkflowStartResponse`
- Consumes: existing `start_composite_workflow` logic

Add router endpoint following the same pattern as `pause_composite_workflow` (lines 220-246):

```python
@router.post(
    "/composite-workflows/{workflow_run_id}/retry-failed",
    response_model=CompositeWorkflowStartResponse,
)
async def retry_failed_composite_workflow(
    workflow_run_id: uuid.UUID,
    session: AsyncSession = Depends(get_db),
):
    try:
        pending = await composite_svc.retry_failed_packs(session, workflow_run_id)
        return _start_response_from_run(pending)
    except KeyError:
        raise HTTPException(status_code=404, detail="Composite workflow run not found") from None
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None
    except Exception as exc:
        logger.exception("[llm-composite-workflow][retry-failed] unhandled")
        await session.rollback()
        raise HTTPException(status_code=500, detail={"code": "COMPOSITE_WORKFLOW_RETRY_ERROR", "message": "Failed to retry composite workflow.", "error": str(exc)[:500]}) from exc
```

Add service method `retry_failed_packs` to `llm_composite_workflow_service.py`:
1. Load the original workflow run
2. Extract `execution_summary.pack_summaries` — filter for packs where `status != 'succeeded'` and `status != 'no_connection'`
3. Collect all `pair_ids` from failed packs
4. Extract `candidate_ids` from those pair_ids (deduplicate)
5. If no failed packs → raise `ValueError("No failed packs to retry")`
6. Create a new `CompositeWorkflowRunRequest` with the same provider/model/temperature/max_tokens/prompt config, but only the failed-pair candidate_ids
7. Call `start_composite_workflow()` with the new request
8. Return the new run response

---

### Task 2: Frontend — fault recovery button in PoolExtractionModal

**Files:**
- Modify: `frontend/src/pages/llm-extraction/components/PoolExtractionModal.tsx`
- Modify: `frontend/src/api/endpoints.ts`

Add API function:
```typescript
export const retryFailedCompositeWorkflow = (workflowRunId: string) =>
  postJson<CompositeWorkflowStartResponse>(
    `/api/llm-extraction/composite-workflows/${workflowRunId}/retry-failed`,
    {},
  )
```

In PoolExtractionModal's result screen (`renderResult`), after the "汇总" stats section, add when `progress.failedPacks > 0`:

```tsx
<button
  className="llm-btn llm-btn-primary"
  onClick={async () => {
    try {
      const resp = await retryFailedCompositeWorkflow(progress.workflowRunId)
      // Reset progress for the new run
      setProgress({...initialProgress, workflowRunId: resp.workflow_run_id, workflowStatus: resp.status, totalPacks: resp.pair_count ? Math.ceil(resp.pair_count / 40) : 0, startedAt: new Date().toISOString()})
      setModalState('progress')
    } catch (err) {
      setProgress(prev => ({...prev, errors: [...prev.errors, `重试失败: ${err}`]}))
    }
  }}
>
  重试失败包 ({progress.failedPacks})
</button>
```

---

### Task 3: Frontend — cost visibility (progress + result)

**Files:**
- Modify: `frontend/src/pages/llm-extraction/components/PoolExtractionModal.tsx`

Add token fields to `ProgressData` interface:
```typescript
estimatedInputTokens: number
estimatedOutputTokens: number  
actualPromptTokens: number
actualCompletionTokens: number
```

In the polling effect, read token data from the same sources already polled:
```typescript
const estInput = readProgressMetric(sources, 'estimated_input_tokens') ?? 0
const estOutput = readProgressMetric(sources, 'estimated_output_tokens') ?? 0
const actualPrompt = readProgressMetric(sources, 'prompt_tokens')
const actualCompletion = readProgressMetric(sources, 'completion_tokens')
```

Add cost helper:
```typescript
function estimateCost(inputTokens: number, outputTokens: number): string {
  // DeepSeek CN pricing (¥/1M tokens)
  const inputPrice = 1.0   // ¥1 per 1M input tokens
  const outputPrice = 2.0  // ¥2 per 1M output tokens
  const cost = (inputTokens / 1_000_000) * inputPrice + (outputTokens / 1_000_000) * outputPrice
  if (cost < 0.01) return '< ¥0.01'
  return `¥${cost.toFixed(2)}`
}
```

In renderProgress, add a "用量" section before "时序":
```tsx
<div className="modal-section">
  <p className="modal-section-title">用量</p>
  <div className="modal-section-row">
    <span className="label">预估输入</span>
    <span className="value">{progress.estimatedInputTokens.toLocaleString()} tokens</span>
  </div>
  <div className="modal-section-row">
    <span className="label">预估输出</span>
    <span className="value">{progress.estimatedOutputTokens.toLocaleString()} tokens</span>
  </div>
  {(progress.actualPromptTokens > 0 || progress.actualCompletionTokens > 0) && (
    <>
      <div className="modal-section-row">
        <span className="label">实际输入</span>
        <span className="value">{progress.actualPromptTokens.toLocaleString()} tokens</span>
      </div>
      <div className="modal-section-row">
        <span className="label">实际输出</span>
        <span className="value">{progress.actualCompletionTokens.toLocaleString()} tokens</span>
      </div>
      <div className="modal-section-row">
        <span className="label">预估费用</span>
        <span className="value" style={{ fontWeight: 600, color: '#2563eb' }}>
          {estimateCost(progress.actualPromptTokens, progress.actualCompletionTokens)}
        </span>
      </div>
    </>
  )}
</div>
```

In renderResult, add a "费用" section after the time section:
```tsx
<div className="modal-section">
  <div className="modal-section-row">
    <span className="label">实际输入 tokens</span>
    <span className="value">{progress.actualPromptTokens.toLocaleString()}</span>
  </div>
  <div className="modal-section-row">
    <span className="label">实际输出 tokens</span>
    <span className="value">{progress.actualCompletionTokens.toLocaleString()}</span>
  </div>
  <div className="modal-section-row">
    <span className="label">预估费用</span>
    <span className="value" style={{ fontSize: 16, fontWeight: 600, color: '#2563eb' }}>
      {estimateCost(progress.actualPromptTokens, progress.actualCompletionTokens)}
    </span>
  </div>
</div>
```

---

### Task 4: Verify

```bash
cd backend && .venv/Scripts/python.exe -m pytest tests/ -q --ignore=tests/test_llm_field_completion.py
cd frontend && npm run build
```
