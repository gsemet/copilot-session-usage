# Pricing Reference

`copilot-session-usage` ships a bundled pricing table at
`src/copilot_session_usage/data/models-and-pricing.yml`.

## Upstream source

Prices are synced from the GitHub Copilot official rate card:
[`github/docs` — `data/tables/copilot/models-and-pricing.yml`](https://github.com/github/docs/blob/main/data/tables/copilot/models-and-pricing.yml)

The bundled copy is updated with each release.

## Cost formula

The VS Code debug log reports three token counts per LLM call:

| Field in log | Meaning |
|---|---|
| `inputTokens` | **Total** prompt tokens sent — cached and non-cached combined |
| `cachedTokens` | Subset of `inputTokens` served from the provider's prompt cache |
| `outputTokens` | Completion tokens generated |

Non-cached input = `inputTokens − cachedTokens`. The two input
components are billed at different rates, so the formula splits them:

```
cost_usd = (
    (inputTokens - cachedTokens) × rate.input          # fresh prompt tokens
  +  cachedTokens                × rate.cached_input   # cache-read tokens
  +  outputTokens                × rate.output         # completion tokens
) / 1_000_000
```

Results are summed across all models called in the session.

The equivalent statement using Anthropic-style variable names
(where `input` already excludes cached tokens) is:

```
cost_usd = (
    input          × rate.input
  + cache_read     × rate.cached_input
  + cache_creation × (rate.cache_write ?? rate.input)
  + output         × rate.output
) / 1_000_000
```

VS Code debug logs do not expose `cache_creation` tokens directly.
For Anthropic models, the tool approximates the incremental cache-creation
cost using fresh input as a proxy (see note below).

:::{note}
**Anthropic `cache_write` — approximated via fresh input.**

Anthropic models have a `cache_write` rate for tokens written to the provider's
cache for the first time. VS Code JSONL logs do not expose `cacheCreationTokens`;
`agent-traces.db` has the schema column but VS Code does not populate it for
Claude models (verified: 0 rows, VS Code 1.103+).

The tool approximates the incremental cost as:

```
delta = (inputTokens - cachedTokens) × (cache_write_per_m - input_per_m) / 1_000_000
```

Verified on a real 92-call Claude Sonnet 4.6 session: this matches the VS Code
AIC panel exactly ($5.9037 both ways). Models without `cache_write` (OpenAI,
Google) are unaffected — the delta is zero.

`agent_traces_db_paths()` in `vscode.py` locates `agent-traces.db` on all
platforms. When VS Code starts populating `gen_ai.usage.cache_creation.input_tokens`,
reading the exact value from the DB will replace this proxy without API changes.
:::

## AI Credits and USD

Post-2026-06-01, GitHub Copilot bills in **AI Credits (AIC)**.
The upstream rate card publishes prices in USD per million tokens.
The conversion is:

```
1 AIC = $0.01 USD    →    100 AIC = $1.00 USD
```

A model priced at `input: $3.00` per million tokens costs **300 AIC**
per million input tokens. This tool reports USD; multiply by 100 to get AIC.

The per-token AIC rate is identical across all Copilot plans. Plans differ
only in the monthly AIC allowance included — that allowance is not tracked
by this tool.

## Cache discounts

All providers discount tokens served from their prompt cache:

| Provider | Cache-read discount vs. input |
|----------|-------------------------------|
| OpenAI | ~10× cheaper |
| Anthropic | ~10× cheaper |
| Google | ~10× cheaper |

A session with 85% cache hit ratio costs significantly less than raw
token counts suggest.

## Long-context tier switching

Some models have two pricing tiers based on input token count:

| Model | Threshold | Effect |
|-------|-----------|--------|
| GPT-5.4 | > 272K tokens | Input/cached/output prices double |
| GPT-5.5 | > 272K tokens | Input/cached/output prices double |
| Gemini 3.1 Pro | > 200K tokens | Input/cached/output prices increase |

`copilot-session-usage` selects the correct tier automatically based on
the session's total input tokens per model.

## Custom pricing

Override any model's price by editing
`src/copilot_session_usage/data/custom-models-pricing.yml`. Entries in
this file take precedence over the main table.
