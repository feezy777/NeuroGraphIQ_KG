# Pool Extraction Modal Redesign — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task.

**Goal:** Replace `CandidatePoolBar` + `FullExtractionModal` with a single `PoolExtractionModal` that handles pool management, extraction progress, and results in one 900px modal with fixed size.

**Architecture:** One modal component with three internal states (prepare/progress/result). Polling loop reads `execution_summary` from composite workflow API every 2s. Client-side computes average time and remaining estimate.

**Tech Stack:** React 18 + TypeScript, existing CSS variables, `getJson` from `api/client.ts`

**Spec:** `docs/superpowers/specs/2026-06-25-pool-extraction-modal-redesign.md`

## Global Constraints

- Modal fixed at max-width 900px, min-height 520px across all three states
- Progress polls `GET /api/llm-extraction/composite-workflow/{run_id}` every 2s
- Use real backend fields: `processed_pack_count`, `provider_success_count`, `failed_pack_count`, `parsed_projection_count`, `pack_summaries`
- `npm run build` must pass with 0 TypeScript errors
- Delete `CandidatePoolBar.tsx` and `FullExtractionModal.tsx`

---

## File Map

| File | Action |
|------|--------|
| `frontend/src/pages/llm-extraction/hooks/useCandidatePool.ts` | Modify — add `searchCandidates`, `batchRemove` |
| `frontend/src/pages/llm-extraction/components/PoolExtractionModal.tsx` | Create — three-state modal |
| `frontend/src/pages/llm-extraction/components/CandidatePoolBar.tsx` | Delete |
| `frontend/src/pages/llm-extraction/components/FullExtractionModal.tsx` | Delete |
| `frontend/src/pages/LlmExtractionPage.tsx` | Modify — remove Bar, wire modal |
| `frontend/src/styles.css` | Modify — remove pool-bar, add `.pool-extraction-modal` |

---

### Task 1: Enhance useCandidatePool Hook

**Files:**
- Modify: `frontend/src/pages/llm-extraction/hooks/useCandidatePool.ts`

**Interfaces:**
- Adds: `searchCandidates(query: string) => CandidateBrainRegion[]`, `batchRemove(ids: string[]) => void`
- Produces: Extended hook return consumed by Task 2

- [ ] **Step 1: Add `batchRemove` method**

In the hook's return block, add `batchRemove` before `clearPool`. This removes multiple candidates at once:

```typescript
  const batchRemove = useCallback(async (candidateIds: string[]) => {
    if (!pool || candidateIds.length === 0) return
    try {
      await removePoolMembers(pool.id, { candidate_ids: candidateIds })
      if (mountedRef.current) {
        const remaining = pool.candidate_count - candidateIds.length
        if (remaining <= 0) {
          setPool(null)
        } else {
          const full = await getCandidatePool(pool.id)
          if (mountedRef.current) setPool(full)
        }
      }
    } catch (err) {
      console.warn('[useCandidatePool] batchRemove failed:', err)
    }
  }, [pool?.id, pool?.candidate_count])
```

- [ ] **Step 2: Add `searchCandidates` method**

```typescript
  const searchCandidates = useCallback(async (query: string): Promise<any[]> => {
    if (!query.trim() || !scope) return []
    try {
      const { listCandidates } = await import('../../../api/endpoints')
      const result = await listCandidates({
        source_atlas: scope.sourceAtlas,
        granularity_level: scope.granularityLevel,
        granularity_family: scope.granularityFamily ?? '',
        search: query,
        limit: 20,
      })
      return result.items ?? []
    } catch (err) {
      console.warn('[useCandidatePool] searchCandidates failed:', err)
      return []
    }
  }, [scope])
```

- [ ] **Step 3: Update return object**

```typescript
  return {
    pool, pooledCandidateIds, isLoading,
    addCandidates, removeCandidate, batchRemove, clearPool,
    searchCandidates,
  }
```

- [ ] **Step 4: Verify**

```bash
cd frontend && npx tsc --noEmit --pretty 2>&1 | grep -i "useCandidatePool\|error TS" | head -5
```
Expected: No TS errors.

---

### Task 2: Create PoolExtractionModal

**Files:**
- Create: `frontend/src/pages/llm-extraction/components/PoolExtractionModal.tsx`

