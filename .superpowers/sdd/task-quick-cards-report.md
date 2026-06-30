# SDD Report: Quick Extraction Cards Refactor

## Status: DONE

## Changes Made

### 1. Created `frontend/src/pages/llm-extraction/components/QuickExtractionCards.tsx`
New standalone component with:
- Expand/collapse per card via `collapsed` state map
- Always-visible rendering (no `selectedCandidateIds.length >= 2` guard)
- Three cards: 脑区功能提取, 连接提取, 回路+步骤+功能
- Each card shows count requirement badge, toggle arrow, and action button
- Disabled state at opacity 0.55 with "暂不可用" button label

### 2. Updated `frontend/src/styles.css` (lines 10315-10379)
Replaced old `.llm-quick-*` CSS with new styles supporting:
- Column flex layout with collapsible body (`max-height` transition)
- `.llm-quick-card-disabled` for reduced opacity
- `.llm-quick-card-header` with hover state
- `.llm-quick-card-body-collapsed` for zero-height hidden state
- `.llm-quick-count` badge (gray pill)
- `.llm-quick-toggle` arrow indicator
- `.llm-quick-action-btn` with hover blue border

### 3. Updated `frontend/src/pages/LlmExtractionPage.tsx`
- Added import: `import { QuickExtractionCards } from './llm-extraction/components/QuickExtractionCards'`
- Replaced inline `<div className="llm-quick-extract-row">` block (3 buttons) with `<QuickExtractionCards>` component
- Removed `selectedCandidateIds.length >= 2` guard -- component now always visible when `activeDataTab === 'candidates'`
- Passes `selectedCount` prop and 3 callback props

## Verification

- `npx tsc --noEmit --pretty`: **0 errors**
- `npm run build`: **built in 1.35s** (zero errors, only pre-existing chunk size warning)

## Files Touched

| File | Action |
|------|--------|
| `frontend/src/pages/llm-extraction/components/QuickExtractionCards.tsx` | Created |
| `frontend/src/styles.css` | Modified |
| `frontend/src/pages/LlmExtractionPage.tsx` | Modified |
