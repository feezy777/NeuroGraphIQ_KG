# Task 3 Report: Delete old components and update CSS

## Status: DONE

## Steps Completed

### Step 1: Delete old component files
- Deleted `frontend/src/pages/llm-extraction/components/CandidatePoolBar.tsx`
- Deleted `frontend/src/pages/llm-extraction/components/FullExtractionModal.tsx`

### Step 2: Clean up CSS
Removed the following from `frontend/src/styles.css`:
- `.pool-bar` (entire block with all sub-styles: `.pool-bar-left`, `.pool-bar-icon`, `.pool-bar-info`, `.pool-bar-info strong`, `.pool-bar-actions`, `.pool-bar-btn`, `.pool-bar-btn:hover`, `.pool-bar-btn.primary`, `.pool-bar-btn.primary:hover`, `.pool-bar-btn.danger`, `.pool-bar-btn.danger:hover`, `.pool-bar-btn:disabled`)
- `.pool-bar-progress` and `.pool-bar-progress-text` blocks
- `@keyframes pool-progress-pulse`
- `.pool-row-marker` block

Kept (as instructed):
- `.pool-bar-progress-track`
- `.pool-bar-progress-fill`

### Step 3: Add pool-extraction-modal CSS
Added after `.modal-panel.wide`:
```css
.pool-extraction-modal .modal-panel {
  min-height: 520px;
}
```

### Step 4: Verify build
Built with `npm run build`. Expected TS errors present:
- `Cannot find module CandidatePoolBar` (to be fixed in Task 4)
- `Cannot find module FullExtractionModal` (to be fixed in Task 4)
- Pre-existing `listCandidates` error in `useCandidatePool.ts` (unrelated)

## Files Modified
- `frontend/src/pages/llm-extraction/components/CandidatePoolBar.tsx` -- deleted
- `frontend/src/pages/llm-extraction/components/FullExtractionModal.tsx` -- deleted
- `frontend/src/styles.css` -- removed pool-bar styles, added pool-extraction-modal CSS
