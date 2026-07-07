# P0 Wave 2 Report: Token Usage & Cost Visibility in PoolExtractionModal

## Summary

Added token usage and cost visibility to the PoolExtractionModal progress and result screens.

## Changes Made

**File:** `D:\Tool\Coding\IDE\PyCharm\NeuroGraphIQ_KG_V3_1\frontend\src\pages\llm-extraction\components\PoolExtractionModal.tsx`

1. **ProgressData interface** — Added 4 new fields: `estimatedInputTokens`, `estimatedOutputTokens`, `actualPromptTokens`, `actualCompletionTokens`

2. **Cost helper function** — Added `estimateCost()` using DeepSeek CN pricing (¥1/1M input, ¥2/1M output tokens)

3. **Initial state** — All 4 token fields initialized to 0 in the `useState<ProgressData>` initial object

4. **Polling effect** — Reads `estimated_input_tokens` and `estimated_output_tokens` from both live and terminal sources; reads `prompt_tokens` and `completion_tokens` from `result_summary` only after workflow completion

5. **Progress UI** — New "用量" (Usage) section showing estimated input/output tokens during extraction, plus actual tokens and cost estimate after completion

6. **Result UI** — New "费用" (Cost) section showing actual input/output tokens and total cost estimate when data is available

7. **Reset on start** — Token fields zeroed in both extraction paths (function pool workflow and composite workflow)

## Verification

- `npm run build` passes with 0 TypeScript errors
- No runtime logic changes to existing behavior — token fields are additive only
