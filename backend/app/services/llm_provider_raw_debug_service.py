"""Isolated provider raw-text diagnostic — no DB, no workflow, no JSON parsing."""

from __future__ import annotations

from typing import Any

from app.schemas.llm_extraction import ProviderRawDebugRequest, ProviderRawDebugResponse
from app.services.llm_json_utils import raw_response_preview
from app.services.llm_providers import UnknownProviderError, get_llm_provider
from app.services.llm_providers.base import LlmProviderTextResult, ProviderNotConfiguredError

RAW_TEXT_PREVIEW_MAX = 2000


def _json_mode_from_response_format(response_format: dict[str, Any] | None) -> bool:
    if not response_format:
        return False
    return response_format.get("type") == "json_object"


def text_result_to_debug_dict(result: LlmProviderTextResult) -> dict[str, Any]:
    raw_text = result.raw_text or ""
    preview = result.raw_response_preview or raw_response_preview(raw_text)
    if len(preview) > RAW_TEXT_PREVIEW_MAX:
        preview = raw_response_preview(preview)
    keys = result.response_payload.get("raw_response_keys")
    if not isinstance(keys, list):
        keys = []
    return {
        "provider": result.provider,
        "model_name": result.model,
        "transport_ok": result.transport_ok,
        "raw_text": raw_text or None,
        "raw_text_preview": preview or None,
        "response_char_count": len(raw_text),
        "finish_reason": result.finish_reason,
        "usage": result.usage.as_dict() if result.usage else {},
        "error": result.error,
        "fallback_raw_response_used": bool(result.fallback_raw_response_used),
        "raw_response_keys": [str(k) for k in keys],
        "latency_ms": result.latency_ms,
    }


def build_provider_raw_debug_response(
    *,
    provider: str,
    model_name: str,
    result: LlmProviderTextResult,
) -> ProviderRawDebugResponse:
    raw_text = result.raw_text or ""
    preview = result.raw_response_preview or raw_response_preview(raw_text)
    keys = result.response_payload.get("raw_response_keys")
    if not isinstance(keys, list):
        keys = []
    return ProviderRawDebugResponse(
        provider=provider,
        model_name=model_name or result.model,
        transport_ok=result.transport_ok,
        raw_text_present=bool(raw_text.strip()),
        raw_text_preview=preview or None,
        response_char_count=len(raw_text),
        finish_reason=result.finish_reason,
        usage=result.usage.as_dict() if result.usage else {},
        fallback_raw_response_used=bool(result.fallback_raw_response_used),
        error=result.error,
        raw_response_keys=[str(k) for k in keys],
        latency_ms=result.latency_ms,
    )


async def invoke_provider_raw_debug(body: ProviderRawDebugRequest) -> ProviderRawDebugResponse:
    provider_key = (body.provider or "deepseek").strip().lower()
    try:
        provider = get_llm_provider(provider_key)
    except UnknownProviderError as exc:
        return ProviderRawDebugResponse(
            provider=provider_key,
            model_name=body.model_name or "",
            transport_ok=False,
            raw_text_present=False,
            raw_text_preview=None,
            response_char_count=0,
            finish_reason=None,
            usage={},
            fallback_raw_response_used=False,
            error=str(exc),
            raw_response_keys=[],
        )

    json_mode = _json_mode_from_response_format(body.response_format)
    try:
        result = await provider.complete_text(
            model=body.model_name or "",
            system_prompt="You are a helpful assistant. Follow the user instruction exactly.",
            user_prompt=body.prompt,
            temperature=body.temperature,
            max_tokens=body.max_tokens,
            json_mode=json_mode,
        )
    except ProviderNotConfiguredError as exc:
        return ProviderRawDebugResponse(
            provider=provider_key,
            model_name=body.model_name or "",
            transport_ok=False,
            raw_text_present=False,
            raw_text_preview=None,
            response_char_count=0,
            finish_reason=None,
            usage={},
            fallback_raw_response_used=False,
            error=str(exc),
            raw_response_keys=[],
        )

    return build_provider_raw_debug_response(
        provider=provider_key,
        model_name=body.model_name or result.model,
        result=result,
    )
