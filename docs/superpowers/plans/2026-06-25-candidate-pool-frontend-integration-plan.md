# Candidate Pool Frontend Integration — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) to implement this plan task-by-task.

**Goal:** Add invisible auto-pooling + top status bar + full extraction modal to the LLM Extraction page, so users accumulate candidates across batches and trigger full all_pairs extraction with one click.

**Architecture:** New `useCandidatePool` hook manages pool state. `CandidatePoolBar` renders at page top. `FullExtractionModal` is the confirmation dialog. Existing `DataFirstCandidatesTab` and `LlmExtractionPage` get minimal wiring changes.

**Tech Stack:** React 18 + TypeScript + Vite, existing CSS variables and modal patterns

**Spec:** `docs/superpowers/specs/2026-06-25-candidate-pool-frontend-integration-design.md`

## Global Constraints

- Pool auto-creates by (source_atlas, granularity_level, granularity_family) — never cross-atlas
- Existing one-shot extraction flow preserved unchanged
- Modal styles unified: `.modal-panel` base + `.modal-panel.wide` for full extraction (900px max)
- All user-facing text uses existing i18n patterns (Chinese)
- `npm run build` must pass with 0 TypeScript errors

---

## File Map

| File | Action | Responsibility |
|------|--------|----------------|
| `frontend/src/api/endpoints.ts` | Modify | Add 6 pool API functions + types |
| `frontend/src/pages/llm-extraction/hooks/useCandidatePool.ts` | Create | Pool state: auto-fetch, auto-add, clear, progress |
| `frontend/src/pages/llm-extraction/components/CandidatePoolBar.tsx` | Create | Top status bar (idle + progress modes) |
| `frontend/src/pages/llm-extraction/components/FullExtractionModal.tsx` | Create | Wide confirmation modal for full extraction |
| `frontend/src/styles.css` | Modify | Add `.modal-panel.wide`, `.pool-bar`, pool progress styles |
| `frontend/src/pages/LlmExtractionPage.tsx` | Modify | Wire pool bar, auto-add on extract, full extraction trigger |
| `frontend/src/pages/llm-extraction/components/DataFirstCandidatesTab.tsx` | Modify | Emit selection IDs for auto-add; row marker for pooled candidates |

---

### Task 1: API Endpoints — Pool Types + Functions

**Files:**
- Modify: `frontend/src/api/endpoints.ts`

**Interfaces:**
- Produces: TypeScript types and 6 API functions consumed by Tasks 2-6

- [ ] **Step 1: Add pool types**

Add this block after the existing type definitions (e.g., after `CandidateBrainRegion` or near other LLM types):

```typescript
// ── Candidate Pools ──────────────────────────────────────────────────────────
export interface CandidatePoolMember {
  id: string
  pool_id: string
  candidate_id: string
  added_at: string
  added_by: string | null
}

export interface CandidatePool {
  id: string
  name: string | null
  resource_id: string | null
  batch_id: string | null
  source_atlas: string
  granularity_level: string
  granularity_family: string | null
  candidate_count: number
  pair_count: number
  status: string
  created_at: string
  updated_at: string
  memberships: CandidatePoolMember[]
}

export interface CandidatePoolCreateRequest {
  name?: string | null
  candidate_ids: string[]
  resource_id?: string | null
  batch_id?: string | null
  source_atlas: string
  granularity_level: string
  granularity_family?: string | null
}

export interface CandidatePoolMembersRequest {
  candidate_ids: string[]
}
```

- [ ] **Step 2: Add API functions**

Add after the pool types:

```typescript
export const createCandidatePool = (body: CandidatePoolCreateRequest) =>
  postJson<CandidatePool>('/api/candidates/pools', body)

export const listCandidatePools = (params?: Record<string, string | number | undefined>) =>
  getJson<{ items: CandidatePool[]; total: number }>('/api/candidates/pools', params)

export const getCandidatePool = (poolId: string) =>
  getJson<CandidatePool>(`/api/candidates/pools/${poolId}`)

export const addPoolMembers = (poolId: string, body: CandidatePoolMembersRequest) =>
  postJson<CandidatePool>(`/api/candidates/pools/${poolId}/members`, body)

export const removePoolMembers = (poolId: string, body: CandidatePoolMembersRequest) =>
  deleteJson<CandidatePool>(`/api/candidates/pools/${poolId}/members`, body)

export const deleteCandidatePool = (poolId: string) =>
  deleteJson<void>(`/api/candidates/pools/${poolId}`)
```

- [ ] **Step 3: Verify**

```bash
cd frontend && npx tsc --noEmit --pretty 2>&1 | head -5
```
Expected: 0 new TS errors (pool types are additive).

---

### Task 2: useCandidatePool Hook

**Files:**
- Create: `frontend/src/pages/llm-extraction/hooks/useCandidatePool.ts`

**Interfaces:**
- Consumes: `CandidatePool`, `CandidatePoolCreateRequest` from Task 1
- Produces: `useCandidatePool(scope)` → `{ pool, candidates, addCandidates, removeCandidate, clearPool, isLoading }`

- [ ] **Step 1: Write the hook**

```typescript
// frontend/src/pages/llm-extraction/hooks/useCandidatePool.ts
import { useState, useEffect, useCallback, useRef } from 'react'
import {
  createCandidatePool,
  getCandidatePool,
  addPoolMembers,
  removePoolMembers,
  deleteCandidatePool,
  listCandidatePools,
  type CandidatePool,
  type CandidatePoolMember,
} from '../../../api/endpoints'

export interface PoolScope {
  sourceAtlas: string
  granularityLevel: string
  granularityFamily: string | null
}

function scopeKey(s: PoolScope): string {
  return `${s.sourceAtlas}::${s.granularityLevel}::${s.granularityFamily ?? ''}`
}

export function useCandidatePool(scope: PoolScope | null) {
  const [pool, setPool] = useState<CandidatePool | null>(null)
  const [isLoading, setIsLoading] = useState(false)
  const mountedRef = useRef(true)
  const currentKey = scope ? scopeKey(scope) : null

  // Fetch or create pool when scope changes
  useEffect(() => {
    mountedRef.current = true
    if (!scope) {
      setPool(null)
      return
    }

    let cancelled = false
    setIsLoading(true)

    ;(async () => {
      try {
        // Find existing pool for this scope
        const { items } = await listCandidatePools({
          source_atlas: scope.sourceAtlas,
          granularity_level: scope.granularityLevel,
          granularity_family: scope.granularityFamily ?? '',
          status: 'active',
          limit: 1,
        })
        if (!mountedRef.current || cancelled) return

        if (items.length > 0) {
          // Refresh to get full memberships
          const full = await getCandidatePool(items[0].id)
          if (!mountedRef.current || cancelled) return
          setPool(full)
        } else {
          setPool(null) // No pool yet — will be created on first add
        }
      } catch (err) {
        console.warn('[useCandidatePool] fetch failed:', err)
      } finally {
        if (mountedRef.current && !cancelled) setIsLoading(false)
      }
    })()

    return () => { cancelled = true }
  }, [currentKey])

  // Cleanup on unmount
  useEffect(() => {
    return () => { mountedRef.current = false }
  }, [])

  const pooledCandidateIds = new Set(
    pool?.memberships?.map((m: CandidatePoolMember) => m.candidate_id) ?? []
  )

  const addCandidates = useCallback(async (candidateIds: string[]) => {
    if (!scope || candidateIds.length === 0) return

    const newIds = candidateIds.filter(id => !pooledCandidateIds.has(id))
    if (newIds.length === 0) return // All already in pool

    try {
      let currentPool = pool
      if (!currentPool) {
        // Auto-create pool on first add
        currentPool = await createCandidatePool({
          candidate_ids: newIds,
          source_atlas: scope.sourceAtlas,
          granularity_level: scope.granularityLevel,
          granularity_family: scope.granularityFamily,
        })
      } else {
        currentPool = await addPoolMembers(currentPool.id, { candidate_ids: newIds })
      }
      if (mountedRef.current) {
        // Refresh full pool to get updated memberships
        const full = await getCandidatePool(currentPool.id)
        if (mountedRef.current) setPool(full)
      }
    } catch (err) {
      console.warn('[useCandidatePool] add failed:', err)
    }
  }, [scope, pool?.id, currentKey])

  const removeCandidate = useCallback(async (candidateId: string) => {
    if (!pool) return
    try {
      await removePoolMembers(pool.id, { candidate_ids: [candidateId] })
      if (mountedRef.current) {
        const full = await getCandidatePool(pool.id)
        if (mountedRef.current) setPool(full.candidate_count > 0 ? full : null)
      }
    } catch (err) {
      console.warn('[useCandidatePool] remove failed:', err)
    }
  }, [pool?.id])

  const clearPool = useCallback(async () => {
    if (!pool) return
    try {
      await deleteCandidatePool(pool.id)
      if (mountedRef.current) setPool(null)
    } catch (err) {
      console.warn('[useCandidatePool] clear failed:', err)
    }
  }, [pool?.id])

  return {
    pool,
    pooledCandidateIds,
    isLoading,
    addCandidates,
    removeCandidate,
    clearPool,
  }
}
```