**Interfaces:**
- Consumes: `useCandidatePool` return type, `ModelSelector`, `CandidatePool` type, composite workflow API
- Produces: Modal used by Task 4

- [ ] **Step 1: Create the component with three states**

Write `frontend/src/pages/llm-extraction/components/PoolExtractionModal.tsx`:

```tsx
import { useState, useEffect, useRef, useCallback } from 'react'
import { ModelSelector } from './ModelSelector'
import {
  getCandidatePool, addPoolMembers, removePoolMembers,
  type CandidatePool, type CandidatePoolMember,
} from '../../../api/endpoints'
import { getJson } from '../../../api/client'

type ModalState = 'prepare' | 'progress' | 'result'

interface Props {
  open: boolean
  pool: CandidatePool | null
  pooledCandidateIds: Set<string>
  provider: string
  modelName: string
  providers: any[]
  onProviderChange: (p: string) => void
  onModelChange: (m: string) => void
  onPoolRefresh: () => void  // callback to refresh pool from parent
  selectedCount: number
  onAddSelected: () => void
  onClose: () => void
}

interface ProgressData {
  processedPacks: number; totalPacks: number
  successPacks: number; failedPacks: number
  connectionsFound: number
  recentErrors: string[]
}

interface ResultData {
  totalPacks: number; successPacks: number; failedPacks: number
  connectionsFound: number; elapsedSeconds: number
}

export function PoolExtractionModal({
  open, pool, pooledCandidateIds,
  provider, modelName, providers,
  onProviderChange, onModelChange, onPoolRefresh,
  selectedCount, onAddSelected, onClose,
}: Props) {
  const [state, setState] = useState<ModalState>('prepare')
  const [dryRun, setDryRun] = useState(false)
  const [searchQuery, setSearchQuery] = useState('')
  const [searchResults, setSearchResults] = useState<any[]>([])
  const [selectedForRemove, setSelectedForRemove] = useState<Set<string>>(new Set())
  const [progress, setProgress] = useState<ProgressData | null>(null)
  const [result, setResult] = useState<ResultData | null>(null)
  const [errorMsg, setErrorMsg] = useState<string | null>(null)
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null)
  const startTimeRef = useRef<number>(0)
  const runIdRef = useRef<string | null>(null)

  // Reset on open
  useEffect(() => {
    if (open) { setState('prepare'); setProgress(null); setResult(null); setErrorMsg(null) }
    return () => { if (pollRef.current) clearInterval(pollRef.current) }
  }, [open])

  // Search
  const handleSearch = useCallback(async (q: string) => {
    setSearchQuery(q)
    if (!q.trim()) { setSearchResults([]); return }
    try {
      const { listCandidates } = await import('../../../api/endpoints')
      const result = await listCandidates({
        source_atlas: pool?.source_atlas, granularity_level: pool?.granularity_level,
        search: q, limit: 20,
      })
      setSearchResults((result as any).items ?? [])
    } catch { setSearchResults([]) }
  }, [pool?.source_atlas, pool?.granularity_level])

  const addSearchResult = async (candidateId: string) => {
    if (!pool) return
    await addPoolMembers(pool.id, { candidate_ids: [candidateId] })
    onPoolRefresh()
    setSearchResults(prev => prev.filter(r => r.id !== candidateId))
  }

  const removeSelected = async () => {
    if (!pool || selectedForRemove.size === 0) return
    await removePoolMembers(pool.id, { candidate_ids: [...selectedForRemove] })
    setSelectedForRemove(new Set())
    onPoolRefresh()
  }

  // ── Start extraction ──
  const startExtraction = async () => {
    if (!pool) return
    setState('progress')
    setErrorMsg(null)
    startTimeRef.current = Date.now()

    try {
      const { runCompositeWorkflow } = await import('../services/compositeExtractionRunner')
      const response = await runCompositeWorkflow({
        workflow_type: 'connection_with_function',
        provider, model_name: modelName,
        candidate_pool_id: pool.id,
        create_mirror_records: true, dry_run: dryRun,
      })
      runIdRef.current = (response as any).workflow_run_id
      
      // Start polling
      pollRef.current = setInterval(async () => {
        try {
          const data: any = await getJson(
            `/api/llm-extraction/composite-workflow/${runIdRef.current}`
          )
          const s = data.result_summary ?? data
          const pp = s.processed_pack_count ?? s.executed_pack_count ?? 0
          const tp = s.pack_count ?? s.planned_pack_count ?? 0
          const sp = s.provider_success_count ?? 0
          const fp = s.failed_pack_count ?? 0
          const cf = s.parsed_projection_count ?? s.created_counts?.connections ?? 0
          const errors = (s.pack_summaries ?? [])
            .filter((p: any) => p.parse_error || p.status === 'failed')
            .slice(-3)
            .map((p: any) => `pack_${p.pack_index ?? '?'}: ${p.parse_error_type ?? p.status ?? 'unknown'}`)

          setProgress({ processedPacks: pp, totalPacks: tp, successPacks: sp, failedPacks: fp, connectionsFound: cf, recentErrors: errors })

          const done = data.status === 'succeeded' || data.status === 'failed' || data.status === 'cancelled'
          if (done) {
            clearInterval(pollRef.current!)
            pollRef.current = null
            setResult({
              totalPacks: tp, successPacks: sp, failedPacks: fp,
              connectionsFound: cf,
              elapsedSeconds: Math.round((Date.now() - startTimeRef.current) / 1000),
            })
            setState('result')
            onPoolRefresh()
          }
        } catch { /* polling error — continue */ }
      }, 2000)
    } catch (err: any) {
      setErrorMsg(err?.message ?? '提取启动失败')
      setState('prepare')
    }
  }

  const cancelExtraction = async () => {
    if (pollRef.current) clearInterval(pollRef.current)
    if (runIdRef.current) {
      try { await getJson(`/api/llm-extraction/composite-workflow/${runIdRef.current}/cancel`) } catch {}
    }
    setState('prepare')
    setProgress(null)
  }

  // ── Compute display values ──
  const elapsed = progress ? (Date.now() - startTimeRef.current) / 1000 : 0
  const avgPerPack = progress && progress.processedPacks > 0 ? elapsed / progress.processedPacks : 0
  const remaining = progress ? Math.round(avgPerPack * (progress.totalPacks - progress.processedPacks)) : 0
  const pct = progress && progress.totalPacks > 0 ? Math.round((progress.processedPacks / progress.totalPacks) * 100) : 0

  if (!open) return null

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className={`modal-panel wide pool-extraction-modal`} style={{ minHeight: 520 }} onClick={e => e.stopPropagation()}>
        {/* Header */}
        <div className="modal-header">
          <h3 style={{ margin: 0, fontSize: 18, fontWeight: 600 }}>
            {state === 'prepare' && '⚡ 全量连接提取'}
            {state === 'progress' && `⚡ 提取中...  ${pool?.source_atlas ?? ''} · ${pool?.granularity_level ?? ''}`}
            {state === 'result' && `✅ 提取完成  ${pool?.source_atlas ?? ''} · ${pool?.granularity_level ?? ''}`}
          </h3>
          <button className="btn-close" onClick={onClose}>✕</button>
        </div>

        {errorMsg && (
          <div style={{ padding: '8px 20px', color: '#cf1322', background: '#fff2f0', fontSize: 13 }}>{errorMsg}</div>
        )}

        {/* ── PREPARE ── */}
        {state === 'prepare' && pool && (
          <>
            <div style={{ padding: '0 20px' }}>
              <div className="modal-section">
                <p className="modal-section-title">
                  📊 候选池 &nbsp;
                  <span style={{ fontWeight: 400, fontSize: 13, color: '#2563eb' }}>
                    已累积 {pool.candidate_count} 脑区 · 预估 {pool.pair_count?.toLocaleString()} 对
                  </span>
                </p>
                {/* Search + Add */}
                <div style={{ display: 'flex', gap: 8, marginBottom: 12 }}>
                  <input
                    className="modal-prompt-textarea"
                    style={{ flex: 1, marginBottom: 0 }}
                    placeholder="搜索脑区加入池..."
                    value={searchQuery}
                    onChange={e => handleSearch(e.target.value)}
                  />
                  <button className="pool-bar-btn" onClick={onAddSelected} disabled={selectedCount === 0}>
                    + 添加选中 ({selectedCount})
                  </button>
                </div>
                {searchResults.length > 0 && (
                  <div style={{ maxHeight: 120, overflow: 'auto', marginBottom: 8, border: '1px solid #f0f0f0', borderRadius: 6 }}>
                    {searchResults.map((r: any) => (
                      <div key={r.id} style={{ display: 'flex', justifyContent: 'space-between', padding: '6px 10px', fontSize: 13, borderBottom: '1px solid #f5f5f5' }}>
                        <span>{r.cn_name || r.en_name || r.id}</span>
                        <button className="pool-bar-btn" style={{ padding: '2px 8px', fontSize: 11 }} onClick={() => addSearchResult(r.id)}>加入</button>
                      </div>
                    ))}
                  </div>
                )}
                {/* Pool members table */}
                {pool.candidate_count > 0 && (
                  <>
                    <div style={{ display: 'flex', gap: 8, marginBottom: 8, alignItems: 'center' }}>
                      <label style={{ fontSize: 12, cursor: 'pointer' }}>
                        <input type="checkbox" checked={selectedForRemove.size === pooledCandidateIds.size} onChange={() => {
                          if (selectedForRemove.size === pooledCandidateIds.size) setSelectedForRemove(new Set())
                          else setSelectedForRemove(new Set(pooledCandidateIds))
                        }} /> 全选
                      </label>
                      {selectedForRemove.size > 0 && (
                        <button className="pool-bar-btn danger" style={{ fontSize: 11, padding: '2px 10px' }} onClick={removeSelected}>
                          移除选中 ({selectedForRemove.size})
                        </button>
                      )}
                    </div>
                    <div style={{ maxHeight: 200, overflow: 'auto', border: '1px solid #f0f0f0', borderRadius: 6 }}>
                      <table style={{ width: '100%', fontSize: 13, borderCollapse: 'collapse' }}>
                        <thead>
                          <tr style={{ background: '#fafafa', textAlign: 'left' }}>
                            <th style={{ padding: '6px 8px', width: 32 }}></th>
                            <th style={{ padding: '6px 8px' }}>脑区名称</th>
                            <th style={{ padding: '6px 8px' }}>操作</th>
                          </tr>
                        </thead>
                        <tbody>
                          {pool.memberships?.map((m: CandidatePoolMember) => (
                            <tr key={m.id} style={{ borderTop: '1px solid #f5f5f5' }}>
                              <td style={{ padding: '4px 8px' }}>
                                <input type="checkbox" checked={selectedForRemove.has(m.candidate_id)} onChange={() => {
                                  setSelectedForRemove(prev => {
                                    const next = new Set(prev)
                                    next.has(m.candidate_id) ? next.delete(m.candidate_id) : next.add(m.candidate_id)
                                    return next
                                  })
                                }} />
                              </td>
                              <td style={{ padding: '4px 8px' }}>{m.candidate_id}</td>
                              <td style={{ padding: '4px 8px' }}>
                                <button className="pool-bar-btn" style={{ fontSize: 11, padding: '1px 8px', color: '#cf1322' }}
                                  onClick={() => { removePoolMembers(pool.id, { candidate_ids: [m.candidate_id] }); onPoolRefresh() }}>
                                  ✕ 移除
                                </button>
                              </td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  </>
                )}
              </div>

              {/* Model config */}
              <div className="modal-section">
                <p className="modal-section-title">⚙️ 模型配置</p>
                <ModelSelector
                  providers={providers}
                  provider={provider} modelName={modelName}
                  onProviderChange={onProviderChange} onModelChange={onModelChange}
                />
                <label style={{ display: 'flex', alignItems: 'center', gap: 8, marginTop: 12, fontSize: 13, color: '#888', cursor: 'pointer' }}>
                  <input type="checkbox" checked={dryRun} onChange={e => setDryRun(e.target.checked)} />
                  Dry run（仅预览，不实际调用 LLM）
                </label>
              </div>
            </div>

            <div className="modal-footer">
              <button className="pool-bar-btn" onClick={onClose}>取消</button>
              <button className="pool-bar-btn primary" onClick={startExtraction} disabled={!pool || pool.candidate_count < 2}>
                🚀 开始全量提取
              </button>
            </div>
          </>
        )}

        {/* ── PROGRESS ── */}
        {state === 'progress' && progress && (
          <>
            <div style={{ padding: '0 20px' }}>
              <div className="modal-section">
                <div className="pool-bar-progress-track" style={{ marginBottom: 12, height: 8 }}>
                  <div className="pool-bar-progress-fill" style={{ width: `${pct}%`, height: 8 }} />
                </div>
                <div className="pool-bar-progress-text" style={{ fontSize: 15, fontWeight: 500, color: '#1a1a2e', marginBottom: 8 }}>
                  {progress.processedPacks} / {progress.totalPacks} 包 ({pct}%)
                </div>
                <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '6px 24px', fontSize: 14 }}>
                  <div>✅ 成功 <strong>{progress.successPacks}</strong> 包</div>
                  <div>❌ 异常 <strong>{progress.failedPacks}</strong> 包</div>
                  <div>📊 已发现 <strong>{progress.connectionsFound}</strong> 条连接</div>
                  <div>⏱ 平均 <strong>{avgPerPack.toFixed(1)}s</strong>/包</div>
                </div>
                {remaining > 0 && (
                  <div style={{ marginTop: 8, fontSize: 13, color: '#888' }}>
                    ⏳ 预计剩余 ≈ {remaining > 60 ? `${Math.round(remaining / 60)} 分钟` : `${remaining} 秒`}
                  </div>
                )}
                {progress.recentErrors.length > 0 && (
                  <div style={{ marginTop: 10, padding: '8px 12px', background: '#fff2f0', borderRadius: 6, fontSize: 12 }}>
                    <strong style={{ color: '#cf1322' }}>最近异常:</strong>
                    {progress.recentErrors.map((e, i) => (
                      <div key={i} style={{ color: '#666', marginTop: 2 }}>{e}</div>
                    ))}
                  </div>
                )}
              </div>
            </div>
            <div className="modal-footer">
              <button className="pool-bar-btn danger" onClick={cancelExtraction}>⏹ 取消提取</button>
            </div>
          </>
        )}

        {/* ── RESULT ── */}
        {state === 'result' && result && (
          <>
            <div style={{ padding: '0 20px' }}>
              <div className="modal-section">
                <p className="modal-section-title">📊 结果摘要</p>
                <div className="modal-section-row"><span className="label">总包数</span><span className="value">{result.totalPacks}</span></div>
                <div className="modal-section-row"><span className="label">成功</span><span className="value">{result.successPacks}</span></div>
                <div className="modal-section-row"><span className="label">失败</span><span className="value">{result.failedPacks}</span></div>
                <div className="modal-section-row"><span className="label">连接总数</span><span className="value" style={{ color: '#2563eb', fontWeight: 700 }}>{result.connectionsFound} 条</span></div>
                <div className="modal-section-row"><span className="label">耗时</span><span className="value">{Math.round(result.elapsedSeconds / 60)} 分 {result.elapsedSeconds % 60} 秒</span></div>
              </div>
            </div>
            <div className="modal-footer">
              <button className="pool-bar-btn" onClick={onClose}>关闭</button>
            </div>
          </>
        )}
      </div>
    </div>
  )
}
```

