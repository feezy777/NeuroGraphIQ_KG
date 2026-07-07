"""DeepSeek LLM provider (OpenAI-compatible chat completions)."""

from __future__ import annotations

import json
import logging
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
from app.services.settings_service import get_deepseek_runtime_config

logger = logging.getLogger(__name__)


def supports_json_object_mode() -> bool:
    """DeepSeek chat completions support OpenAI-style JSON object mode."""
    return True


def _try_parse_json(raw: str) -> dict[str, Any] | None:
    from app.services.llm_json_utils import parse_llm_json_response

    try:
        return parse_llm_json_response(raw)
    except (json.JSONDecodeError, ValueError):
        return None


def extract_raw_text_from_response(body: Any, *, http_text: str = "") -> tuple[str, bool]:
    """Extract assistant text from DeepSeek/OpenAI-style chat completion payloads."""
    fallback_used = False
    if isinstance(body, dict):
        choices = body.get("choices")
        if isinstance(choices, list) and choices:
            first = choices[0] or {}
            if isinstance(first, dict):
                message = first.get("message")
                if isinstance(message, dict):
                    content = message.get("content")
                    if isinstance(content, str) and content.strip():
                        return content, False
                    # v4-pro reasoning model: answer may be in reasoning_content
                    reasoning = message.get("reasoning_content")
                    if isinstance(reasoning, str) and reasoning.strip():
                        return reasoning, False
                delta = first.get("delta")
                if isinstance(delta, dict):
                    content = delta.get("content")
                    if isinstance(content, str) and content.strip():
                        return content, False
        message = body.get("message")
        if isinstance(message, dict):
            content = message.get("content")
            if isinstance(content, str) and content.strip():
                return content, False
        for key in ("content", "text"):
            val = body.get(key)
            if isinstance(val, str) and val.strip():
                return val, False
    if http_text.strip():
        return http_text[:8000], True
    if body is not None:
        return str(body)[:8000], True
    return "", fallback_used