- [ ] **Step 2: Verify**

```bash
cd frontend && npx tsc --noEmit --pretty 2>&1 | grep -i "useCandidatePool\|error"
```
Expected: No TS errors related to this file.

---

### Task 3: Unified Modal CSS + Pool Bar Styles

**Files:**
- Modify: `frontend/src/styles.css`

**Interfaces:**
- Produces: CSS classes consumed by Tasks 4 and 5

- [ ] **Step 1: Add wide modal variant and pool-bar styles**

After the existing `.modal-prompt-textarea:focus` block (around line 9678), add:

```css
/* ── Wide modal variant ─────────────────────────────────────────────────── */
.modal-panel.wide {
  max-width: 900px;
}

/* ── Modal section cards ─────────────────────────────────────────────────── */
.modal-section {
  background: #f8f9fc;
  border-radius: 8px;
  padding: 16px 20px;
  margin-bottom: 16px;
}
.modal-section-title {
  font-size: 13px;
  font-weight: 600;
  color: #6b7280;
  text-transform: uppercase;
  letter-spacing: 0.5px;
  margin: 0 0 12px 0;
}
.modal-section-row {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 14px;
  color: #333;
  margin-bottom: 6px;
}
.modal-section-row .label {
  color: #888;
  min-width: 100px;
}
.modal-section-row .value {
  font-weight: 500;
}

/* ── Candidate Pool Bar ──────────────────────────────────────────────────── */
.pool-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  background: linear-gradient(135deg, #eef4ff 0%, #f0f5ff 100%);
  border: 1px solid #d6e4ff;
  border-radius: 10px;
  padding: 10px 18px;
  margin-bottom: 16px;
  font-size: 14px;
  gap: 12px;
  flex-wrap: wrap;
}
.pool-bar-left {
  display: flex;
  align-items: center;
  gap: 10px;
  flex: 1;
  min-width: 200px;
}
.pool-bar-icon {
  font-size: 20px;
}
.pool-bar-info {
  color: #1e3a5f;
}
.pool-bar-info strong {
  color: #2563eb;
}
.pool-bar-actions {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-shrink: 0;
}
.pool-bar-btn {
  padding: 5px 14px;
  border-radius: 6px;
  border: 1px solid #d0d7e2;
  background: #fff;
  color: #555;
  font-size: 13px;
  cursor: pointer;
  transition: all 0.15s;
  white-space: nowrap;
}
.pool-bar-btn:hover {
  border-color: #2563eb;
  color: #2563eb;
  background: #f8faff;
}
.pool-bar-btn.primary {
  background: #2563eb;
  color: #fff;
  border-color: #2563eb;
  font-weight: 500;
}
.pool-bar-btn.primary:hover {
  background: #1d4ed8;
}
.pool-bar-btn.danger {
  color: #cf1322;
  border-color: #ffccc7;
}
.pool-bar-btn.danger:hover {
  background: #fff2f0;
  border-color: #cf1322;
}
.pool-bar-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

/* ── Pool Bar Progress Mode ──────────────────────────────────────────────── */
.pool-bar-progress {
  flex: 1;
  min-width: 150px;
}
.pool-bar-progress-text {
  font-size: 13px;
  color: #555;
  margin-bottom: 4px;
}
.pool-bar-progress-track {
  height: 6px;
  background: #e0e7f0;
  border-radius: 3px;
  overflow: hidden;
}
.pool-bar-progress-fill {
  height: 100%;
  background: linear-gradient(90deg, #2563eb, #3b82f6);
  border-radius: 3px;
  transition: width 0.5s ease;
  animation: pool-progress-pulse 2s ease-in-out infinite;
}
@keyframes pool-progress-pulse {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.7; }
}

/* ── Pool row marker ─────────────────────────────────────────────────────── */
.pool-row-marker {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 20px;
  height: 20px;
  font-size: 12px;
  color: #2563eb;
  cursor: default;
}
```

