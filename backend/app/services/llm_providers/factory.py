"""LLM provider factory."""

from __future__ import annotations

from app.services.llm_providers.base import LlmProvider, UnknownProviderError
from app.services.llm_providers.deepseek import DeepSeekProvider
from app.services.llm_providers.kimi import KimiProvider

_PROVIDERS: dict[str, LlmProvider] = {
    "deepseek": DeepSeekProvider(),
    "kimi": KimiProvider(),
}


def get_llm_provider(provider_name: str) -> LlmProvider:
    key = (provider_name or "").strip().lower()
    provider = _PROVIDERS.get(key)
    if provider is None:
        raise UnknownProviderError(provider_name)
    return provider