class DeepSeekProvider:
    name = "deepseek"

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
        text_result, _parsed = await self._complete_chat(
            model=model,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            temperature=temperature,
            max_tokens=max_tokens,
            timeout_seconds=timeout_seconds,
            json_mode=json_mode,
            parse_json=False,
        )
        return text_result

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
        text_result, parsed_json = await self._complete_chat(
            model=model,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            temperature=temperature,
            max_tokens=max_tokens,
            timeout_seconds=timeout_seconds,
            json_mode=supports_json_object_mode(),
            parse_json=True,
        )
        return LlmProviderResponse(
            provider=text_result.provider,
            model=text_result.model,
            raw_text=text_result.raw_text or "",
            parsed_json=parsed_json,
            usage=text_result.usage,
            finish_reason=text_result.finish_reason,
            request_payload_redacted=text_result.request_payload_redacted,
            response_payload={
                **text_result.response_payload,
                **({"fallback_raw_response_used": True} if text_result.fallback_raw_response_used else {}),
            },
            latency_ms=text_result.latency_ms,
            error_message=text_result.error,
            transport_ok=text_result.transport_ok,
            response_format=text_result.response_format,
        )

    async def _complete_chat(
        self,
        *,
        model: str,
        system_prompt: str,
        user_prompt: str,
        temperature: float,
        max_tokens: int,
        timeout_seconds: int,
        json_mode: bool,
        parse_json: bool,
    ) -> tuple[LlmProviderTextResult, dict[str, Any] | None]:
        config = get_deepseek_runtime_config()
        if not config.enabled:
            raise ProviderNotConfiguredError("DeepSeek provider is disabled in Settings.")
        api_key = (config.api_key or "").strip()
        if not api_key:
            raise ProviderNotConfiguredError(
                "DeepSeek API key is not configured; set it in Settings before extracting."
            )

        use_model = model or config.default_model
        base_url = config.base_url.rstrip("/")
        redacted = {
            "model": use_model,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "message_roles": ["system", "user"],
        }
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

        json_mode_enabled = bool(json_mode and supports_json_object_mode())
        json_mode_warning: str | None = None

        async def _post(client: httpx.AsyncClient, *, use_json_mode: bool) -> httpx.Response:
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
            if use_json_mode:
                payload["response_format"] = {"type": "json_object"}
            return await client.post(
                f"{base_url}/chat/completions",
                json=payload,
                headers=headers,
            )

        # Unified timeout: all models >=120s, reasoning models >=180s
        _MODEL_MIN_TIMEOUT = {'deepseek-v4-pro': 180, 'deepseek-reasoner': 180}
        resolved_timeout = max(timeout_seconds or config.timeout_seconds or 120,
                               _MODEL_MIN_TIMEOUT.get(use_model, 120))
        started = time.monotonic()
        logger.info(
            "[deepseek] POST chat/completions model=%s user_chars=%s json_mode=%s timeout=%ss",
            use_model,
            len(user_prompt),
            json_mode_enabled,
            resolved_timeout,
        )
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(resolved_timeout, connect=15.0),
            trust_env=False,
        ) as client:
            try:
                resp = await _post(client, use_json_mode=json_mode_enabled)
                if json_mode_enabled and resp.status_code >= 400:
                    body_text = resp.text[:500].lower()
                    if "response_format" in body_text or resp.status_code == 400:
                        logger.warning(
                            "[deepseek] JSON mode rejected (HTTP %s); retrying without response_format",
                            resp.status_code,
                        )
                        json_mode_warning = (
                            f"DeepSeek JSON mode unavailable (HTTP {resp.status_code}); "
                            "retried without response_format."
                        )
                        json_mode_enabled = False
                        resp = await _post(client, use_json_mode=False)
            except httpx.HTTPError as exc:
                latency_ms = int((time.monotonic() - started) * 1000)
                return LlmProviderTextResult(
                    provider=self.name,
                    model=use_model,
                    raw_text=None,
                    usage=LlmProviderUsage(),
                    finish_reason=None,
                    transport_ok=False,
                    error=f"DeepSeek request failed: {exc}",
                    request_payload_redacted={**redacted, "json_mode_enabled": json_mode_enabled},
                    response_payload={"json_mode_enabled": json_mode_enabled},
                    latency_ms=latency_ms,
                ), None

        latency_ms = int((time.monotonic() - started) * 1000)
        if resp.status_code >= 400:
            raw_text, fallback_used = extract_raw_text_from_response(None, http_text=resp.text)
            return LlmProviderTextResult(
                provider=self.name,
                model=use_model,
                raw_text=raw_text or resp.text[:2000] or None,
                usage=LlmProviderUsage(),
                finish_reason=None,
                transport_ok=False,
                error=f"DeepSeek returned HTTP {resp.status_code}",
                raw_response_preview=raw_response_preview(raw_text or resp.text[:2000]),
                request_payload_redacted={**redacted, "json_mode_enabled": json_mode_enabled},
                response_payload={
                    "status_code": resp.status_code,
                    "json_mode_enabled": json_mode_enabled,
                },
                latency_ms=latency_ms,
                fallback_raw_response_used=fallback_used,
            ), None

        try:
            body = resp.json()
        except ValueError:
            raw_text, fallback_used = extract_raw_text_from_response(None, http_text=resp.text)
            return LlmProviderTextResult(
                provider=self.name,
                model=use_model,
                raw_text=raw_text or resp.text[:2000] or None,
                usage=LlmProviderUsage(),
                finish_reason=None,
                transport_ok=True,
                error="DeepSeek response was not valid JSON",
                raw_response_preview=raw_response_preview(raw_text or resp.text[:2000]),
                request_payload_redacted={**redacted, "json_mode_enabled": json_mode_enabled},
                response_payload={"json_mode_enabled": json_mode_enabled},
                latency_ms=latency_ms,
                fallback_raw_response_used=fallback_used,
            ), None

        raw_text, fallback_used = extract_raw_text_from_response(body, http_text=resp.text)
        finish = None
        choices = body.get("choices") if isinstance(body, dict) else None
        if isinstance(choices, list) and choices and isinstance(choices[0], dict):
            finish = choices[0].get("finish_reason")

        usage_raw = body.get("usage") or {} if isinstance(body, dict) else {}
        usage = LlmProviderUsage(
            prompt_tokens=usage_raw.get("prompt_tokens"),
            completion_tokens=usage_raw.get("completion_tokens"),
            total_tokens=usage_raw.get("total_tokens"),
        )
        response_payload: dict[str, Any] = {
            "model": body.get("model") if isinstance(body, dict) else None,
            "usage": usage.as_dict(),
            "json_mode_enabled": json_mode_enabled,
        }
        if isinstance(body, dict):
            response_payload["raw_response_keys"] = list(body.keys())
        if json_mode_warning:
            response_payload["json_mode_warning"] = json_mode_warning
        if fallback_used:
            response_payload["fallback_raw_response_used"] = True

        parsed_json = _try_parse_json(raw_text) if parse_json and raw_text else None
        preview = raw_response_preview(raw_text) if raw_text else None
        return LlmProviderTextResult(
            provider=self.name,
            model=use_model,
            raw_text=raw_text or None,
            usage=usage,
            finish_reason=finish,
            transport_ok=True,
            error=None if raw_text else "DeepSeek response missing content",
            raw_response_preview=preview,
            response_format="json_object" if json_mode_enabled else None,
            request_payload_redacted={**redacted, "json_mode_enabled": json_mode_enabled},
            response_payload=response_payload,
            latency_ms=latency_ms,
            fallback_raw_response_used=fallback_used,
        ), parsed_json
