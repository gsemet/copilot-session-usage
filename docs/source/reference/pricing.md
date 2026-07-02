# Pricing Reference

`copilot-session-usage` ships a bundled pricing table at
`src/copilot_session_usage/data/models-and-pricing.yml`.
All cost calculations use this file.

Prices reflect the published GitHub Copilot per-token rates for each model.
Cache-hit discounts and long-context tier switching are applied automatically.

## Cost formula

For each model call:

```
cost = (input_tokens - cached_tokens) / 1_000_000 × input_price
     + cached_tokens / 1_000_000 × cached_input_price
     + output_tokens / 1_000_000 × output_price
```

## Cache discounts

All providers apply a discount to tokens served from their prompt cache.
The exact ratio varies:

| Provider | Cached discount |
|----------|----------------|
| OpenAI | ~10× cheaper than input |
| Anthropic | ~10× cheaper than input |
| Google | ~4× cheaper than input |

A session with 85% cache hit ratio costs significantly less than its raw
token count suggests.

## Long-context tier switching

Some models have two pricing tiers based on input length:

| Model | Threshold | Effect |
|-------|-----------|--------|
| GPT-5.4 | > 272K tokens | Input/cached/output prices double |
| GPT-5.4 mini | > 272K tokens | Input/cached/output prices double |

`copilot-session-usage` automatically selects the correct tier based on the
total input tokens in the session.

## Updating pricing

The bundled pricing is updated manually with each release. To refresh it from
the upstream YAML source:

```bash
just refresh-pricing
```

This fetches the latest pricing YAML and regenerates the bundled file.
Run `just preflight` afterwards to validate no tests broke.

## Custom pricing

Override any model's price by editing
`src/copilot_session_usage/data/custom-models-pricing.yml`. Entries in
this file take precedence over the main table.
