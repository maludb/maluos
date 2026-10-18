"""Cost of one model call from the provider's usage block and the model_registry prices."""
from __future__ import annotations

from decimal import Decimal

MILLION = Decimal(1_000_000)


def normalise_usage(wire: str, usage: dict | None) -> dict[str, int]:
    """The four counters the ledger keeps, whatever the wire calls them. On the OpenAI wire
    cached tokens are INSIDE prompt_tokens; on Anthropic's they are separate. The ledger's
    input_tokens is always the uncached input, so the four never double count."""
    u = usage or {}
    if wire == "anthropic":
        return {"input": int(u.get("input_tokens") or 0), "output": int(u.get("output_tokens") or 0),
                "cache_read": int(u.get("cache_read_input_tokens") or 0),
                "cache_write": int(u.get("cache_creation_input_tokens") or 0)}
    # OpenAI reports cache hits as prompt_tokens_details.cached_tokens. DeepSeek reports the same
    # there and also as prompt_cache_hit_tokens (top level on older responses, inside the details
    # on newer ones) — read whichever is present, never add them together.
    details = u.get("prompt_tokens_details") or {}
    cached = int(details.get("cached_tokens") or details.get("prompt_cache_hit_tokens")
                 or u.get("prompt_cache_hit_tokens") or 0)
    return {"input": max(0, int(u.get("prompt_tokens") or 0) - cached),
            "output": int(u.get("completion_tokens") or 0), "cache_read": cached, "cache_write": 0}


def cost(tokens: dict[str, int], model: dict) -> Decimal:
    def price(column: str) -> Decimal:
        return Decimal(str(model.get(column) or 0))
    total = (tokens["input"] * price("price_input_per_mtok")
             + tokens["output"] * price("price_output_per_mtok")
             + tokens["cache_read"] * price("price_cache_read_per_mtok")
             + tokens["cache_write"] * price("price_cache_write_per_mtok")) / MILLION
    return total.quantize(Decimal("0.000001"))
