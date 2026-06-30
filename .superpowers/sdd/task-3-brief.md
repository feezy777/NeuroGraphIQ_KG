# Task 3: Pass temperature/maxTokens/prompt params to API calls

**File to modify:** `frontend/src/pages/llm-extraction/components/PoolExtractionModal.tsx`

**Interfaces from Tasks 1-2 (already committed):**
- `temperature` (float, default 0.7)
- `maxTokens` (int, default 4096)
- `primaryTemplateKey` (string, e.g. 'same_granularity_connection_completion_v1')
- `editingPrompt` (bool)
- `customUserPrompt` (string)
- `customSystemPrompt` (string)

## Requirements

### 1. In `handleStartExtraction`, add params to `runSameGranularityFunctionExtraction` call

Find the function extraction path (around line ~554). In the object passed to `runSameGranularityFunctionExtraction({...})`, add three fields after `create_evidence`:

```typescript
          temperature: temperature !== 0.7 ? temperature : undefined,
          max_tokens: maxTokens !== 4096 ? maxTokens : undefined,
          prompt_template_key: primaryTemplateKey || undefined,
```

Exact insertion: after `create_evidence: !dryRun,` (the last field before `})`), add the three lines above with a trailing comma on the previous line if needed.

### 2. In `handleStartExtraction`, add params to composite workflow payload

Find `const payload = {` (around line ~586). The payload object currently ends with `create_evidence: !dryRun,`. Add after that line:

```typescript
        temperature: temperature !== 0.7 ? temperature : undefined,
        max_tokens: maxTokens !== 4096 ? maxTokens : undefined,
        prompt_template_key: primaryTemplateKey || undefined,
        prompt_overrides: editingPrompt && primaryTemplateKey
          ? { [primaryTemplateKey]: customUserPrompt }
          : undefined,
```

### 3. In `handleClose`, reset prompt state

Find the `handleClose` callback (around line ~1050). Inside the function, after `setDryRun(false)`, add:

```typescript
    setTemperature(0.7)
    setMaxTokens(4096)
    setShowPromptPreview(false)
    setEditingPrompt(false)
    setCustomSystemPrompt('')
    setCustomUserPrompt('')
    setPromptTemplates([])
```

## Global Constraints
- Build must pass: `cd D:\Tool\Coding\IDE\PyCharm\NeuroGraphIQ_KG_V3_1\frontend && npm run build` with 0 TypeScript errors
- Only pass non-default values to API (undefined for defaults keeps backend defaults)
- All state variables already exist

## Verification
```
cd D:\Tool\Coding\IDE\PyCharm\NeuroGraphIQ_KG_V3_1\frontend && npm run build
```
Expected: 0 TypeScript errors.
