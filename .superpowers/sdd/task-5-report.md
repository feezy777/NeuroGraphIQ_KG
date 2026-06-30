# Task 5 Report: FullExtractionModal Component

## Summary
Created `FullExtractionModal.tsx` — a modal dialog for triggering full connection extraction on a candidate pool.

## File Created
`frontend/src/pages/llm-extraction/components/FullExtractionModal.tsx`

## What It Does
- Displays a modal overlay when `open=true` and a `pool` is provided
- Shows extraction scope: atlas name, granularity, candidate count, pair count, estimated packs
- Embeds `ModelSelector` for provider/model selection (with `providers` prop to match actual interface)
- Includes Dry run checkbox (local state, not yet wired to backend)
- Includes extract content options: Connection (always checked, readonly) and Projection Function (optional checkbox)
- On confirm, calls `onConfirm(includeProjectionFunctions)` with the boolean flag
- Closes on overlay click, X button, or Cancel

## Key Design Decisions
- `providers` prop added to `Props` interface — required by `ModelSelector`'s actual signature (`providers: Array<{ name, configured, default_model }>`)
- `dryRun` state is local for now (no backend endpoint yet); parent can read it as a future prop if needed
- `includeProjFn` state is local; value is passed to `onConfirm` callback
- Uses existing CSS classes: `modal-overlay`, `modal-panel`, `modal-header`, `modal-footer`, `modal-section`, `modal-section-title`, `modal-section-row`, `btn-close`, `pool-bar-btn`, `primary`

## Verification
- `npx tsc --noEmit` passes with zero TypeScript errors
- All props match the actual `ModelSelector` interface (verified against `ModelSelector.tsx`)
- The `CandidatePool` type is imported from `../../../api/endpoints` and matches the actual interface

## Status
DONE
