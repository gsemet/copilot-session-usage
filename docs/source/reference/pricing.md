# Pricing Reference

`copilot-session-usage` ships a bundled pricing table at
`src/copilot_session_usage/data/models-and-pricing.yml`.

## Upstream source

Prices are synced from the GitHub Copilot official rate card:
[`github/docs` — `data/tables/copilot/models-and-pricing.yml`](https://github.com/github/docs/blob/main/data/tables/copilot/models-and-pricing.yml)

The bundled copy is updated with each release.

## Utility models

GitHub Copilot utility models power background features and are not billed as
premium usage. They can still appear in local VS Code debug logs, so
`copilot-session-usage` recognizes the current utility families — GPT-4o,
GPT-4.1, and GPT-5.4 nano, including versioned variants — and excludes their
requests from token totals, cost estimates, breakdowns, and commit-usage
trailers. See GitHub's [utility-model documentation](https://docs.github.com/en/copilot/concepts/models/utility-models)
for the authoritative list and billing behavior.

## Runtime refresh and fallback

When pricing is loaded through the default Python API or a normal analysis
command, the tool attempts one refresh per rolling 24-hour period. The refresh
downloads and validates the upstream YAML, then stores it in the user
configuration directory returned by `platformdirs`:

| Platform | Cache directory |
|---|---|
| macOS | `~/Library/Application Support/copilot-session-usage/` |
| Linux | `${XDG_CONFIG_HOME:-~/.config}/copilot-session-usage/` |
| Windows | `%LOCALAPPDATA%\\copilot-session-usage\\` |

The cache contains `models-and-pricing.yml`, provenance metadata in
`models-and-pricing.lock`, and a separate `models-and-pricing.refresh.lock`
used to serialize concurrent writers. YAML and metadata are written through
temporary files and atomically replaced, so a failed refresh does not destroy
the previous valid snapshot.

If the network is unavailable or the upstream document is invalid, analysis
silently falls back to the newest valid local source: the user cache or the
bundled release copy. Failed automatic attempts are still throttled for the
same 24-hour window. A direct refresh reports the failure instead of hiding it.

Automatic refresh can be disabled for an individual Python call with
`load_pricing(auto_refresh=False)`. Explicit refresh is available through the
Python API and `copilot-session-usage pricing refresh`; use `--force` to ignore
the rolling window. `copilot-session-usage pricing status` shows cache paths,
timestamps, checksums, and the last refresh error.

The refresh command prints a concise report with the result, UTC timestamps,
model count, source, cache files, and checksum. For example:

```text
Pricing refresh
Result           Already current
Attempted        2026-08-05 12:14:08 UTC
Latest refresh   2026-08-05 12:14:08 UTC
Models           35
Source           GitHub Copilot rate card
Cache file       ~/Library/Application Support/copilot-session-usage/models-and-pricing.yml
Metadata file    ~/Library/Application Support/copilot-session-usage/models-and-pricing.lock
Checksum         4d0edb1c05af21c5
```

## Cost formula

For each VS Code request, `copilotUsageNanoAiu` takes precedence over token
pricing whenever present, including an explicit zero:

```text
cost_usd = copilotUsageNanoAiu / 100_000_000_000
```

This is the billed amount used by VS Code and already includes cache writes,
pricing tiers, and any billing adjustments. No token-based surcharge is added.
The same request costs feed session, model, subagent, and skill breakdowns.
Only requests without billing telemetry use the fallback below; a billed request
does not suppress estimates for other requests of the same model.

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

Fallback costs are calculated per request before aggregation, so pricing tiers
depend on each request's context size, not accumulated session tokens.

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

VS Code JSONL debug logs do not expose `cache_creation` tokens directly.
For any model with a cache-write premium, the tool approximates the incremental cache-creation
cost using fresh input as a proxy (see note below).

:::{note}
**Cache-write fallback: Anthropic and newer GPT models.**

The official rate card includes `cache_write` for Anthropic models and GPT-5.6
and later OpenAI families. The fallback is driven by the model's selected rate,
not its provider name. VS Code JSONL logs do not expose `cacheCreationTokens`.

The tool approximates the incremental cost as:

```
delta = (inputTokens - cachedTokens) × (cache_write_per_m - input_per_m) / 1_000_000
```

The premium is added only when `cache_write_per_m > input_per_m`.
Models without a cache-write rate are unaffected.

The approximation matched an earlier 92-call Claude session, but that does not
establish exactness for every request or model. Fresh input is not necessarily
all written to cache. Missing cache-creation counts, stale rates, BYOK billing,
or billing discounts prevent a universal dollar-accuracy guarantee for fallback
estimates. The package does not currently join JSONL requests to OTel cache-write
counts in `agent-traces.db`.
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
| GPT-5.4 / GPT-5.5 | > 272K tokens | Input/cache-read double; output increases 1.5x |
| GPT-5.6 Luna | > 200K tokens | Input/cache-read/cache-write double; output increases 1.5x |
| GPT-5.6 Sol / Terra and GPT-6 families | > 272K tokens | Input/cache-read/cache-write double; output increases 1.5x |
| Grok 4.x | > 200K tokens | Input/cache-read/output double |

`copilot-session-usage` selects the correct tier automatically based on
each VS Code request's input tokens. Versioned model names use the most specific
matching pricing prefix. Aggregate-only CLI summaries cannot recover individual
request context sizes; without a billed figure, their tier is chosen from the
average request size.

## Copilot CLI/App limitations

CLI/App costs use Copilot's billed `totalNanoAiu` (session, per model, per
agent), so totals are dollar-accurate. The event log has only cumulative
usage, so:

- **No per-skill cost.** There is no per-request usage to split by skill;
  `skills.breakdown` is empty. Detected skills and tool counts remain.
- **Unattributed remainder.** Per-model and per-agent metrics omit session
  segments that ended without `session.shutdown` (crash or kill before a
  resume). That cost is in `total.unattributed_usd`, not in any breakdown.
- **Active sessions** report only the latest checkpoint total, entirely
  unattributed.
- **Token fallback** (no billed figure) cannot see per-request long-context
  tiers or discounts and is an estimate.

## Custom pricing

Override any model's price by editing
`src/copilot_session_usage/data/custom-models-pricing.yml`. Entries in
this file take precedence over the main table. Custom pricing is intentionally
bundled-only and is not downloaded into the user runtime cache.