- [ ] **Step 2: Verify the build**

```bash
cd frontend && npm run build 2>&1 | tail -10
```
Expected: Build succeeds (CSS changes only, no TS impact).

---

### Task 4: CandidatePoolBar Component

**Files:**
- Create: `frontend/src/pages/llm-extraction/components/CandidatePoolBar.tsx`

**Interfaces:**
- Consumes: CSS from Task 3, `useCandidatePool` from Task 2, `CandidatePool` from Task 1
- Produces: React component used by Task 6

- [ ] **Step 1: Write the component**

```tsx
// frontend/src/pages/llm-extraction/components/CandidatePoolBar.tsx
import { useState } from 'react'
import { ConfirmDialog } from '../../../components/ConfirmDialog'
import type { CandidatePool } from '../../../api/endpoints'

interface PoolProgress {
  processedPacks: number
  totalPacks: number
  connectionsFound: number
  errorPacks: number
}

interface Props {
  pool: CandidatePool | null
  pooledCount: number
  selectedCount: number
  isExtracting: boolean
  progress: PoolProgress | null
  onAddSelected: () => void
  onFullExtract: () => void
  onClearPool: () => void
  onViewDetails: () => void
}

export function CandidatePoolBar({
  pool,
  pooledCount,
  selectedCount,
  isExtracting,
  progress,
  onAddSelected,
  onFullExtract,
  onClearPool,
  onViewDetails,
}: Props) {
  const [showClearConfirm, setShowClearConfirm] = useState(false)

  // Hide when no pool and not extracting
  if (!pool && !isExtracting) return null

  // ── Progress mode ──
  if (isExtracting && progress) {
    const pct = progress.totalPacks > 0
      ? Math.round((progress.processedPacks / progress.totalPacks) * 100)
      : 0

    return (
      <div className="pool-bar">
        <div className="pool-bar-left">
          <span className="pool-bar-icon">⚡</span>
          <div className="pool-bar-progress">
            <div className="pool-bar-progress-text">
              提取中 · {pool?.source_atlas ?? ''} · {pool?.granularity_level ?? ''}
              &nbsp;&nbsp;|&nbsp;&nbsp;
              {progress.processedPacks}/{progress.totalPacks} 包
              &nbsp;&nbsp;|&nbsp;&nbsp;
              已发现 <strong>{progress.connectionsFound}</strong> 条连接
              {progress.errorPacks > 0 && (
                <span style={{ color: '#cf1322', marginLeft: 8 }}>
                  · {progress.errorPacks} 包异常
                </span>
              )}
            </div>
            <div className="pool-bar-progress-track">
              <div
                className="pool-bar-progress-fill"
                style={{ width: `${pct}%` }}
              />
            </div>
          </div>
        </div>
        <div className="pool-bar-actions">
          <button className="pool-bar-btn" onClick={onViewDetails}>查看详情</button>
        </div>
      </div>
    )
  }

  // ── Idle mode ──
  if (!pool) return null

  return (
    <>
      <div className="pool-bar">
        <div className="pool-bar-left">
          <span className="pool-bar-icon">🧠</span>
          <div className="pool-bar-info">
            {pool.source_atlas} · {pool.granularity_level}
            &nbsp;&nbsp;已累积 <strong>{pooledCount}</strong> 脑区
            &nbsp;·&nbsp; 预估 <strong>{pool.pair_count?.toLocaleString() ?? 0}</strong> 对
          </div>
        </div>
        <div className="pool-bar-actions">
          <button className="pool-bar-btn" onClick={onViewDetails}>
            查看池
          </button>
          <button
            className="pool-bar-btn"
            onClick={onAddSelected}
            disabled={selectedCount === 0}
          >
            + 添加选中 ({selectedCount})
          </button>
          <button className="pool-bar-btn primary" onClick={onFullExtract}>
            ⚡ 全量提取
          </button>
          <button
            className="pool-bar-btn danger"
            onClick={() => setShowClearConfirm(true)}
          >
            清空
          </button>
        </div>
      </div>

      <ConfirmDialog
        open={showClearConfirm}
        title="清空候选池"
        message={`确认清空 ${pool.source_atlas} · ${pool.granularity_level} 池中的全部 ${pooledCount} 个脑区？`}
        confirmLabel="确认清空"
        onConfirm={() => { onClearPool(); setShowClearConfirm(false) }}
        onCancel={() => setShowClearConfirm(false)}
      />
    </>
  )
}
```

