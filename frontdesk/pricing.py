"""List prices for cost estimates, USD per million tokens. An ESTIMATE for the cost line and the
eval report, not a bill: check the vendor's pricing page before quoting a number. Unknown models
report cost as None rather than a guess.

Sources: Anthropic list prices as of 2026-06; OpenAI developers.openai.com/api/docs/pricing
(standard tier, read 2026-10-29); Google ai.google.dev/gemini-api/docs/pricing (paid tier, page
updated 2026-10-28). Gemini 3.8 Flash doubles on 2027-01-01 (to 1.50 / 7.50 / 0.15). Cache reads
bill at a fraction of input (per model); 5-minute cache writes at 1.25x input (Anthropic)."""
from __future__ import annotations

# model -> (input, output, cache_read)
PRICES: dict[str, tuple[float, float, float]] = {
    "claude-fable-5-1": (10.00, 50.00, 0.25),
    "claude-opus-5-5": (4.00, 20.00, 0.20),
    "claude-opus-5": (5.00, 25.00, 0.50),
    "claude-sonnet-5": (2.00, 10.00, 0.20),
    "claude-haiku-4-5": (1.00, 5.00, 0.10),
    "gpt-6.1-sol": (2.00, 10.00, 0.10),
    "gemini-3.8-flash": (0.75, 3.75, 0.075),   # output includes thinking tokens
}
CACHE_WRITE_MULT = 1.25


def cost_usd(model: str, tokens_in: int, tokens_out: int, cache_read: int = 0,
             cache_write: int = 0) -> float | None:
    p = PRICES.get(model)
    if p is None:
        return None
    inp, out, cr = p
    return (tokens_in * inp + tokens_out * out + cache_read * cr
            + cache_write * inp * CACHE_WRITE_MULT) / 1_000_000