- [ ] **Step 2: Verify**

```bash
cd frontend && npx tsc --noEmit --pretty 2>&1 | grep -i "PoolExtractionModal\|error TS" | head -10
```
Expected: No TS errors. If `runCompositeWorkflow` doesn't exist or has different signature, adapt the call to match the actual API function used in `LlmExtractionPage.tsx` for triggering composite workflows.

---

### Task 3: Cleanup — Delete Old Components + Update CSS

**Files:**
- Delete: `frontend/src/pages/llm-extraction/components/CandidatePoolBar.tsx`
- Delete: `frontend/src/pages/llm-extraction/components/FullExtractionModal.tsx`
- Modify: `frontend/src/styles.css`

- [ ] **Step 1: Delete old components**

```bash
rm frontend/src/pages/llm-extraction/components/CandidatePoolBar.tsx
rm frontend/src/pages/llm-extraction/components/FullExtractionModal.tsx
```

- [ ] **Step 2: Clean CSS**

In `frontend/src/styles.css`, remove the pool-bar section (`.pool-bar`, `.pool-bar-left`, `.pool-bar-info`, `.pool-bar-actions`, `.pool-bar-btn`, `.pool-bar-progress`, `.pool-row-marker`, and `@keyframes pool-progress-pulse`). These were added in the previous iteration. Find them and delete.

