"""Tests for POST /api/symptom-query/conversation — mocked LLM, no real DeepSeek."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock

from fastapi.testclient import TestClient

from app.main import app
from app.services.llm_providers.base import LlmProviderResponse, LlmProviderUsage


def _mock_provider(parsed_json: dict) -> AsyncMock:
    """Build an AsyncMock provider whose complete_json returns a given parsed_json."""
    provider = AsyncMock()
    provider.complete_json.return_value = LlmProviderResponse(
        provider="deepseek",
        model="test-model",
        raw_text=json.dumps(parsed_json, ensure_ascii=False),
        parsed_json=parsed_json,
        usage=LlmProviderUsage(),
        finish_reason="stop",
        request_payload_redacted={},
        response_payload={},
        latency_ms=0,
    )
    return provider


def test_conversation_asking_stage(monkeypatch):
    """LLM returns asking stage — endpoint responds with a follow-up question."""
    mock_provider = _mock_provider({
        "stage": "asking",
        "content": "Do you have tinnitus?",
        "summary": None,
    })
    monkeypatch.setattr(
        "app.routers.symptom_query.get_llm_provider",
        lambda _name: mock_provider,
    )

    client = TestClient(app)
    resp = client.post("/api/symptom-query/conversation", json={
        "messages": [
            {"role": "user", "content": "I have dizziness when I stand up."},
        ],
        "granularity_level": "macro",
    })

    assert resp.status_code == 200
    data = resp.json()
    assert data["stage"] == "asking"
    assert data["content"] == "Do you have tinnitus?"
    assert data["summary"] is None


def test_conversation_empty_messages_returns_asking():
    """Empty messages list triggers early return with an asking response."""
    client = TestClient(app)
    resp = client.post("/api/symptom-query/conversation", json={
        "messages": [],
        "granularity_level": "macro",
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["stage"] == "asking"
    assert data["content"] is not None


def test_conversation_llm_failure_fallback(monkeypatch):
    """LLM failure triggers graceful fallback using raw user messages as summary."""
    mock_provider = AsyncMock()
    mock_provider.complete_json = AsyncMock(side_effect=Exception("LLM down"))
    monkeypatch.setattr(
        "app.routers.symptom_query.get_llm_provider",
        lambda name: mock_provider,
    )
    monkeypatch.setattr(
        "app.routers.symptom_query.get_deepseek_runtime_config",
        lambda: type("C", (), {"api_key": "sk-test", "default_model": "deepseek-chat"})(),
    )

    client = TestClient(app)
    resp = client.post("/api/symptom-query/conversation", json={
        "messages": [{"role": "user", "content": "I feel dizzy"}],
        "granularity_level": "macro",
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["stage"] == "summarizing"
    assert "dizzy" in (data["summary"] or "").lower()


def test_conversation_summarizing_stage(monkeypatch):
    """LLM returns summarizing stage — endpoint responds with a clinical summary."""
    mock_provider = _mock_provider({
        "stage": "summarizing",
        "content": None,
        "summary": "Vestibular symptoms suggestive of BPPV",
    })
    monkeypatch.setattr(
        "app.routers.symptom_query.get_llm_provider",
        lambda _name: mock_provider,
    )

    client = TestClient(app)
    resp = client.post("/api/symptom-query/conversation", json={
        "messages": [
            {"role": "user", "content": "I have dizziness when I stand up."},
            {"role": "assistant", "content": "Does the room spin or do you feel faint?"},
            {"role": "user", "content": "The room spins for about 30 seconds."},
        ],
        "granularity_level": "macro",
    })

    assert resp.status_code == 200
    data = resp.json()
    assert data["stage"] == "summarizing"
    assert data["content"] is None
    assert data["summary"] == "Vestibular symptoms suggestive of BPPV"
