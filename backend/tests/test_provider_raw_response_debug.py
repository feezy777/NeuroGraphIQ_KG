"""Tests for isolated provider raw-text debug endpoint (mock provider only)."""

from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from app.main import app
from app.schemas.llm_extraction import ProviderRawDebugRequest
from app.services.llm_provider_raw_debug_service import (
    RAW_TEXT_PREVIEW_MAX,
    invoke_provider_raw_debug,
    text_result_to_debug_dict,
)
from app.services.llm_providers.base import LlmProviderTextResult, LlmProviderUsage


def _text_result(
    raw_text: str,
    *,
    transport_ok: bool = True,
    error: str | None = None,
    fallback: bool = False,
) -> LlmProviderTextResult:
    return LlmProviderTextResult(
        provider="deepseek",
        model="deepseek-chat",
        raw_text=raw_text,
        usage=LlmProviderUsage(prompt_tokens=1, completion_tokens=2, total_tokens=3),
        finish_reason="stop",
        transport_ok=transport_ok,
        error=error,
        raw_response_preview=raw_text[:2000],
        response_payload={
            "json_mode_enabled": True,
            "raw_response_keys": ["id", "choices", "usage", "model"],
        },
        request_payload_redacted={"model": "deepseek-chat", "json_mode_enabled": True},
        latency_ms=12,
        fallback_raw_response_used=fallback,
    )


def test_text_result_to_debug_dict_includes_raw_text_without_json_parse():
    payload = '{"ok": true}'
    result = _text_result(payload)
    out = text_result_to_debug_dict(result)
    assert out["raw_text"] == payload
    assert out["raw_text_preview"] == payload
    assert out["response_char_count"] == len(payload)
    assert out["transport_ok"] is True
    assert out["raw_response_keys"] == ["id", "choices", "usage", "model"]
    assert "parsed" not in out


def test_raw_text_preview_truncated_to_2000():
    long_text = "x" * 5000
    result = _text_result(long_text)
    out = text_result_to_debug_dict(result)
    assert len(out["raw_text_preview"] or "") <= RAW_TEXT_PREVIEW_MAX + 64


def test_invoke_provider_raw_debug_success():
    mock_provider = AsyncMock()
    mock_provider.complete_text = AsyncMock(return_value=_text_result('{"ok": true}'))
    with patch(
        "app.services.llm_provider_raw_debug_service.get_llm_provider",
        return_value=mock_provider,
    ):
        resp = asyncio.run(
            invoke_provider_raw_debug(
                ProviderRawDebugRequest(
                    provider="deepseek",
                    model_name="deepseek-chat",
                    prompt='请只输出一个 JSON object：{"ok": true}',
                    response_format={"type": "json_object"},
                )
            )
        )
    assert resp.raw_text_present is True
    assert resp.response_char_count > 0
    assert resp.raw_text_preview
    assert resp.transport_ok is True
    assert resp.error is None
    mock_provider.complete_text.assert_awaited_once()
    call_kwargs = mock_provider.complete_text.await_args.kwargs
    assert call_kwargs["json_mode"] is True


def test_invoke_provider_raw_debug_structured_provider_error():
    mock_provider = AsyncMock()
    mock_provider.complete_text = AsyncMock(
        return_value=_text_result("", transport_ok=False, error="DeepSeek returned HTTP 401")
    )
    with patch(
        "app.services.llm_provider_raw_debug_service.get_llm_provider",
        return_value=mock_provider,
    ):
        resp = asyncio.run(
            invoke_provider_raw_debug(
                ProviderRawDebugRequest(provider="deepseek", prompt="hello")
            )
        )
    assert resp.transport_ok is False
    assert resp.raw_text_present is False
    assert resp.error == "DeepSeek returned HTTP 401"


def test_debug_endpoint_returns_raw_text_present_without_db():
    client = TestClient(app)
    mock_provider = AsyncMock()
    mock_provider.complete_text = AsyncMock(return_value=_text_result('{"ok": true}'))
    with patch(
        "app.services.llm_provider_raw_debug_service.get_llm_provider",
        return_value=mock_provider,
    ):
        resp = client.post(
            "/api/llm-extraction/debug/provider-raw",
            json={
                "provider": "deepseek",
                "model_name": "deepseek-chat",
                "prompt": '请只输出一个 JSON object：{"ok": true}',
                "temperature": 0,
                "max_tokens": 256,
                "response_format": {"type": "json_object"},
            },
        )
    assert resp.status_code == 200
    body = resp.json()
    assert body["raw_text_present"] is True
    assert body["response_char_count"] > 0
    assert body["raw_text_preview"]
    assert "sk-" not in json.dumps(body)
    assert "api_key" not in json.dumps(body).lower()


def test_debug_endpoint_unknown_provider_structured_error():
    client = TestClient(app)
    resp = client.post(
        "/api/llm-extraction/debug/provider-raw",
        json={
            "provider": "unknown_provider_xyz",
            "prompt": "hello",
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["transport_ok"] is False
    assert body["raw_text_present"] is False
    assert body["error"]
