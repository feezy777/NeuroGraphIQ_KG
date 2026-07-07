# ExtractionProgressPanel + Field Completion Async Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extract shared progress/result panel from PoolExtractionModal into reusable ExtractionProgressPanel component. Adapt FieldCompletionModal to use it. Make field completion backend async (background task + polling + cancel) with concurrency.

**Architecture:** Three-phase: (1) Extract shared component, (2) Adapt PoolExtractionModal to use it, (3) Adapt FieldCompletionModal with async backend. Each phase independently testable.

**Tech Stack:** React 18 + TypeScript, FastAPI, SQLAlchemy async, DeepSeek provider

## Global Constraints

- Don't change extraction pipeline logic (pair generation, parsing, Mirror write)
- Don't change field completion prompt templates or field mapping
- Don't change Dry Run logic for either feature
- Shared component must accept progress via props (parent owns polling)

---

### Phase 1: Shared Component

### Task 1: Create ExtractionProgressPanel component

**Files:**
- Create: `frontend/src/pages/llm-extraction/components/ExtractionProgressPanel.tsx`
- Create: `frontend/src/pages/llm-extraction/components/ExtractionProgressPanel.css`

**Interfaces:**
- Produces: `ExtractionProgressPanel` component with props:
  - `progress: ProgressData` (imported from PoolExtractionModal or shared types)
  - `onPause?: () => void`
  - `onResume?: () => void`
  - `onCancel: () => void`
  - `onClose: () => void`
  - `onRetryFailed?: () => void`
  - `onViewResults?: () => void`
  - `showRetry?: boolean`
  - `showPause?: boolean`
  - `workflowType?: string`
  - `isDryRun?: boolean`
  - `dryRunPlan?: any`

- [ ] **Step 1: Create type file for shared progress types**

Move `ProgressData` interface to `frontend/src/pages/llm-extraction/types.ts`:

```typescript
export interface ProgressData {
  workflowRunId: string
  workflowStatus: string
  progressPercent: number
  processedPacks: number
  totalPacks: number
  successPacks: number
  failedPacks: number
  noFindingsPacks: number
  connectionsFound: number
  screenedLikelyCount: number
  functionCount: number
  parsedNoConnCount: number
  createdCount: number
  updatedCount: number
  mergedCount: number
  skippedDupCount: number
  noConnectionCount: number
  providerCallCount: number
  modelCalls: number
  promptSent: number
  inFlightPacks: number
  concurrency: number
  averagePackSec: number | null
  estimatedRemainingSec: number | null
  zeroDiags: string[]
  errors: string[]
  elapsedSec: number
  startedAt: string | null
  lastPauseResponse: string
  lastPauseError: string
  lastCancelResponse: string
  lastCancelError: string
  estimatedInputTokens: number
  estimatedOutputTokens: number
  actualPromptTokens: number
  actualCompletionTokens: number
  dryRunSamplePack: boolean
}
```

- [ ] **Step 2: Copy renderProgress and renderResult from PoolExtractionModal**

Copy the two render functions (lines ~1509-1770 and ~1844-1970 from current PoolExtractionModal.tsx) into ExtractionProgressPanel. Keep the compact two-column layout with RawDebug.

- [ ] **Step 3: Wire up props**

Replace direct state access with `props.progress.*`. Replace `handlePause/handleResume/handleCancel/handleClose/setShowErrors` with `props.onPause/onResume/onCancel/onClose`.

- [ ] **Step 4: Export component**

```typescript
export function ExtractionProgressPanel({
  progress, onPause, onResume, onCancel, onClose,
  onRetryFailed, onViewResults, showRetry = false, showPause = true,
  workflowType, isDryRun, dryRunPlan,
}: ExtractionProgressPanelProps) { ... }
```

- [ ] **Step 5: Build check**

Run: `cd frontend && npm run build`
Expected: 0 errors

- [ ] **Step 6: Commit**

