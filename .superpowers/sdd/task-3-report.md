# Task 3 Report: Pass temperature/maxTokens/prompt params to API calls

## Status: DONE

## Changes Made

File: `frontend/src/pages/llm-extraction/components/PoolExtractionModal.tsx`

### 1. `runSameGranularityFunctionExtraction` call (function extraction path)
Added three fields after `create_evidence: !dryRun,`:
- `temperature: temperature !== 0.7 ? temperature : undefined`
- `max_tokens: maxTokens !== 4096 ? maxTokens : undefined`
- `prompt_template_key: primaryTemplateKey || undefined`

### 2. Composite workflow payload
Added four fields after `create_evidence: !dryRun,`:
- `temperature: temperature !== 0.7 ? temperature : undefined`
- `max_tokens: maxTokens !== 4096 ? maxTokens : undefined`
- `prompt_template_key: primaryTemplateKey || undefined`
- `prompt_overrides: editingPrompt && primaryTemplateKey ? { [primaryTemplateKey]: customUserPrompt } : undefined`

### 3. `handleClose` prompt state reset
Added seven state resets after `setDryRun(false)`:
- `setTemperature(0.7)`
- `setMaxTokens(4096)`
- `setShowPromptPreview(false)`
- `setEditingPrompt(false)`
- `setCustomSystemPrompt('')`
- `setCustomUserPrompt('')`
- `setPromptTemplates([])`

## Verification
- `npm run build` passes with 0 TypeScript errors and 0 build errors (pre-existing chunk size warnings only).
- Non-default values only sent to API (defaults yield `undefined`, letting backend use its defaults).
- All state variables referenced already exist from prior implementation.