Also add the fixed modal size:
```css
/* ── Pool extraction modal ─────────────────────────────────────────────── */
.pool-extraction-modal .modal-panel {
  min-height: 520px;
}
```

- [ ] **Step 3: Verify build**

```bash
cd frontend && npm run build 2>&1 | tail -5
```
Expected: Build succeeds.

---

### Task 4: Wire Modal into LlmExtractionPage

**Files:**
- Modify: `frontend/src/pages/LlmExtractionPage.tsx`

- [ ] **Step 1: Update imports**

Remove:
```tsx
import { CandidatePoolBar } from './llm-extraction/components/CandidatePoolBar'
import { FullExtractionModal } from './llm-extraction/components/FullExtractionModal'
```

Replace `FullExtractionModal` import with:
```tsx
import { PoolExtractionModal } from './llm-extraction/components/PoolExtractionModal'
```

- [ ] **Step 2: Remove pool bar JSX**

Find and delete the `<CandidatePoolBar ... />` block (around lines 5997-6029).

- [ ] **Step 3: Replace modal JSX**

Find `<FullExtractionModal ... />` and replace with:

```tsx
      <PoolExtractionModal
        open={showFullExtractModal}
        pool={pool}
        pooledCandidateIds={pooledCandidateIds}
        provider={provider}
        modelName={modelName}
        providers={providers}
        onProviderChange={setProvider}
        onModelChange={setModelName}
        onPoolRefresh={() => {
          // Re-fetch pool to update state
          if (poolScope) {
            // Force re-render by toggling poolScope reference
            setPoolScope({ ...poolScope })
          }
        }}
        selectedCount={selectedCount}
        onAddSelected={() => addCandidates(selectedCandidateIds).catch(() => {})}
        onClose={() => setShowFullExtractModal(false)}
      />
```

