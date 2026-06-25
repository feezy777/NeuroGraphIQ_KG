"""Local runtime settings service for the Workbench.

The settings file is intentionally local-only. Public helpers always return
masked API-key state; only transport code receives the resolved secret.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

import httpx

from app.config import get_settings
from app.schemas.settings import (
    DeepSeekConnectionTestRequest,
    DeepSeekConnectionTestResponse,
    DeepSeekRuntimeConfig,
    KimiRuntimeConfig,
    KimiRuntimeSettings,
    PublicApiProviderRuntimeSettings,
    PublicDeepSeekRuntimeSettings,
    PublicKimiRuntimeSettings,
    PublicRuntimeSettings,
    RuntimeSettings,
    RuntimeSettingsPatch,
)

BACKEND_ROOT = Path(__file__).resolve().parents[2]
RUNTIME_SETTINGS_PATH = BACKEND_ROOT / "data" / "runtime" / "settings.local.json"


def mask_api_key(api_key: str | None) -> str | None:
    key = (api_key or "").strip()
    if not key:
        return None
    prefix = key[:3] if len(key) >= 3 else "***"
    suffix = key[-4:] if len(key) >= 4 else key[-1:]
    return f"{prefix}****{suffix}"


def _read_file_settings() -> dict[str, Any]:
    if not RUNTIME_SETTINGS_PATH.exists():
        return {}
    try:
        data = json.loads(RUNTIME_SETTINGS_PATH.read_text("utf-8"))
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def load_runtime_settings() -> RuntimeSettings:
    return RuntimeSettings.model_validate(_read_file_settings())


def _write_runtime_settings(settings: RuntimeSettings) -> None:
    RUNTIME_SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    RUNTIME_SETTINGS_PATH.write_text(
        json.dumps(settings.model_dump(), ensure_ascii=False, indent=2),
        "utf-8",
    )


def _resolved_api_key(runtime_key: str, env_key: str = "") -> str:
    if runtime_key.strip():
        return runtime_key.strip()
    return (env_key or "").strip()


def to_public_runtime_settings(settings: RuntimeSettings) -> PublicRuntimeSettings:
    deepseek = settings.api_providers.deepseek
    kimi = settings.api_providers.kimi
    # Workbench "configured" reflects runtime file only — not deployment .env secrets.
    resolved_deepseek = deepseek.api_key.strip()
    resolved_kimi = kimi.api_key.strip()
    return PublicRuntimeSettings(
        api_providers=PublicApiProviderRuntimeSettings(
            deepseek=PublicDeepSeekRuntimeSettings(
                enabled=deepseek.enabled,
                base_url=deepseek.base_url,
                default_model=deepseek.default_model,
                api_key_configured=bool(resolved_deepseek),
                api_key_masked=mask_api_key(resolved_deepseek),
                timeout_seconds=deepseek.timeout_seconds,
                max_batch_size=deepseek.max_batch_size,
                temperature=deepseek.temperature,
                max_tokens=deepseek.max_tokens,
            ),
            kimi=PublicKimiRuntimeSettings(
                enabled=kimi.enabled,
                base_url=kimi.base_url,
                default_model=kimi.default_model,
                api_key_configured=bool(resolved_kimi),
                api_key_masked=mask_api_key(resolved_kimi),
                timeout_seconds=kimi.timeout_seconds,
                max_batch_size=kimi.max_batch_size,
                temperature=kimi.temperature,
                max_tokens=kimi.max_tokens,
            ),
        ),
        basic=settings.basic,
    )


def update_runtime_settings(payload: dict[str, Any] | RuntimeSettingsPatch) -> PublicRuntimeSettings:
    patch = (
        payload
        if isinstance(payload, RuntimeSettingsPatch)
        else RuntimeSettingsPatch.model_validate(payload)
    )
    current = load_runtime_settings()
    data = current.model_dump()

    if patch.basic is not None:
        for key, value in patch.basic.model_dump(exclude_none=True).items():
            data["basic"][key] = value

    if patch.api_providers and patch.api_providers.deepseek is not None:
        deepseek_patch = patch.api_providers.deepseek
        deepseek_data = deepseek_patch.model_dump(
            exclude={"api_key", "explicit_clear_api_key"}, exclude_none=True
        )
        data["api_providers"]["deepseek"].update(deepseek_data)
        if deepseek_patch.explicit_clear_api_key:
            data["api_providers"]["deepseek"]["api_key"] = ""
        elif deepseek_patch.api_key is not None and deepseek_patch.api_key.strip():
            data["api_providers"]["deepseek"]["api_key"] = deepseek_patch.api_key.strip()

    if patch.api_providers and patch.api_providers.kimi is not None:
        kimi_patch = patch.api_providers.kimi
        if "kimi" not in data["api_providers"]:
            data["api_providers"]["kimi"] = KimiRuntimeSettings().model_dump()
        kimi_data = kimi_patch.model_dump(
            exclude={"api_key", "explicit_clear_api_key"}, exclude_none=True
        )
        data["api_providers"]["kimi"].update(kimi_data)
        if kimi_patch.explicit_clear_api_key:
            data["api_providers"]["kimi"]["api_key"] = ""
        elif kimi_patch.api_key is not None and kimi_patch.api_key.strip():
            data["api_providers"]["kimi"]["api_key"] = kimi_patch.api_key.strip()

    updated = RuntimeSettings.model_validate(data)
    _write_runtime_settings(updated)
    return to_public_runtime_settings(updated)


def get_deepseek_runtime_config() -> DeepSeekRuntimeConfig:
    runtime = load_runtime_settings().api_providers.deepseek
    settings = get_settings()
    return DeepSeekRuntimeConfig(
        enabled=runtime.enabled,
        base_url=(runtime.base_url or settings.deepseek_base_url).rstrip("/"),
        default_model=runtime.default_model or settings.deepseek_default_model,
        api_key=_resolved_api_key(runtime.api_key, settings.deepseek_api_key),
        timeout_seconds=runtime.timeout_seconds,
        max_batch_size=runtime.max_batch_size,
        temperature=runtime.temperature,
        max_tokens=runtime.max_tokens,
    )


def get_kimi_runtime_config() -> KimiRuntimeConfig:
    runtime = load_runtime_settings().api_providers.kimi
    settings = get_settings()
    return KimiRuntimeConfig(
        enabled=runtime.enabled,
        base_url=(runtime.base_url or settings.kimi_base_url).rstrip("/"),
        default_model=runtime.default_model or settings.kimi_default_model,
        api_key=_resolved_api_key(runtime.api_key, settings.kimi_api_key),
        timeout_seconds=runtime.timeout_seconds,
        max_batch_size=runtime.max_batch_size,
        temperature=runtime.temperature,
        max_tokens=runtime.max_tokens,
    )


async def test_deepseek_connection(
    body: DeepSeekConnectionTestRequest,
) -> DeepSeekConnectionTestResponse:
    saved = get_deepseek_runtime_config()
    api_key = (body.api_key or saved.api_key or "").strip()
    model = (body.default_model or saved.default_model).strip()
    base_url = (body.base_url or saved.base_url).rstrip("/")

    if not api_key:
        return DeepSeekConnectionTestResponse(
            ok=False,
            model=model,
            error_message="DeepSeek API key is not configured.",
        )

    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": "Reply with the word ok."},
            {"role": "user", "content": "ping"},
        ],
        "temperature": 0,
        "max_tokens": 4,
        "stream": False,
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    started = time.monotonic()
    try:
        async with httpx.AsyncClient(
            timeout=saved.timeout_seconds,
            trust_env=False,
        ) as client:
            resp = await client.post(
                f"{base_url}/chat/completions",
                json=payload,
                headers=headers,
            )
        latency_ms = int((time.monotonic() - started) * 1000)
        if resp.status_code >= 400:
            return DeepSeekConnectionTestResponse(
                ok=False,
                model=model,
                latency_ms=latency_ms,
                error_message=f"DeepSeek returned HTTP {resp.status_code}.",
            )
        return DeepSeekConnectionTestResponse(ok=True, model=model, latency_ms=latency_ms)
    except httpx.HTTPError as exc:
        latency_ms = int((time.monotonic() - started) * 1000)
        return DeepSeekConnectionTestResponse(
            ok=False,
            model=model,
            latency_ms=latency_ms,
            error_message=f"DeepSeek request failed: {exc}",
        )
