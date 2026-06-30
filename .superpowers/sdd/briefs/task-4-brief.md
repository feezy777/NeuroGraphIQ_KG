# Task 4: Fix 5 Frontend — ProgressData + 显示

**Plan:** `docs/superpowers/plans/2026-06-30-pack-stats-audit-fix.md`
**Spec:** `docs/superpowers/specs/2026-06-30-pack-stats-audit-fix-design.md`

## File
- Modify: `frontend/src/pages/llm-extraction/components/PoolExtractionModal.tsx`

## Global Constraints
- 最小侵入
- 向后兼容：旧运行记录的 execution_summary 无新字段，前端做缺省处理
- npm run build 零 TypeScript 错误

## Changes (6 locations)

### 1. Add field to ProgressData interface (~line 32)
After `failedPacks`, add:
```typescript
  noConnectionPacks: number      // no_connection_pack_count — succeeded but zero connections found
```

### 2. Initialize in default state (~line 228)
After `failedPacks: 0,`, add:
```typescript
    noConnectionPacks: 0,
```

### 3. Initialize in start handler (~line 575)
After `failedPacks: 0,`, add:
```typescript
        noConnectionPacks: 0,
```

### 4. Read from API in polling (~line 799)
After the noConn read block, add:
```typescript
        const noConnectionPacks = readProgressMetric(
          terminal ? finalSources : liveSources,
          'no_connection_pack_count',
        ) ?? 0
```

### 5. Pass to setProgress (~line 913)
After `failedPacks,` line, add:
```typescript
          noConnectionPacks: noConnectionPacks ?? 0,
```

### 6. Display in UI — after success/fail pack cards
Find the `modal-metric-card` section around ~lines 1298-1310, add a new card after the "失败包" card:
```tsx
            <div className="modal-metric-card" style={{ background: progress.noConnectionPacks > 0 ? '#fff7e6' : '#fafafa' }}>
              <div className="metric-label" style={{ color: '#d48806' }}>无连接包</div>
              <div className="metric-value" style={{ color: '#d48806' }}>
                {progress.noConnectionPacks > 0 ? progress.noConnectionPacks : '—'}
              </div>
            </div>
```

## Verification
- `cd frontend && npm run build` — zero TypeScript errors