- [ ] **Step 2: Verify build**

```bash
cd frontend && npx tsc --noEmit --pretty 2>&1 | grep -i "CandidatePoolBar\|error TS" | head -10
```
Expected: No TS errors.

---

### Task 5: FullExtractionModal Component

**Files:**
- Create: `frontend/src/pages/llm-extraction/components/FullExtractionModal.tsx`

**Interfaces:**
- Consumes: CSS from Task 3, `CandidatePool` from Task 1
- Produces: Modal component used by Task 6

- [ ] **Step 1: Write the component**

```tsx
// frontend/src/pages/llm-extraction/components/FullExtractionModal.tsx
import { useState } from 'react'
import { ModelSelector } from './ModelSelector'
import type { CandidatePool } from '../../../api/endpoints'

interface Props {
  open: boolean
  pool: CandidatePool | null
  provider: string
  modelName: string
  onProviderChange: (p: string) => void
  onModelChange: (m: string) => void
  onConfirm: (includeProjectionFunctions: boolean) => void
  onClose: () => void
}

export function FullExtractionModal({
  open,
  pool,
  provider,
  modelName,
  onProviderChange,
  onModelChange,
  onConfirm,
  onClose,
}: Props) {
  const [includeProjFn, setIncludeProjFn] = useState(false)
  const [dryRun, setDryRun] = useState(false)

  if (!open || !pool) return null

  const packs = pool.pair_count > 0
    ? Math.ceil(pool.pair_count / 30)
    : 0

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal-panel wide" onClick={e => e.stopPropagation()}>
        {/* Header */}
        <div className="modal-header">
          <h3>⚡ 全量连接提取</h3>
          <button className="btn-close" onClick={onClose}>✕</button>
        </div>

        {/* Scope section */}
        <div className="modal-section">
          <p className="modal-section-title">📊 提取范围</p>
          <div className="modal-section-row">
            <span className="label">Atlas</span>
            <span className="value">{pool.source_atlas}</span>
          </div>
          <div className="modal-section-row">
            <span className="label">Granularity</span>
            <span className="value">
              {pool.granularity_level}
              {pool.granularity_family ? ` / ${pool.granularity_family}` : ''}
            </span>
          </div>
          <div className="modal-section-row">
            <span className="label">脑区数</span>
            <span className="value">{pool.candidate_count} 个</span>
          </div>
          <div className="modal-section-row">
            <span className="label">配对量</span>
            <span className="value">{pool.pair_count.toLocaleString()} 对 (all_pairs)</span>
          </div>
          <div className="modal-section-row">
            <span className="label">预估</span>
            <span className="value">{packs} 包 (30对/包，5路并发)</span>
          </div>
        </div>

        {/* Model section */}
        <div className="modal-section">
          <p className="modal-section-title">⚙️ 模型配置</p>
          <ModelSelector
            provider={provider}
            modelName={modelName}
            onProviderChange={onProviderChange}
            onModelChange={onModelChange}
          />
          <label style={{ display: 'flex', alignItems: 'center', gap: 8, marginTop: 12, fontSize: 13, color: '#888', cursor: 'pointer' }}>
            <input
              type="checkbox"
              checked={dryRun}
              onChange={e => setDryRun(e.target.checked)}
            />
            Dry run（仅预览，不实际调用 LLM）
          </label>
        </div>

        {/* Content section */}
        <div className="modal-section">
          <p className="modal-section-title">📋 提取内容</p>
          <label style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 14, cursor: 'pointer' }}>
            <input type="checkbox" checked readOnly />
            连接提取 (Connection)
          </label>
          <label style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 14, marginTop: 8, cursor: 'pointer' }}>
            <input
              type="checkbox"
              checked={includeProjFn}
              onChange={e => setIncludeProjFn(e.target.checked)}
            />
            连接功能提取 (Projection Function)
          </label>
        </div>

        {/* Footer */}
        <div className="modal-footer">
          <button className="pool-bar-btn" onClick={onClose}>取消</button>
          <button
            className="pool-bar-btn primary"
            onClick={() => onConfirm(includeProjFn)}
          >
            🚀 开始全量提取
          </button>
        </div>
      </div>
    </div>
  )
}
```

