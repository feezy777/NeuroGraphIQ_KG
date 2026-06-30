# Task 2 Report: Temperature/MaxTokens sliders + prompt preview UI

**Status**: DONE

## What was changed

**File:** `frontend/src/pages/llm-extraction/components/PoolExtractionModal.tsx`

### Insertion 1: Advanced params section (高级参数)
Added between the Dry run checkbox `</label>` and the model config modal-section's closing `</div>` (inside the existing "模型配置" section):

- Temperature slider: range input 0-2, step 0.1, displays current value in blue
- Max Tokens slider: range input 256-8192, step 256, displays current value in blue
- Both use state variables (`temperature`, `maxTokens`) from Task 1

### Insertion 2: Collapsible prompt template preview section (提示词模板)
Added after the model config modal-section's closing `</div>`, inside the main container div:

- Collapsible header with `▾`/`▸` indicator, click to toggle
- Shows `primaryTemplate.key` when collapsed
- When expanded: template info, system prompt textarea (editable with "编辑/恢复默认" toggle), user prompt textarea
- Editing warning message when in edit mode
- Composite workflow notes for `connection_with_function` and `circuit_with_function_steps`

## Build verification

```
npm run build
```
- `tsc -b`: 0 TypeScript errors
- `vite build`: succeeded in 1.39s
- No new dependencies added

## Concerns

None. The implementation follows existing inline style patterns, all state variables from Task 1 are used correctly, and the build passes cleanly.
