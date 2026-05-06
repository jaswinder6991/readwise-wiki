"""Best-effort per-token cost estimation.

This is a deliberately small lookup of common model rates so the LLMCall.cost_estimate_usd
field shows something useful in the admin. Unknown models return 0 — this is illustrative,
not a billing source. Update as you onboard new models.

Rates are USD per 1M tokens. Sources: provider pricing pages as of project setup; verify
against the current prices for your selected model/provider.
"""

from __future__ import annotations

from decimal import Decimal

# (input_per_million, output_per_million)
PRICING: dict[str, tuple[Decimal, Decimal]] = {
    # OpenAI
    "gpt-4o": (Decimal("2.50"), Decimal("10.00")),
    "gpt-4o-mini": (Decimal("0.15"), Decimal("0.60")),
    # Anthropic via OpenRouter
    "anthropic/claude-sonnet-4.6": (Decimal("3.00"), Decimal("15.00")),
    "anthropic/claude-haiku-4.5": (Decimal("0.80"), Decimal("4.00")),
    "anthropic/claude-opus-4.7": (Decimal("15.00"), Decimal("75.00")),
}


def estimate_cost_usd(model: str, prompt_tokens: int, completion_tokens: int) -> Decimal:
    rates = PRICING.get(model)
    if not rates:
        return Decimal("0")
    input_rate, output_rate = rates
    cost = Decimal(prompt_tokens) * input_rate / Decimal(1_000_000) + Decimal(
        completion_tokens
    ) * output_rate / Decimal(1_000_000)
    return cost.quantize(Decimal("0.000001"))
