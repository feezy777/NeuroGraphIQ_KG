# Task 1 Report

## What was changed

**File:** `frontend/src/pages/llm-extraction/components/PoolExtractionModal.tsx`

### 1. Imports (line 3 import block)
- Added `getExtractionPromptTemplates` (runtime import)
- Added `type ExtractionPromptTemplate` (type import)

### 2. State variables (after `localPoolId`, around line 219)
Added 7 new state variables under a `// ── Prompt engineering` section:
- `temperature` (default 0.7)
- `maxTokens` (default 4096)
- `showPromptPreview` (default false)
- `editingPrompt` (default false)
- `customSystemPrompt` (default '')
- `customUserPrompt` (default '')
- `promptTemplates` (typed as `ExtractionPromptTemplate[]`, default [])

### 3. Template mapping + effects + memo (between Lock panel height effect and Keep localMembers in sync effect)
- `WORKFLOW_PRIMARY_TEMPLATE` mapping: `Record<string, string>` mapping `workflowType` values to template keys
- `primaryTemplateKey` derived value from `WORKFLOW_PRIMARY_TEMPLATE[workflowType]`
- `useEffect` to load prompt templates via `getExtractionPromptTemplates('extraction')` on modal open
- `useMemo` to derive `primaryTemplate` from fetched templates by matching `primaryTemplateKey`
- `useEffect` to populate `customSystemPrompt` and `customUserPrompt` when `primaryTemplate` loads

## Build verification

Command: `cd frontend && npm run build`

**Result: PASS** — 0 TypeScript errors, build succeeds in 1.37s.

Pre-existing warnings (not related to this change):
- Dynamic import of `client.ts` by `useCandidatePool.ts`
- Chunk size > 500 kB

## Concerns

None. All changes are straightforward additions as specified in the brief. No existing functionality is modified.
