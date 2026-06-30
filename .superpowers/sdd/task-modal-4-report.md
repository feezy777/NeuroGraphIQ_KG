# Task 4: Wire PoolExtractionModal into LlmExtractionPage — Report

## Status: DONE

## Changes Made

### 1. `frontend/src/pages/LlmExtractionPage.tsx`

| Step | Change | Details |
|------|--------|---------|
| **Step 1** | Read file | Parsed 319KB file to understand imports, state, and JSX usage |
| **Step 2** | Fix imports | Removed `CandidatePoolBar` + `FullExtractionModal` imports; added `PoolExtractionModal` import |
| **Step 3** | Add `refresh` | Added `refresh` to `useCandidatePool(poolScope)` destructuring |
| **Step 4** | Remove CandidatePoolBar JSX | Deleted the entire `<CandidatePoolBar ... />` block (lines 5995-6011, ~17 lines) |
| **Step 5** | Replace FullExtractionModal | Replaced `<FullExtractionModal ...>` (with complex `onConfirm`/`onProgress` extraction logic) with `<PoolExtractionModal>` using the new prop interface |
| **Step 6** | Remove unused state | Removed `isExtracting` + `extractProgress` state declarations (only used by the deleted bar and old modal callback) |

### 2. `frontend/src/pages/llm-extraction/hooks/useCandidatePool.ts`

| Issue | Fix |
|-------|-----|
| `listCandidates` not exported from API endpoints | Changed dynamic import from `endpoints` to `client`, using `getJson('/api/candidates/brain-regions', ...)` directly |

## Props Mapping (Old FullExtractionModal → New PoolExtractionModal)

| Old Prop | New Prop | Notes |
|----------|----------|-------|
| `open` | `open` | Same |
| `pool` | `pool` | Same |
| — | `pooledCandidateIds` | Added — new required prop from `useCandidatePool` |
| `provider` | `provider` | Same |
| `modelName` | `modelName` | Same |
| `providers` | `providers` | Same |
| `onProviderChange` | `onProviderChange` | Same |
| `onModelChange` | `onModelChange` | Same |
| — | `onPoolRefresh` | Added — new prop, wired to `refresh` from `useCandidatePool` |
| — | `selectedCount` | Added — new prop, wired to existing `selectedCount` state |
| — | `onAddSelected` | Added — new prop, wired to `addCandidates(selectedCandidateIds)` |
| `onClose` | `onClose` | Same |
| `onConfirm` | Removed | Complex extraction logic (setIsExtracting/setExtractProgress/runCompositeExtractionTask) handled internally by PoolExtractionModal |

## Build Verification

- `npm run build` passes with **0 TypeScript errors**
- Vite build produces: `index.html` (0.42 kB), `index-B7f8T8LK.css` (175.6 kB), `index-BUhEYh7x.js` (1,091 kB)
- Only warnings: chunk size advisory and dynamic/static dual import advisory (both non-blocking)
