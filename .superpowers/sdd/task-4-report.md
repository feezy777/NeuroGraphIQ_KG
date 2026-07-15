# Task 4 Report: Chat Panel + State Machine for SymptomQueryPage

## Changes Made

**File:** `frontend/src/pages/SymptomQueryPage.tsx`

### What was done

1. **Replaced single-line symptom input** with a multi-turn chat panel
2. **Added state machine** (`idle` -> `chatting` -> `summarizing` -> `analyzing` -> `results`)
3. **Added state variables:**
   - `phase` — current stage of the interaction
   - `messages` — chat history as `{role, content}[]`
   - `summary` — editable AI-generated symptom summary
   - `chatInput` — controlled input for chat text
   - `chatLoading` — loading indicator for send
   - `chatEndRef` — scroll anchor for auto-scroll
4. **Added handlers:**
   - `handleSend` — sends messages to `/api/symptom-query/conversation`, handles `asking` and `summarizing` stages
   - `handleConfirm` — auto-chains `/analyze` -> `/expand` -> `/search` -> `/graph` on confirmation
   - `handleContinueChat` — returns to chatting phase for more refinement
   - `handleClear` — resets all state to idle
5. **Replaced the top card** with:
   - Chat bubble display (user right blue, AI left gray) with auto-scroll
   - Editable summary textarea with "确认并开始分析" / "继续对话" buttons
   - Input bar with send/clear buttons, disabled during loading/analyzing
   - Analyzing spinner state
   - Collapsed "重新查询" `<details>` element in results phase
6. **Updated circuit list condition** to `phase === 'results' && circuits.length > 0`
7. **Updated empty state condition** to `phase === 'results' && circuits.length === 0 && ...`

### Verifications

- `npm run build` — exit 0 (TypeScript + Vite build passes)
- `pytest tests/test_symptom_query.py -q` — 5 passed
- Git commit: `8c27447` on branch `main`

### Files Changed

- `frontend/src/pages/SymptomQueryPage.tsx` (+115, -22)
