"""Tests for the per-token cost lookup."""

from __future__ import annotations

from decimal import Decimal

from wiki.services.pricing import estimate_cost_usd


class TestPricing:
    def test_known_model_returns_estimate(self):
        # gpt-4o-mini: $0.15 in / $0.60 out per 1M tokens.
        # 1000 in + 500 out = 0.00015 + 0.00030 = 0.00045
        cost = estimate_cost_usd("gpt-4o-mini", 1000, 500)
        assert cost == Decimal("0.000450")

    def test_unknown_model_returns_zero(self):
        assert estimate_cost_usd("never-heard-of-it", 9999, 9999) == Decimal("0")

    def test_zero_tokens_returns_zero(self):
        assert estimate_cost_usd("gpt-4o-mini", 0, 0) == Decimal("0E-6")