- [ ] **Step 2: Verify build**

```bash
cd frontend && npx tsc --noEmit --pretty 2>&1 | grep -i "FullExtractionModal\|error TS" | head -10
```
Expected: No TS errors.

---

### Task 6: Wire Everything into LlmExtractionPage + DataFirstCandidatesTab

**Files:**
- Modify: `frontend/src/pages/LlmExtractionPage.tsx`
- Modify: `frontend/src/pages/llm-extraction/components/DataFirstCandidatesTab.tsx`

**Interfaces:**
- Consumes: All tasks above
- Produces: Fully integrated pool feature

- [ ] **Step 1: LlmExtractionPage — Add imports**

At top of `LlmExtractionPage.tsx`, add:

```tsx
import { CandidatePoolBar } from './llm-extraction/components/CandidatePoolBar'
import { FullExtractionModal } from './llm-extraction/components/FullExtractionModal'
import { useCandidatePool, type PoolScope } from './llm-extraction/hooks/useCandidatePool'
```

- [ ] **Step 2: LlmExtractionPage — Add pool state**

Find the existing state declarations (around line 5795+). Add:

```tsx
  // ── Candidate pool state ─────────────────────────────────────────────
  const poolScope: PoolScope | null = useMemo(() => {
    // Derive from current candidate table context — match the selected candidates' scope
    if (selectedCandidateIds.length > 0) {
      // Use the first selected candidate's scope — all must be homogeneous
      // (backend enforces this)
      const first = candidates.find(c => c.id === selectedCandidateIds[0])
      if (first) {
        return {
          sourceAtlas: first.source_atlas,
          granularityLevel: first.granularity_level,
          granularityFamily: first.granularity_family ?? null,
        }
      }
    }
    // Fallback: try from activeDataTab or session scope
    return null
  }, [selectedCandidateIds, candidates])

  const {
    pool,
    pooledCandidateIds,
    addCandidates,
    removeCandidate,
    clearPool,
  } = useCandidatePool(poolScope)

  const [showFullExtractModal, setShowFullExtractModal] = useState(false)
  const [isExtracting, setIsExtracting] = useState(false)
  const [extractProgress, setExtractProgress] = useState<{
    processedPacks: number
    totalPacks: number
    connectionsFound: number
    errorPacks: number
  } | null>(null)
```