```bash
git add frontend/src/pages/llm-extraction/components/ExtractionProgressPanel.tsx
git add frontend/src/pages/llm-extraction/types.ts
git commit -m "feat: add ExtractionProgressPanel shared component"
```

---

### Task 2: Adapt PoolExtractionModal to use ExtractionProgressPanel

**Files:**
- Modify: `frontend/src/pages/llm-extraction/components/PoolExtractionModal.tsx`
- Modify: `frontend/src/pages/llm-extraction/types.ts`

- [ ] **Step 1: Import shared component and types**

```typescript
import { ExtractionProgressPanel } from './ExtractionProgressPanel'
import type { ProgressData } from '../types'
```

Remove `ProgressData` interface from PoolExtractionModal (now in types.ts).

- [ ] **Step 2: Replace renderProgress() call**

In the render dispatcher (line ~2091-2097), replace:
```tsx
{modalState === 'progress' && renderProgress()}
{modalState === 'result' && renderResult()}
```
with:
```tsx
{(modalState === 'progress' || modalState === 'result') && (
  <ExtractionProgressPanel
    progress={progress}
    onPause={handlePause}
    onResume={handleResume}
    onCancel={handleCancel}
    onClose={handleClose}
    onRetryFailed={progress.failedPacks > 0 ? () => handleRetry() : undefined}
    onViewResults={!dryRunPlan && isSuccess ? () => {
      window.location.href = `/data-center?tab=mirror-kg&run_id=${progress.workflowRunId}`
    } : undefined}
    showRetry={progress.failedPacks > 0}
    showPause={progress.workflowStatus === 'running' || progress.workflowStatus === 'pending'}
    workflowType={workflowType}
    isDryRun={!!dryRunPlan}
    dryRunPlan={dryRunPlan}
  />
)}
```

- [ ] **Step 3: Remove old renderProgress and renderResult functions**

