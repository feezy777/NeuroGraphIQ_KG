# Task 1: Backend — Conversation Endpoint

Add `POST /api/symptom-query/conversation` to `backend/app/routers/symptom_query.py`.

## Spec
- Accepts `{messages: [{role, content}], granularity_level}`
- Returns `{stage: "asking"|"summarizing", content: str|null, summary: str|null}`
- LLM prompt asks it to triage symptoms, ask ONE question per turn, produce summary after 2-4 exchanges
- On LLM failure: graceful fallback — use raw user messages as summary

## Steps
1. Create `backend/tests/test_symptom_query.py` with 2 mock tests (asking + summarizing stages)
2. Run: FAIL (404)
3. Add ConversationRequest/ConversationResponse schemas + CONVERSATION_PROMPT constant + endpoint
4. Run: 2 passed
5. `python -c "import app.main"` → OK
6. Commit
