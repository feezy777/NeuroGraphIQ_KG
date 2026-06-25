"""Thin async DeepSeek (OpenAI-compatible) chat client.

Only responsibility: turn a system+user prompt into raw text + token usage.
It does NOT parse domain JSON, touch the DB, or know about candidates — keeping the
LLM transport decoupled from the candidate-side extraction service.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

import httpx

from app.config import get_deepseek_runtime_config


class DeepSeekConfigError(Exception):
    """Raised when DeepSeek is not configured (e.g. empty API key)."""


class DeepSeekCallError(Exception):
    """Raised when the DeepSeek HTTP call fails or returns an unusable body."""


@dataclass
class DeepSeekResult:
    content: str
    model: str
    prompt_tokens: int | None
    completion_tokens: int | None
    total_tokens: int | None
    latency_ms: int


async def chat_completion(
    *,
    system_prompt: str,
    user_prompt: str,
    model: str | None = None,
    temperature: float = 0.2,
    timeout: float = 60.0,
) -> DeepSeekResult:
    """Call DeepSeek chat completions and return raw content + usage.

    Raises DeepSeekConfigError when no API key is set so the API layer can return a
    clean, actionable error instead of crashing.
    """
    config = get_deepseek_runtime_config()
    api_key = (config.api_key or "").strip()
    if not api_key:
        raise DeepSeekConfigError(
            "DeepSeek API key is not configured; set it in Settings or backend/.env before extracting."
        )

    base_url = config.base_url.rstrip("/")
    use_model = model or config.default_model
    payload = {
        "model": use_model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": temperature,
        "response_format": {"type": "json_object"},
        "stream": False,
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    started = time.monotonic()
    # trust_env=False avoids Windows proxy interference (same fix as the E2E script).
    async with httpx.AsyncClient(timeout=timeout or config.timeout_seconds, trust_env=False) as client:
        try:
            resp = await client.post(
                f"{base_url}/chat/completions", json=payload, headers=headers
            )
        except httpx.HTTPError as exc:
            raise DeepSeekCallError(f"DeepSeek request failed: {exc}") from exc

    latency_ms = int((time.monotonic() - started) * 1000)

    if resp.status_code >= 400:
        raise DeepSeekCallError(
            f"DeepSeek returned HTTP {resp.status_code}: {resp.text[:500]}"
        )

    try:
        body = resp.json()
        content = body["choices"][0]["message"]["content"]
    except (ValueError, KeyError, IndexError, TypeError) as exc:
        raise DeepSeekCallError(
            f"DeepSeek response missing content: {resp.text[:500]}"
        ) from exc

    usage = body.get("usage") or {}
    return DeepSeekResult(
        content=content,
        model=body.get("model", use_model),
        prompt_tokens=usage.get("prompt_tokens"),
        completion_tokens=usage.get("completion_tokens"),
        total_tokens=usage.get("total_tokens"),
        latency_ms=latency_ms,
    )