Wait — `selectedCandidateIds` and `candidates` may not be in scope at the top level. The hook needs to be placed where these values are accessible. Let me adjust:

Find the component function body where `selectedCandidateIds` and all state lives. The pool hook should be declared **after** the candidate data loading but **before** the render return.

Let me provide exact placement instructions:

**Find** (around line 5810):
```tsx
  const [selectedCandidateIds, setSelectedCandidateIds] = useState<string[]>([])
```

**After** the existing state block, add:

```tsx
  // ── Candidate pool scope ────────────────────────────────────────────
  const [poolScope, setPoolScope] = useState<PoolScope | null>(null)

  // When candidates are loaded and user filters change, update pool scope
  useEffect(() => {
    // Get current batch/atlas context from the active filters
    const batchId = scopeBatchId ?? sess.batch_id ?? ''
    // If we have a batch selected, derive scope from it
    if (batchId && batches.length > 0) {
      const batch = batches.find((b: any) => b.id === batchId)
      if (batch) {
        setPoolScope({
          sourceAtlas: batch.source_atlas || 'AAL3',
          granularityLevel: batch.granularity_level || 'macro',
          granularityFamily: batch.granularity_family || 'macro_clinical',
        })
      }
    }
  }, [scopeBatchId, batches])

  const {
    pool,
    pooledCandidateIds,
    addCandidates,
    removeCandidate,
    clearPool,
  } = useCandidatePool(poolScope)

  const [showFullExtractModal, setShowFullExtractModal] = useState(false)
  const [isExtracting, setIsExtracting] = useState(false)
  const [extractProgress, setExtractProgress] = useState<{
    processedPacks: number; totalPacks: number
    connectionsFound: number; errorPacks: number
  } | null>(null)

  const pooledCount = pool?.candidate_count ?? 0
```

- [ ] **Step 3: LlmExtractionPage — Wire auto-add on extraction**

Find where `runCompositeTask` (around line 5854) or individual extraction functions are called. After a successful extraction trigger, silently add selected candidates to the pool:

```tsx
  // Inside the extraction trigger function, AFTER sending the API call:
  // Auto-add selected candidates to the pool
  if (selectedCandidateIds.length > 0) {
    addCandidates(selectedCandidateIds).catch(() => {
      // Silent — pool add failure shouldn't block extraction
    })
  }
```

Find the exact location by searching for `runCompositeTask` or `runSameGranularityConnectionExtraction` calls. Add the auto-add right after the API call.

- [ ] **Step 4: LlmExtractionPage — Render pool bar + modal**

Find the JSX return. Add `CandidatePoolBar` as the first element in the main content area (after `<PageHeader>` or the page title):

```tsx
        <CandidatePoolBar
          pool={pool}
          pooledCount={pooledCount}
          selectedCount={selectedCandidateIds.length}
          isExtracting={isExtracting}
          progress={extractProgress}
          onAddSelected={() => addCandidates(selectedCandidateIds)}
          onFullExtract={() => setShowFullExtractModal(true)}
          onClearPool={clearPool}
          onViewDetails={() => {
            // Navigate or expand pool detail view
            // For MVP: just scroll to the candidates table
            window.scrollTo({ top: 400, behavior: 'smooth' })
          }}
        />
```

