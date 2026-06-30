# Task 1 Report: wizardStep type + remove prompt from step 2 + update step 2 footer

**Status:** DONE

## Changes Made

File: `frontend/src/pages/llm-extraction/components/PoolExtractionModal.tsx`

1. **Line 213** — Widened `wizardStep` type from `useState<1 | 2>(1)` to `useState<1 | 2 | 3>(1)`.

2. **Deleted the entire `{/* Prompt template preview */}` block** (was ~100 lines of JSX). Removed:
   - The collapsible header with `showPromptPreview` toggle
   - The system prompt textarea
   - The user prompt textarea
   - The editing warning
   - The composite workflow notes

3. **Changed step 2 footer** from:
   - `onClick={handleStartExtraction}` with text `开始提取 ({selectedExtractionIds.length} 区)` and `disabled` condition
   - to: `onClick={() => setWizardStep(3)}` with text `下一步`, no `disabled` condition.

## Build Verification

```
npm run build  ->  PASS  (0 TypeScript errors)
```

Build warnings (pre-existing, unrelated to these changes):
- Dynamic import warning for `client.ts`
- Chunk size warning (>500 kB)
