# Task 4: CandidatePoolBar Component

## Status: DONE

## Summary

Created `frontend/src/pages/llm-extraction/components/CandidatePoolBar.tsx` — a React component for displaying and interacting with candidate pools during LLM extraction.

## Details

- **File created**: `frontend/src/pages/llm-extraction/components/CandidatePoolBar.tsx`
- **Props interface**: `pool`, `pooledCount`, `selectedCount`, `isExtracting`, `progress`, and 4 callbacks (`onAddSelected`, `onFullExtract`, `onClearPool`, `onViewDetails`)
- **Two display modes**: Progress mode (during extraction with progress bar) and Idle mode (pool overview with action buttons)

## Adjustments from template

- Added `danger` prop to the `ConfirmDialog` for the clear pool confirmation (destructive action), using the existing prop from `ConfirmDialog`'s interface
- Verified `ConfirmDialog` props match the template (`open`, `title`, `message`, `confirmLabel`, `onConfirm`, `onCancel`)
- Verified `CandidatePool` type in `frontend/src/api/endpoints.ts` has all used fields (`source_atlas`, `granularity_level`, `pair_count`)

## TypeScript Check

- `npx tsc --noEmit --pretty` passed with zero errors
- No CandidatePoolBar-related errors
