# Task 6: Candidate Pool Frontend Integration — Report

**Status**: DONE

## Changes Made

### File 1: `frontend/src/pages/LlmExtractionPage.tsx`

1. **Added imports** for `CandidatePoolBar`, `FullExtractionModal`, `useCandidatePool`, and `PoolScope`.

2. **Added pool state** after `scope` and `providers` declarations:
   - `poolScope` state derived from session scope (`scope.source_atlas`, `scope.granularity_level`, `scope.granularity_family`)
   - `useCandidatePool(poolScope)` hook providing `pool`, `pooledCandidateIds`, `addCandidates`, `clearPool`
   - `showFullExtractModal`, `isExtracting`, `extractProgress` state for the full extraction flow

3. **Added auto-add on extraction** — `addCandidates(selectedCandidateIds)` is called before opening the extraction modal in:
   - `handleBatchExtract` (toolbar batch button)
   - All three quick extraction card onClick handlers (功能提取, 连接提取, 回路+步骤+功能提取)

4. **Rendered `CandidatePoolBar`** — appears in the JSX after the quick extraction cards, showing pool info when a pool exists or extraction is in progress.

5. **Rendered `FullExtractionModal`** — appears before the closing `</div>`. Its `onConfirm` extracts candidate IDs from the pool, calls `runCompositeExtractionTask`, and updates progress via the pool bar.

6. **Passed `pooledCandidateIds`** prop to `DataFirstCandidatesTab`.

### File 2: `frontend/src/pages/llm-extraction/components/DataFirstCandidatesTab.tsx`

1. **Added `pooledCandidateIds?: Set<string>`** to the `Props` interface and destructured it.

2. **Added `displayCols` computed columns** — when `pooledCandidateIds` is non-empty, a marker column (32px wide with a 🧠 icon) is prepended to show which candidates are already in the pool.

3. **Updated table rendering** — colgroup, thead, tbody, and colSpan values all use `displayCols` instead of `cols` to account for the optional marker column.

## Verification

- `npx tsc --noEmit` — 0 TypeScript errors
- `npm run build` — builds successfully (1689 modules transformed)

## Files Modified
- `frontend/src/pages/LlmExtractionPage.tsx` — main pool integration
- `frontend/src/pages/llm-extraction/components/DataFirstCandidatesTab.tsx` — pool row markers
