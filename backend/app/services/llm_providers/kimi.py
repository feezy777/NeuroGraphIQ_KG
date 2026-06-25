"""Kimi (Moonshot) LLM provider — OpenAI-compatible chat completions."""

from __future__ import annotations

import json
import time
from typing import Any

import httpx

from app.services.llm_json_utils import raw_response_preview
from app.services.llm_providers.base import (
    LlmProviderResponse,
    LlmProviderTextResult,
    LlmProviderUsage,
    ProviderNotConfiguredError,
)
from app.services.llm_providers.deepseek import extract_raw_text_from_response
from app.services.settings_service import get_kimi_runtime_config


def _try_parse_json(raw: str) -> dict[str, Any] | None:
    from app.services.llm_json_utils import parse_llm_json_response

    try:
        return parse_llm_json_response(raw)
    except (json.JSONDecodeError, ValueError):
        return None


class KimiProvider:
    name = "kimi"

    async def complete_text(
        self,
        *,
        model: str,
        system_prompt: str,
        user_prompt: str,
        temperature: float = 0.2,
        max_tokens: int = 2000,
        timeout_seconds: int = 60,
        json_mode: bool = False,
    ) -> LlmProviderTextResult:
        result = await self.complete_json(
            model=model,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            temperature=temperature,
            max_tokens=max_tokens,
            timeout_seconds=timeout_seconds,
        )
        preview = raw_response_preview(result.raw_text) if result.raw_text else None
        return LlmProviderTextResult(
            provider=result.provider,
            model=result.model,
            raw_text=result.raw_text or None,
            usage=result.usage,
            finish_reason=result.finish_reason,
            transport_ok=result.transport_ok,
            error=result.error_message,
            raw_response_preview=preview,
            response_format=result.response_format,
            request_payload_redacted=result.request_payload_redacted,
            response_payload=result.response_payload,
            latency_ms=result.latency_ms,
        )

    async def complete_json(
        self,
        *,
        model: str,
        system_prompt: str,
        user_prompt: str,
        temperature: float = 0.2,
        max_tokens: int = 2000,
        response_schema: dict[str, Any] | None = None,
        timeout_seconds: int = 60,
    ) -> LlmProviderResponse:
        config = get_kimi_runtime_config()
        if not config.enabled:
            raise ProviderNotConfiguredError("Kimi provider is disabled in Settings.")
        api_key = (config.api_key or "").strip()
        if not api_key:
            raise ProviderNotConfiguredError(
                "Kimi API key is not configured; set it in Settings or KIMI_API_KEY before extracting."
            )

        use_model = model or config.default_model
        base_url = config.base_url.rstrip("/")
        payload: dict[str, Any] = {
            "model": use_model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": False,
        }
        redacted = {
            "model": use_model,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "message_roles": ["system", "user"],
        }

        started = time.monotonic()
        async with httpx.AsyncClient(
            timeout=timeout_seconds or config.timeout_seconds,
            trust_env=False,
        ) as client:
            try:
                resp = await client.post(
                    f"{base_url}/chat/completions",
                    json=payload,
                    headers={
                        "Authorization": f"Bearer {api_key}",
                        "Content-Type": "application/json",
                    },
                )
            except httpx.HTTPError as exc:
                latency_ms = int((time.monotonic() - started) * 1000)
                return LlmProviderResponse(
                    provider=self.name,
                    model=use_model,
                    raw_text="",
                    parsed_json=None,
                    usage=LlmProviderUsage(),
                    finish_reason=None,
                    request_payload_redacted=redacted,
                    response_payload={},
                    latency_ms=latency_ms,
                    error_message=f"Kimi request failed: {exc}",
                )

        latency_ms = int((time.monotonic() - started) * 1000)
        if resp.status_code >= 400:
            return LlmProviderResponse(
                provider=self.name,
                model=use_model,
                raw_text=resp.text[:2000],
                parsed_json=None,
                usage=LlmProviderUsage(),
                finish_reason=None,
                request_payload_redacted=redacted,
                response_payload={"status_code": resp.status_code},
                latency_ms=latency_ms,
                error_message=f"Kimi returned HTTP {resp.status_code}",
            )

        try:
            body = resp.json()
            content, fallback_used = extract_raw_text_from_response(body, http_text=resp.text)
            finish = None
            choices = body.get("choices") if isinstance(body, dict) else None
            if isinstance(choices, list) and choices and isinstance(choices[0], dict):
                finish = choices[0].get("finish_reason")
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            return LlmProviderResponse(
                provider=self.name,
                model=use_model,
                raw_text=resp.text[:2000],
                parsed_json=None,
                usage=LlmProviderUsage(),
                finish_reason=None,
                request_payload_redacted=redacted,
                response_payload={},
                latency_ms=latency_ms,
                error_message=f"Kimi response missing content: {exc}",
            )

        usage_raw = body.get("usage") or {}
        usage = LlmProviderUsage(
            prompt_tokens=usage_raw.get("prompt_tokens"),
            completion_tokens=usage_raw.get("completion_tokens"),
            total_tokens=usage_raw.get("total_tokens"),
        )
        response_payload: dict[str, Any] = {"model": body.get("model"), "usage": usage.as_dict()}
        if fallback_used:
            response_payload["fallback_raw_response_used"] = True
        return LlmProviderResponse(
            provider=self.name,
            model=body.get("model", use_model),
            raw_text=content,
            parsed_json=_try_parse_json(content),
            usage=usage,
            finish_reason=finish,
            request_payload_redacted=redacted,
            response_payload=response_payload,
            latency_ms=latency_ms,
            transport_ok=True,
        )