Also update `useCandidatePool` destructuring to include `batchRemove` if needed. Actually — the pool refresh needs to trigger `useCandidatePool` to re-fetch. The simplest way: add a `refreshKey` state that increments on `onPoolRefresh`, and pass it to `useEffect` dependency in the hook. Or add a `refresh` method:

In `LlmExtractionPage.tsx`, add:
```tsx
  const [poolRefreshKey, setPoolRefreshKey] = useState(0)
  const handlePoolRefresh = () => setPoolRefreshKey(k => k + 1)
```

Pass `poolRefreshKey` to `useCandidatePool` dependency (modify the hook to watch it), OR simply call the pool fetch logic again. The simplest fix: add `refresh` to the hook's return.

Actually the simplest approach: since `addCandidates` and `removeCandidate` already refresh the pool internally, and `batchRemove` does too, the modal's search-and-add and remove-selected use the pool API directly. After those calls, `onPoolRefresh` can trigger a parent state update. The parent just needs a way to force the `useCandidatePool` to re-fetch.

Add to `useCandidatePool.ts`:

```typescript
  const refresh = useCallback(async () => {
    if (!pool?.id) return
    try {
      const full = await getCandidatePool(pool.id)
      if (mountedRef.current) setPool(full.candidate_count > 0 ? full : null)
    } catch {}
  }, [pool?.id])
```

Export `refresh` in the return, and pass it as `onPoolRefresh={refresh}`. This is cleaner than a refresh key.

- [ ] **Step 4: Verify build**

```bash
cd frontend && npm run build 2>&1 | tail -5
```
Expected: Build succeeds with 0 errors.

---

## Implementation Order

```
Task 1 (hook enhancement) ──┐
                             ├── Task 3 (cleanup) ── Task 4 (wire)
Task 2 (modal) ────────────┘
```

Task 1 and 2 are independent. Task 3 depends on both. Task 4 depends on Task 3.

---

## Spec Coverage

| Spec Section | Task |
|-------------|------|
| Pool management inside modal | Task 2 |
| Three states (prepare/progress/result) | Task 2 |
| Fixed 900px size, min-height 520px | Task 3 |
| Progress polling + avg/remaining calc | Task 2 |
| Delete CandidatePoolBar + FullExtractionModal | Task 3 |
| Wire into LlmExtractionPage | Task 4 |
| Search candidates + batch remove | Task 1 |