Delete `renderProgress()` and `renderResult()` functions from PoolExtractionModal. Also remove helper variables that are only used by those functions (e.g., `avgSec`, `remSec` at lines ~1510-1511 if they're only used inside renderProgress).

- [ ] **Step 4: Keep polling logic in parent**

The `useEffect` polling interval stays in PoolExtractionModal — it updates `progress` state which flows into ExtractionProgressPanel via props.

- [ ] **Step 5: Add handleRetry wrapper**

If not already extracted, wrap the retry logic in a `handleRetry` callback.

- [ ] **Step 6: Build check**

Run: `cd frontend && npm run build`
Expected: 0 errors, PoolExtractionModal should be ~30% smaller

- [ ] **Step 7: Commit**

```bash
git add frontend/src/pages/llm-extraction/components/PoolExtractionModal.tsx
git commit -m "refactor: PoolExtractionModal uses ExtractionProgressPanel"
```

---

### Phase 2: Field Completion Async Backend

### Task 3: Add async run/poll/cancel endpoints to field completion

**Files:**
- Create: `backend/app/routers/llm_field_completion.py` (rewrite run endpoint, add GET runs/{id}, POST cancel)
- Modify: `backend/app/services/llm_field_completion_service.py`
- Modify: `backend/app/schemas/llm_field_completion.py` (add status fields)

- [ ] **Step 1: Add status enums and response schemas**

In `backend/app/schemas/llm_field_completion.py`, add:

```python
from enum import Enum

class FieldCompletionRunStatus(str, Enum):
    pending = "pending"
    running = "running"
    succeeded = "succeeded"
    partially_succeeded = "partially_succeeded"
    failed = "failed"
    cancelled = "cancelled"

class FieldCompletionRunRead(BaseModel):
    id: uuid.UUID
    status: FieldCompletionRunStatus
    provider: str | None = None
    model_name: str | None = None
    total_count: int = 0
    completed_count: int = 0
    updated_count: int = 0
    suggested_count: int = 0
    skipped_count: int = 0
    failed_count: int = 0
    warnings: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    started_at: datetime | None = None
    completed_at: datetime | None = None
    created_at: datetime | None = None
```

- [ ] **Step 2: Rewrite POST /run endpoint**

Change from synchronous to async:

```python
@router.post("/field-completion/run")
async def run_field_completion(
    request: UniversalFieldCompletionRequest,
    background_tasks: BackgroundTasks,
    session: AsyncSession = Depends(get_db),
):
    # Validate
    # Create run record with status=pending
    run = await create_field_completion_run(session, request)
    await session.commit()
    
    if request.dry_run:
        # Dry run: execute synchronously (no LLM calls)
        return await execute_dry_run(session, run, request)
    
    # Start background execution
    background_tasks.add_task(
        execute_field_completion_background,
        run.id, request.model_dump(mode="json"),
    )
    
    return FieldCompletionStartResponse(
        run_id=run.id,
        status="pending",
        total_count=run.total_count,
    )
```

- [ ] **Step 3: Add GET /runs/{id} endpoint**

```python
@router.get("/field-completion/runs/{run_id}")
async def get_field_completion_run(
    run_id: uuid.UUID,
    session: AsyncSession = Depends(get_db),
):
    run = await session.get(LlmFieldCompletionRun, run_id)
    if not run:
        raise HTTPException(404)
    return FieldCompletionRunRead(
        id=run.id,
        status=run.status,
        total_count=run.total_count or 0,
        completed_count=(run.summary_json or {}).get("completed_count", 0),
        updated_count=(run.summary_json or {}).get("updated_count", 0),
        # ... etc
    )
```

- [ ] **Step 4: Add POST /cancel endpoint**

```python
@router.post("/field-completion/runs/{run_id}/cancel")
async def cancel_field_completion(
    run_id: uuid.UUID,
    session: AsyncSession = Depends(get_db),
):
    run = await session.get(LlmFieldCompletionRun, run_id)
    if not run:
        raise HTTPException(404)
    run.status = FieldCompletionRunStatus.cancelled
    await session.commit()
    return {"status": "cancelled"}
```

- [ ] **Step 5: Run backend tests**

Run: `cd backend && .\.venv\Scripts\python.exe -m pytest tests/ -q -k "field_completion"`
Expected: existing tests pass

- [ ] **Step 6: Commit**

```bash
git add backend/app/routers/llm_field_completion.py backend/app/schemas/llm_field_completion.py
git commit -m "feat: field completion async endpoints (run/poll/cancel)"
```

---

### Task 4: Background execution with concurrency

**Files:**
- Modify: `backend/app/services/llm_field_completion_service.py`
- Modify: `backend/app/services/field_completion_execution.py`

- [ ] **Step 1: Add background task function**

```python
async def execute_field_completion_background(
    run_id: uuid.UUID,
    request_payload: dict[str, Any],
) -> None:
    from app.database import AsyncSessionLocal
    request = UniversalFieldCompletionRequest.model_validate(request_payload)
    
    async with AsyncSessionLocal() as session:
        try:
            run = await session.get(LlmFieldCompletionRun, run_id)
            if not run:
                return
            run.status = "running"
            run.started_at = datetime.now(timezone.utc)
            await session.commit()
            
            result = await run_universal_field_completion(
                session, request, run_id=run_id,
            )
            
            run.status = result.status
            run.completed_at = datetime.now(timezone.utc)
            await session.commit()
        except asyncio.CancelledError:
            run = await session.get(LlmFieldCompletionRun, run_id)
            if run:
                run.status = "cancelled"
                run.completed_at = datetime.now(timezone.utc)
                await session.commit()
```

- [ ] **Step 2: Add concurrency to field execution**

In `field_completion_execution.py`, replace sequential pack execution:

```python
# Before: sequential
for pack in packs:
    result = await call_provider(...)

# After: concurrent with semaphore
semaphore = asyncio.Semaphore(4)

async def run_pack(pack):
    async with semaphore:
        return await call_provider(...)

tasks = [run_pack(p) for p in packs]
for coro in asyncio.as_completed(tasks):
    result = await coro
    # Update progress
    run.summary_json["completed_count"] += 1
    await session.commit()
```

- [ ] **Step 3: Add progress tracking**

Update `summary_json` after each pack:
```python
summary = dict(run.summary_json or {})
summary["completed_count"] = summary.get("completed_count", 0) + 1
run.summary_json = summary
flag_modified(run, "summary_json")
await session.commit()
```

- [ ] **Step 4: Check cancel flag between packs**

```python
for coro in asyncio.as_completed(tasks):
    # Check cancel
    await session.refresh(run)
    if run.status == "cancelled":
        break
    result = await coro
```

- [ ] **Step 5: Run tests**

Run: `cd backend && .\.venv\Scripts\python.exe -m pytest tests/ -q -k "field_completion"`
Expected: pass

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/llm_field_completion_service.py backend/app/services/field_completion_execution.py
git commit -m "feat: field completion async background execution with concurrency"
```

---

### Phase 3: Adapt FieldCompletionModal

### Task 5: Add progress panel to FieldCompletionModal

**Files:**
- Modify: `frontend/src/pages/data-center/FieldCompletionModal.tsx`

- [ ] **Step 1: Import shared component**

```typescript
import { ExtractionProgressPanel } from '../../llm-extraction/components/ExtractionProgressPanel'
import type { ProgressData } from '../../llm-extraction/types'
```

- [ ] **Step 2: Add modal states**

Add `modalState: 'config' | 'progress' | 'result'` to replace current `loading` boolean.

- [ ] **Step 3: Add polling logic**

```typescript
const [progress, setProgress] = useState<ProgressData>({...defaults})

useEffect(() => {
  if (modalState !== 'progress' || !runId) return
  const interval = setInterval(async () => {
    const detail = await getFieldCompletionRun(runId)
    setProgress(prev => ({
      ...prev,
      workflowRunId: detail.id,
      workflowStatus: detail.status,
      processedPacks: detail.completed_count,
      totalPacks: detail.total_count,
      successPacks: detail.updated_count + detail.suggested_count,
      failedPacks: detail.failed_count,
      errors: detail.errors || [],
      elapsedSec: (Date.now() - startTime) / 1000,
    }))
    if (['succeeded', 'partially_succeeded', 'failed', 'cancelled'].includes(detail.status)) {
      setModalState('result')
      clearInterval(interval)
    }
  }, 2000)
  return () => clearInterval(interval)
}, [modalState, runId])
```

- [ ] **Step 4: Add cancel handler**

```typescript
const handleCancel = async () => {
  await cancelFieldCompletionRun(runId)
}
```

- [ ] **Step 5: Replace loading UI with ExtractionProgressPanel**

```tsx
{modalState === 'progress' || modalState === 'result' ? (
  <ExtractionProgressPanel
    progress={progress}
    onCancel={handleCancel}
    onClose={handleClose}
    showPause={false}
    showRetry={false}
    workflowType="field_completion"
  />
) : (
  // existing config UI
)}
```

- [ ] **Step 6: Add API endpoints to frontend**

In `frontend/src/api/endpoints.ts`:
```typescript
export const getFieldCompletionRun = (runId: string) =>
  getJson<FieldCompletionRunRead>(`/api/llm-extraction/field-completion/runs/${runId}`)

export const cancelFieldCompletionRun = (runId: string) =>
  postJson(`/api/llm-extraction/field-completion/runs/${runId}/cancel`, {})
```

- [ ] **Step 7: Build check**

Run: `cd frontend && npm run build`
Expected: 0 errors

- [ ] **Step 8: Commit**

```bash
git add frontend/src/pages/data-center/FieldCompletionModal.tsx frontend/src/api/endpoints.ts
git commit -m "feat: FieldCompletionModal with async progress panel"
```

---

### Verification

1. **Connection extraction unchanged**: Run balanced extraction, verify progress panel shows same data as before
2. **Field completion async**: Run field completion, verify progress updates every 2s, cancel works
3. **Field completion concurrent**: Check backend logs for parallel LLM calls
4. **Field completion speed**: Should be ~4x faster with 4-way concurrency