Before the closing `</div>` of the page, add:

```tsx
        <FullExtractionModal
          open={showFullExtractModal}
          pool={pool}
          provider={provider}
          modelName={modelName}
          onProviderChange={setProvider}
          onModelChange={setModelName}
          onConfirm={async (includeProjFn) => {
            setShowFullExtractModal(false)
            if (!pool) return

            setIsExtracting(true)
            setExtractProgress({
              processedPacks: 0,
              totalPacks: Math.ceil(pool.pair_count / 30),
              connectionsFound: 0,
              errorPacks: 0,
            })

            try {
              // Call composite workflow with candidate_pool_id
              const requestBody: any = {
                workflow_type: 'connection_with_function',
                provider,
                model_name: modelName,
                candidate_pool_id: pool.id,
                create_mirror_records: true,
                dry_run: false,
              }
              // Import and call the API
              const { runCompositeWorkflow } = await import('./llm-extraction/services/compositeExtractionRunner')
              // ... or use the existing composite extraction runner
              
              // Start polling for progress
              // ... (poll GET /api/llm-extraction/composite-workflow/{id})
            } catch (err) {
              console.error('Full extraction failed:', err)
              setIsExtracting(false)
              setExtractProgress(null)
            }
            // Note: Progress polling and completion handling
            // reuses the existing ExtractionRunModal/Suspense pattern
          }}
          onClose={() => setShowFullExtractModal(false)}
        />
```

- [ ] **Step 5: DataFirstCandidatesTab — Emit selection changes**

In `DataFirstCandidatesTab.tsx`, find where table row selection happens. Add a visual marker for candidates already in the pool.

The component already has `onSelectionIdsChange` prop. In the parent (`LlmExtractionPage`), when `selectedCandidateIds` changes, `poolScope` updates and the pool bar reacts — no changes needed to `DataFirstCandidatesTab` for auto-add.

For the **row marker**: If `pooledCandidateIds` is passed as a prop, add a 🧠 icon before the candidate name in the table. This requires a small prop addition to `DataFirstCandidatesTab`:

```tsx
// Add to Props interface:
  pooledCandidateIds?: Set<string>

// In the table columns, prepend marker:
  {
    key: 'marker',
    header: '',
    render: (_: any, row: CandidateBrainRegion) =>
      pooledCandidateIds?.has(row.id) ? (
        <span className="pool-row-marker" title="已在提取池中">🧠</span>
      ) : null,
    width: 32,
  }
```

- [ ] **Step 6: Verify full build**

```bash
cd frontend && npm run build 2>&1
```
Expected: Build succeeds with 0 TypeScript errors.

- [ ] **Step 7: Verify frontend dev server**

```bash
# Start dev server and check http://localhost:5173
# Navigate to LLM Extraction page
# Select candidates → verify pool bar appears
# Click "全量提取" → verify modal opens
```
Expected: Pool bar appears, modal opens with correct pool info.

---

## Implementation Order

```
Task 1 (API types) → Task 2 (hook) ─┐
Task 3 (CSS) ────────────────────────┤
                                      ├→ Task 4 (PoolBar) ─┐
                                      │                     ├→ Task 6 (Integration)
                                      └→ Task 5 (Modal) ───┘
```

Tasks 1-3 are independent and can run in parallel. Tasks 4 and 5 can run in parallel after 1-3. Task 6 depends on all others.

---

## Spec Coverage Check

| Spec Section | Task |
|-------------|------|
| Auto-pool by (atlas, granularity, family) | Task 2 (hook), Task 6 (wire) |
| Top status bar | Task 4 |
| Organic integration + auto-add on extract | Task 6 |
| Full extraction modal (wide, 900px) | Task 5 |
| Unified modal CSS | Task 3 |
| Progress mode during extraction | Task 4 |
| Row marker for pooled candidates | Task 6 |
| Pool detail view | Task 4 (onViewDetails callback) |
