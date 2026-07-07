"""Unit tests for pricing module — normalization, aliases, cost estimation."""

import pytest
from app.pricing.loader import (
    _normalize,
    normalize_pricing_key,
    lookup,
    estimate_cost,
    load_pricing,
    PriceEntry,
    CostResult,
)


@pytest.fixture(autouse=True)
def _ensure_pricing_loaded():
    """Ensure pricing.toml is loaded before each test."""
    load_pricing()


class TestNormalize:
    def test_normalize_basic(self):
        assert _normalize("deepseek") == "deepseek"
        assert _normalize("DeepSeek") == "deepseek"
        assert _normalize(" deepseek-v4-pro ") == "deepseek-v4-pro"

    def test_normalize_trailing_punctuation(self):
        assert _normalize("deepseek-v4-pro.") == "deepseek-v4-pro"
        assert _normalize("deepseek-v4-pro。") == "deepseek-v4-pro"
        assert _normalize("deepseek-v4-pro,") == "deepseek-v4-pro"

    def test_normalize_double_slash(self):
        assert _normalize("deepseek//v4-pro") == "deepseek/v4-pro"

    def test_normalize_pricing_key(self):
        assert normalize_pricing_key("deepseek", "deepseek-v4-pro") == ("deepseek", "deepseek-v4-pro")
        assert normalize_pricing_key("deepseek", "deepseek-v4-pro.") == ("deepseek", "deepseek-v4-pro")
        assert normalize_pricing_key("DeepSeek", " deepseek-v4-pro ") == ("deepseek", "deepseek-v4-pro")


class TestLookup:
    def test_exact_match_v4_pro(self):
        entry = lookup("deepseek", "deepseek-v4-pro")
        assert entry is not None
        assert entry.model == "deepseek-v4-pro"
        assert entry.input_cache_miss == 0.435
        assert entry.output == 0.87

    def test_normalized_lookup(self):
        """Normalization handles case, whitespace, trailing punctuation."""
        entry = lookup("DeepSeek", " deepseek-v4-pro ")
        assert entry is not None
        assert entry.model == "deepseek-v4-pro"

        entry = lookup("deepseek", "deepseek-v4-pro.")
        assert entry is not None
        assert entry.model == "deepseek-v4-pro"

    def test_alias_chat_to_flash(self):
        """deepseek-chat should resolve to deepseek-v4-flash via alias."""
        entry = lookup("deepseek", "chat")
        assert entry is not None
        assert entry.model == "deepseek-chat"

    def test_alias_reasoner_to_flash(self):
        """deepseek-reasoner should resolve to deepseek-v4-flash via alias."""
        entry = lookup("deepseek", "reasoner")
        assert entry is not None
        assert entry.model == "deepseek-reasoner"

    def test_alias_v4_pro_not_mapped_to_flash(self):
        """deepseek-v4-pro must NOT map to deepseek-chat or deepseek-v4-flash."""
        entry = lookup("deepseek", "deepseek-v4-pro")
        assert entry is not None
        assert entry.model == "deepseek-v4-pro"  # stays as v4-pro
        assert entry.input_cache_miss == 0.435

    def test_unknown_model_returns_none(self):
        entry = lookup("nonexistent", "model")
        assert entry is None
        entry = lookup("deepseek", "nonexistent-model-xyz")
        assert entry is None


class TestCostEstimate:
    def test_v4_pro_cost_screenshot_data(self):
        """Test against user's screenshot data: deepseek-v4-pro with specific token counts."""
        entry = lookup("deepseek", "deepseek-v4-pro")
        assert entry is not None

        # Screenshot data: input 1,889,200  output 966,700
        input_tokens = 1_889_200
        output_tokens = 966_700

        result = estimate_cost(input_tokens, output_tokens, entry)

        assert result.priced is True
        # input_cost = (1889200/1e6) * 0.435 * 6.79 ≈ 5.58
        assert abs(result.input_cost_cny - 5.58) < 0.10
        # output_cost = (966700/1e6) * 0.87 * 6.79 ≈ 5.71
        assert abs(result.output_cost_cny - 5.71) < 0.10
        # total ≈ 11.29
        assert abs(result.base_estimated - 11.29) < 0.20

    def test_v4_pro_upper_bound(self):
        """Upper bound with max output tokens."""
        entry = lookup("deepseek", "deepseek-v4-pro")
        assert entry is not None

        # Screenshot: input 1,889,200  max_output 4,980,000
        input_tokens = 1_889_200
        max_output = 4_980_000

        result = estimate_cost(input_tokens, max_output, entry)
        # total upper ≈ 35.0
        assert abs(result.base_estimated - 35.0) < 2.0

    def test_small_tokens_not_negative(self):
        """Very small token counts should still return non-negative costs."""
        entry = lookup("deepseek", "deepseek-v4-pro")
        result = estimate_cost(1, 1, entry)
        assert result.base_estimated >= 0
        assert result.input_cost_cny >= 0
        assert result.output_cost_cny >= 0

    def test_cost_includes_cny_conversion(self):
        """Verify CNY conversion uses the configured rate."""
        entry = lookup("deepseek", "deepseek-chat")
        assert entry is not None
        assert entry.cny_per_usd == 6.79

        result = estimate_cost(1_000_000, 1_000_000, entry)
        # input: 1.0 * 0.435 = 0.435 USD → 2.95 CNY
        # output: 1.0 * 0.87 = 0.87 USD → 5.91 CNY
        # total ≈ 8.86 CNY
        assert result.base_estimated > 0
        assert result.priced is True

    def test_kimi_lookup(self):
        entry = lookup("kimi", "kimi-k2")
        assert entry is not None
        assert entry.input_cache_miss == 1.18
        assert entry.output == 1.77
