# Task 4: Frontend — Chat Panel + State Machine

Replace the single-line symptom input in SymptomQueryPage.tsx with a multi-turn chat panel backed by the new /conversation endpoint (from Task 1).

## Spec
- State machine: idle → chatting → summarizing → confirmed → analyzing → results
- Chat panel: message bubbles (user right blue, AI left gray), auto-scroll, input bar
- Confirmation card: when LLM returns summarizing stage, show editable summary textarea with "确认并开始分析" + "继续对话" buttons
- On confirm: auto-chain /analyze → /expand → /search → /graph
- "清空" resets all state to idle
- Analyzing phase: show spinner, disable input
- After results: collapsed "重新查询" details element

## Steps
1. Add state variables (phase, messages, summary, chatInput, chatLoading)
2. Replace the current search card with chat panel + confirmation card + spinner
3. Implement handleSend, handleConfirm, handleContinueChat, handleClear
4. `npm run build` → exit 0
5. `cd backend && ./.venv/Scripts/python.exe -m pytest tests/test_symptom_query.py -q` → 5 passed
6. Commit

IMPORTANT: Keep the existing circuit list, ForceGraph, and detail sidebar intact. Only replace the top input card.
