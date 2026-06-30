# Task 2: PoolExtractionModal — Report

## File Created

`frontend/src/pages/llm-extraction/components/PoolExtractionModal.tsx`

## Summary

Created the `PoolExtractionModal` component that replaces `CandidatePoolBar` and `FullExtractionModal`. The component manages the full pool extraction lifecycle through three states:

### Three Modal States

1. **`prepare`** — Pool member table with search/filter, select-all/select-none, add selected (via `onAddSelected` prop), remove selected (via `removePoolMembers` API). Model configuration via `ModelSelector` component with dry-run checkbox. Scope info display (atlas, granularity, candidate count, pair count).

2. **`progress`** — Polls `GET /api/llm-extraction/composite-workflows/runs/{runId}` every 2s. Shows progress bar, pack stats (processed/total/success/failed), timing (elapsed/avg-per-pack/remaining estimate), connections found, recent errors. Cancel button supported.

3. **`result`** — Final summary with status banner (success/partial/failure/cancelled), total packs, connections found, timing, error details.

### Key Implementation Details

- **Starting extraction**: Calls `startCompositeWorkflow` from `endpoints.ts` with `workflow_type: 'connection_with_function'`, provider/model/dry-run from config, and scope from pool metadata.
- **Polling**: `useEffect` with `setInterval(2000)` that fetches `getCompositeWorkflowRun` and extracts `result_summary` fields (`processed_pack_count`, `pack_count`, `provider_success_count`, `failed_pack_count`, `parsed_production_count`, `pack_summaries` errors).
- **Client-side timing**: `startTimeRef` captured at start, `elapsedSec = (Date.now() - startTimeRef.current) / 1000`, `avgPerPack = elapsed / processedPacks`, `remaining = avgPerPack * (total - processed)`.
- **Terminal detection**: Status check against a set of terminal statuses (`succeeded`, `failed`, `cancelled`, `partially_succeeded`, etc.).
- **Modal panel**: `minHeight: 520px` with `display: flex; flex-direction: column` for consistent sizing.
- **Member management**: Local memos of `CandidatePoolMember[]` synced from `pool.memberships`, filtered by search term on `candidate_id`. Remove calls `removePoolMembers` then refreshes locally with `getCandidatePool` followed by `onPoolRefresh()`.
- **Cleanup**: On close/return, `clearInterval` on polling ref, resets all local state.

### Exports

```typescript
export function PoolExtractionModal({ open, pool, pooledCandidateIds, provider, modelName, providers, onProviderChange, onModelChange, onPoolRefresh, selectedCount, onAddSelected, onClose }: Props): JSX.Element | null
```

### TypeScript

`npx tsc --noEmit --pretty` passes with **0 errors**.

### CSS Classes Used

- `.modal-overlay`, `.modal-panel.wide`, `.modal-header`, `.modal-footer`, `.modal-section`, `.modal-section-title`, `.modal-section-row`, `.btn-close`
- `.pool-bar-btn`, `.pool-bar-btn.primary`, `.pool-bar-btn.danger`
- `.pool-bar-progress-track`, `.pool-bar-progress-fill`
- `.form-input`

### Status

**DONE** — Component ready for integration.
