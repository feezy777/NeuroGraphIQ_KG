"""Load and query pricing configuration from pricing.toml.

All pricing is stored in USD. CNY estimates are computed at query time
using the configured `cny_per_usd` rate.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_PRICE_CACHE: dict[str, dict[str, dict[str, Any]]] = {}
_ALIAS_CACHE: dict[str, dict[str, str]] = {}  # provider → {alias → canonical_model}
_VERSION: str = "unknown"
_DEFAULT_CURRENCY: str = "USD"
_CNY_PER_USD: float = 6.79

_TOML_PATH = Path(__file__).resolve().parent / "pricing.toml"

#: Characters to strip from model/provider names during normalization.
_STRIP_CHARS = ".。,，/"


@dataclass(frozen=True)
class PriceEntry:
    provider: str
    model: str              # canonical model key
    input_cache_hit: float   # USD per 1M tokens
    input_cache_miss: float  # USD per 1M tokens
    output: float            # USD per 1M tokens
    currency: str = "USD"
    unit: str = "per_1m_tokens"
    source: str = ""
    checked_at: str = ""
    cny_per_usd: float = 6.79


@dataclass
class CostResult:
    """Result of a cost estimate, handling both priced and unpriced models."""
    priced: bool = True
    base_estimated: float = 0.0       # in CNY
    upper_bound: float = 0.0           # in CNY (max output, max retries)
    entry: PriceEntry | None = None
    price_missing: bool = False
    input_cost_cny: float = 0.0
    output_cost_cny: float = 0.0


def _normalize(s: str) -> str:
    """Normalize a provider or model name for lookup.

    - trim whitespace
    - lowercase
    - strip trailing punctuation (.,。,、,)
    - collapse repeated slashes
    """
    s = s.strip().lower()
    s = s.rstrip(_STRIP_CHARS).lstrip(_STRIP_CHARS)
    s = re.sub(r"/{2,}", "/", s)
    return s


def normalize_pricing_key(provider: str, model: str) -> tuple[str, str]:
    """Return (normalized_provider, normalized_model) for pricing lookup.

    >>> normalize_pricing_key("deepseek", "deepseek-v4-pro")
    ('deepseek', 'deepseek-v4-pro')
    >>> normalize_pricing_key("deepseek", "deepseek-v4-pro.")
    ('deepseek', 'deepseek-v4-pro')
    >>> normalize_pricing_key("DeepSeek", " deepseek-v4-pro ")
    ('deepseek', 'deepseek-v4-pro')
    """
    return _normalize(provider), _normalize(model)


def load_pricing() -> None:
    """Load pricing.toml into the module-level cache. Called at FastAPI startup."""
    global _VERSION, _PRICE_CACHE, _ALIAS_CACHE, _DEFAULT_CURRENCY, _CNY_PER_USD
    try:
        import tomllib
    except ImportError:
        import tomli as tomllib  # type: ignore[no-redef]

    if not _TOML_PATH.exists():
        logger.warning("[pricing] %s not found — pricing disabled", _TOML_PATH)
        _PRICE_CACHE = {}
        _ALIAS_CACHE = {}
        return

    raw = tomllib.loads(_TOML_PATH.read_text(encoding="utf-8"))
    _VERSION = raw.get("version", "unknown")
    _DEFAULT_CURRENCY = raw.get("default_currency", "USD")
    _CNY_PER_USD = float(raw.get("cny_per_usd", 6.79))

    # Load price entries
    parsed: dict[str, dict[str, dict[str, Any]]] = {}
    for provider_key, provider_val in raw.get("providers", {}).items():
        normalized_provider = _normalize(provider_key)
        models: dict[str, dict[str, Any]] = {}
        for model_key, model_val in provider_val.get("models", {}).items():
            normalized_model = _normalize(model_key)
            models[normalized_model] = {
                "input_cache_hit": float(model_val.get("input_cache_hit", 0)),
                "input_cache_miss": float(model_val.get("input_cache_miss", 0)),
                "output": float(model_val.get("output", 0)),
                "currency": raw.get("default_currency", "USD"),
                "unit": model_val.get("unit", "per_1m_tokens"),
                "source": model_val.get("source", ""),
                "checked_at": model_val.get("checked_at", ""),
                "cny_per_usd": _CNY_PER_USD,
            }
        parsed[normalized_provider] = models
    _PRICE_CACHE = parsed

    # Load aliases
    alias_parsed: dict[str, dict[str, str]] = {}
    for provider_key, aliases in raw.get("aliases", {}).items():
        np = _normalize(provider_key)
        alias_map: dict[str, str] = {}
        for alias_key, canonical in aliases.items():
            alias_map[_normalize(alias_key)] = _normalize(str(canonical))
        alias_parsed[np] = alias_map
    _ALIAS_CACHE = alias_parsed

    model_count = sum(len(m) for m in parsed.values())
    alias_count = sum(len(a) for a in alias_parsed.values())
    logger.info("[pricing] loaded version=%s with %d provider(s), %d model(s), %d alias(es)",
                _VERSION, len(parsed), model_count, alias_count)


def _resolve_alias(provider: str, model: str) -> str:
    """Resolve a model alias to its canonical key. Returns model unchanged if no alias."""
    provider_aliases = _ALIAS_CACHE.get(provider, {})
    return provider_aliases.get(model, model)


def lookup(provider: str, model: str) -> PriceEntry | None:
    """Look up a price entry with normalization and alias resolution.

    Returns None if the provider or model is not configured.
    """
    normalized_provider, normalized_model = normalize_pricing_key(provider, model)
    provider_models = _PRICE_CACHE.get(normalized_provider)
    if provider_models is None:
        return None

    # Try exact match first
    entry = provider_models.get(normalized_model)
    if entry is not None:
        return PriceEntry(
            provider=normalized_provider,
            model=normalized_model,
            input_cache_hit=entry["input_cache_hit"],
            input_cache_miss=entry["input_cache_miss"],
            output=entry["output"],
            currency=entry["currency"],
            unit=entry["unit"],
            source=entry["source"],
            checked_at=entry["checked_at"],
            cny_per_usd=entry.get("cny_per_usd", _CNY_PER_USD),
        )

    # Try alias resolution
    resolved = _resolve_alias(normalized_provider, normalized_model)
    if resolved != normalized_model:
        entry = provider_models.get(resolved)
        if entry is not None:
            return PriceEntry(
                provider=normalized_provider,
                model=resolved,  # canonical model
                input_cache_hit=entry["input_cache_hit"],
                input_cache_miss=entry["input_cache_miss"],
                output=entry["output"],
                currency=entry["currency"],
                unit=entry["unit"],
                source=entry["source"],
                checked_at=entry["checked_at"],
                cny_per_usd=entry.get("cny_per_usd", _CNY_PER_USD),
            )

    return None


def estimate_cost(input_tokens: int, output_tokens: int, entry: PriceEntry) -> CostResult:
    """Calculate estimated cost in CNY given token counts and a price entry.

    Uses cache-miss pricing by default (conservative).
    Prices are in USD; converted to CNY using the configured exchange rate.
    """
    usd_per_1m = entry.input_cache_miss
    input_cost_usd = (input_tokens / 1_000_000) * usd_per_1m
    output_cost_usd = (output_tokens / 1_000_000) * entry.output
    total_usd = input_cost_usd + output_cost_usd
    rate = entry.cny_per_usd
    return CostResult(
        priced=True,
        base_estimated=round(total_usd * rate, 4),
        upper_bound=round((input_cost_usd + output_cost_usd) * rate * 2, 4),  # rough 2× for max
        entry=entry,
        input_cost_cny=round(input_cost_usd * rate, 4),
        output_cost_cny=round(output_cost_usd * rate, 4),
    )


def get_version() -> str:
    return _VERSION


def get_cny_per_usd() -> float:
    return _CNY_PER_USD


def get_default_currency() -> str:
    return _DEFAULT_CURRENCY


def get_all_entries() -> list[dict[str, Any]]:
    """Return all configured price entries as a flat list (for API endpoint)."""
    result: list[dict[str, Any]] = []
    for provider, models in _PRICE_CACHE.items():
        for model, entry in models.items():
            result.append({
                "provider": provider,
                "model": model,
                **entry,
            })
    return result
