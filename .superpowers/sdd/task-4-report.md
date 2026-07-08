# Task 4 Report: Frontend API Types + Quick Cards

## Summary

Added frontend API types, async functions, and quick card UI for the Circuit → Connection Extraction feature.

## Files Modified

### 1. `frontend/src/api/endpoints.ts`

Added the following TypeScript interfaces:
- `CircuitConnectionExtractionRequest` — request body for /run endpoint
- `CircuitConnectionExtractionStartResponse` — async start response
- `CircuitConnectionExtractionItem` — per-circuit result item
- `CircuitConnectionExtractionRun` — run summary
- `CircuitConnectionExtractionRunDetail` — run detail with items
- `CircuitConnectionExtractionRunListResponse` — paginated list

Added the following async functions:
- `runCircuitConnectionExtraction(body)` → POST `/api/llm-extraction/circuit-connection-extraction/run`
- `listCircuitConnectionExtractionRuns(params?)` → GET `/api/llm-extraction/circuit-connection-extraction/runs`
- `getCircuitConnectionExtractionRun(runId)` → GET `/api/llm-extraction/circuit-connection-extraction/runs/{runId}`
- `cancelCircuitConnectionExtractionRun(runId)` → POST `/api/llm-extraction/circuit-connection-extraction/runs/{runId}/cancel`

### 2. `frontend/src/pages/LlmExtractionPage.tsx`

- Added import for `CircuitConnectionExtractionModal` (will be created in Task 5)
- Added three state variables: `circuitSubTab`, `extractionModalOpen`, `extractionMode`
- Added a sub-tab toggle UI with two buttons: [回路数据浏览] and [回路→连接提取] in the mirror data tab section
- When 'connection-extraction' sub-tab is active, shows two quick cards:
  - 🔗 多连接提取 card (mode: multi_connection)
  - 🎯 主连接对提取 card (mode: main_pair)
- When a quick card is clicked, opens a `CircuitConnectionExtractionModal` (modal component deferred to Task 5)

### 3. `frontend/src/styles.css`

Added CSS classes for the circuit connection extraction quick cards:
- `.llm-quick-cards` — flex container
- `.llm-quick-card-icon` — icon in quick card
- `.llm-quick-card-title` — title in quick card
- `.llm-quick-card-desc` — description in quick card
- `.llm-quick-card-features` — feature list in quick card

## Verification

- `npx tsc --noEmit` passes with 0 errors
- The missing modal component import (`CircuitConnectionExtractionModal`) is declared with a comment noting it will be created in Task 5

## Next Steps

- Task 5: Create the actual `CircuitConnectionExtractionModal` wizard component in `frontend/src/pages/llm-extraction/components/`
