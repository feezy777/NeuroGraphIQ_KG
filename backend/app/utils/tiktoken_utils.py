"""Token counting using tiktoken with per-model encoder selection."""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

#: Model → tiktoken encoding name mapping.
#: DeepSeek models use the same tokenizer as OpenAI's gpt-4o (o200k_base).
#: Kimi models use cl100k_base (GPT-4/GPT-3.5 tokenizer).
MODEL_ENCODING_MAP: dict[str, str] = {
    "deepseek-chat": "o200k_base",
    "deepseek-reasoner": "o200k_base",
    "deepseek-v4-pro": "o200k_base",
    "kimi-k2": "cl100k_base",
    "kimi-k2-thinking": "cl100k_base",
}

#: Fallback encoding when model not in map.
DEFAULT_ENCODING = "o200k_base"

_encoder_cache: dict[str, Any] = {}


def _get_encoder(encoding_name: str):
    """Lazy-load and cache tiktoken encoders."""
    if encoding_name not in _encoder_cache:
        try:
            import tiktoken
            _encoder_cache[encoding_name] = tiktoken.get_encoding(encoding_name)
        except ImportError:
            logger.warning("[tiktoken] tiktoken not installed — falling back to char-based estimate")
            return None
        except Exception:
            logger.exception("[tiktoken] failed to load encoding '%s'", encoding_name)
            return None
    return _encoder_cache[encoding_name]


def resolve_encoding_for_model(model: str) -> str:
    """Map a provider model name to a tiktoken encoding name."""
    return MODEL_ENCODING_MAP.get(model, DEFAULT_ENCODING)


def count_tokens(text: str, model: str = "") -> int:
    """Count tokens in a text string using tiktoken for the given model.

    Falls back to char/4 estimate if tiktoken is unavailable or encoding fails.
    """
    encoding_name = resolve_encoding_for_model(model) if model else DEFAULT_ENCODING
    encoder = _get_encoder(encoding_name)
    if encoder is not None:
        try:
            return len(encoder.encode(text))
        except Exception:
            logger.warning("[tiktoken] encode failed for model=%s — using fallback", model)
    return _fallback_count(text)


def count_tokens_in_payload(payload: dict[str, Any] | list[Any], model: str = "") -> int:
    """Count tokens in a full messages payload (system + user messages as JSON)."""
    import json
    text = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    return count_tokens(text, model=model)


def _fallback_count(text: str) -> int:
    """Conservative char-based token estimate (used when tiktoken unavailable)."""
    ascii_chars = sum(1 for c in text if ord(c) < 128)
    cjk_chars = len(text) - ascii_chars
    return max(1, int(ascii_chars / 4 + cjk_chars / 2))
