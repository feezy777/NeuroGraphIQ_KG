# Task 1 Report

## Status: DONE

## What was changed

### 1. New test file: `backend/tests/test_symptom_query.py`

Two mock-based tests following the FastAPI TestClient + monkeypatch pattern from the existing codebase:

- **`test_conversation_asking_stage`**: Mocks the LLM to return `{"stage":"asking","content":"Do you have tinnitus?","summary":null}`. Asserts 200, correct stage, content, and null summary.
- **`test_conversation_summarizing_stage`**: Mocks the LLM to return `{"stage":"summarizing","content":null,"summary":"Vestibular symptoms suggestive of BPPV"}`. Asserts 200, correct stage, null content, and the summary.

Mock helper `_mock_provider()` creates an `AsyncMock` provider whose `complete_json` returns an `LlmProviderResponse` with the specified `parsed_json`. Monkeypatch targets `app.routers.symptom_query.get_llm_provider`.

### 2. Modified: `backend/app/routers/symptom_query.py`

Added after the `/expand` endpoint (line 289):

- **`ConversationRequest`** schema: `messages: list[dict[str, str]]`, `granularity_level: str = "macro"`
- **`ConversationResponse`** schema: `stage: str`, `content: str | None`, `summary: str | None`
- **`CONVERSATION_PROMPT`** constant: Instructs the LLM to act as a clinical neuroscientist, ask one question per turn, produce summary after 2-4 exchanges, reply JSON only.
- **`POST /conversation`** endpoint: Uses the same DeepSeek provider/config pattern as `/analyze` and `/expand`. Handles JSON parsing with `_array` unwrap and `ast.literal_eval` fallback. On error: graceful fallback using raw user messages as summary.

## Test summary

```
2 passed, 0 failed (1.40s)
```

Pre-existing failures (10) in `test_llm_field_completion`, `test_llm_circuit_projection_extraction`, `test_llm_projection_circuit_extraction`, `test_llm_projection_function_extraction`, and `test_resource_registry` -- unrelated to this change.

## Build verification

```
cd backend && .venv/Scripts/python.exe -c "import app.main; print('OK')"
→ OK
```

## Concerns

None. All changes follow existing patterns in the codebase (`/analyze` and `/expand` endpoints). The error fallback matches the spec requirement for graceful degradation.
