# Task 4 Report: Fix 5 Frontend — ProgressData + Display

**Status:** Complete

**File modified:** `frontend/src/pages/llm-extraction/components/PoolExtractionModal.tsx`

## Changes Made (6 locations)

1. **Interface** (line 34): Added `noConnectionPacks: number` to `ProgressData` interface.
2. **Default state** (line 247): Initialized `noConnectionPacks: 0` in `useState<ProgressData>`.
3. **Start handler** (line 578): Initialized `noConnectionPacks: 0` in `handleStartExtraction`.
4. **API polling** (line 804): Added `readProgressMetric` call reading `'no_connection_pack_count'` from execution_summary.
5. **State update** (line 934): Added `noConnectionPacks: noConnectionPacks ?? 0` to `setProgress()` call.
6. **UI display** (line 1298): Added "无连接包" card after the "失败包" card in the pack stats grid.

## Backward Compatibility

- `readProgressMetric` returns `0` when the backend field is absent, so old execution_summaries without `no_connection_pack_count` show `—` (dash) in the UI.
- No new API contract changes; the field is consumed only when present.

## Verification

- `cd frontend && npm run build` -- **0 TypeScript errors, build successful** (1.39s).
