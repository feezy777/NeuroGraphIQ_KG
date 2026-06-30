---
name: frontend-pool-extraction-modal
description: PoolExtractionModal component and frontend integration (June 2026)
metadata:
  type: project
---

# Frontend Pool Extraction Modal (2026-06-25)

## Component Architecture

### PoolExtractionModal (`frontend/src/pages/llm-extraction/components/PoolExtractionModal.tsx`)
Single modal with three states: `prepare` → `progress` → `result`. Replaces `CandidatePoolBar` + `FullExtractionModal` (both deleted).

**Props:** `open, pool, pooledCandidateIds, provider, modelName, providers, onProviderChange, onModelChange, onPoolRefresh, selectedCandidateIds, candidateLabels, onClose, workflowType`

**Key behaviors:**
- On open: auto-creates pool via `createCandidatePool` + `addPoolMembers` API, saves `localPoolId` to avoid duplicate creation
- "+ 添加选中" button: calls `handleAddSelected` which uses `pool?.id || localPoolId` fallback
- Start extraction: uses `displayMembers` for candidate IDs, calls `startCompositeWorkflow` with 2s polling
- Error sections: collapsible via `showErrors` state, default collapsed
- `handleClose`: resets `localPoolId`, `pendingMembers`, cancels polling

### QuickExtractionCards (`frontend/src/pages/llm-extraction/components/QuickExtractionCards.tsx`)
Always-visible cards with expand/collapse. Replaces inline buttons in LlmExtractionPage.

### Deleted Components
- `CandidatePoolBar.tsx` — replaced by pool indicator row in LlmExtractionPage
- `FullExtractionModal.tsx` — replaced by PoolExtractionModal

## Button Styles
All modal buttons use project-standard `llm-btn` classes:
- `llm-btn` — default
- `llm-btn llm-btn-primary` — primary action
- `llm-btn llm-btn-danger` — destructive action
- Do NOT use `pool-bar-btn` (CSS was removed)

## CSS Fixes
- Log console: dynamic `--log-console-actual-height` via ResizeObserver in `BottomLogConsole.tsx`
- Log console expanded padding: `var(--log-console-actual-height, var(--log-console-height-expanded))` fallback
- Modal: `.pool-extraction-modal .modal-panel { min-height: 520px }`

**Why:** User wanted pool management + extraction + progress all in one modal with organic integration.
**How to apply:** Check `LlmExtractionPage.tsx` for PoolExtractionModal rendering with all required props.
