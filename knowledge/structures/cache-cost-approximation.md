---
type: Structure
title: Cache Cost Approximation
description: How copilot-session-usage approximates Anthropic cache-write costs
  when VS Code debug logs do not expose cache_creation token counts.
tags: [cache-write, anthropic, approximation, cost-estimation, aic]
timestamp: 2026-07-03T00:00:00Z
related_concepts: [concepts/session-cost-analysis.md]
links: [concepts/session-cost-analysis.md,
    findings/cache-write-cost-not-tracked.md]
backlinks: []
---

# Cache Cost Approximation

## The Problem

VS Code JSONL debug logs do not expose `cacheCreationTokens`. The OTel SQLite
store (`agent-traces.db`) has the schema column
`gen_ai.usage.cache_creation.input_tokens` but VS Code does not populate it
for Claude models (verified: 0 rows on VS Code 1.103+). There is therefore no
direct source for the number of tokens written to the Anthropic prompt cache.

## The Approximation Formula

The key insight: VS Code already bills **fresh input** at the standard
`input_per_m` rate. Cache creation is only the *incremental* cost above that
baseline:

```
fresh_input = inputTokens − cachedTokens

cache_write_delta = fresh_input × (cache_write_per_m − input_per_m) / 1_000_000
```

Where:
- `inputTokens` — total tokens sent to the model (from JSONL `attrs.inputTokens`)
- `cachedTokens` — subset served from the prompt cache (from `attrs.cachedTokens`)
- `cache_write_per_m` — Anthropic's cache-write price per million tokens (e.g. $3.75 for Claude Sonnet 4.x)
- `input_per_m` — standard input price per million tokens (e.g. $3.00 for Claude Sonnet 4.x)

The total cost for a request is therefore:

```
total = (input_per_m × inputTokens
       + output_per_m × outputTokens
       − cache_per_m × cachedTokens   # cache read discount already handled
       + cache_write_delta) / 1_000_000
```

This is implemented as `estimate_cost()` in `src/copilot_session_usage/_internal/core.py`
since v0.3.

## Verification

Verified on session `438d24a8` (Claude Sonnet 4.6, 92 calls):

| Metric | Value |
|--------|-------|
| Fresh input | 720,122 tokens |
| Delta: 720K × ($3.75 − $3.00) / M | $0.5401 |
| Tool total (with delta) | $5.9037 |
| VS Code AIC panel (590.37 AIC ÷ 100) | **$5.9037** |

Exact match. Supporting Finding:
[`cache-write-cost-not-tracked`](../findings/cache-write-cost-not-tracked.md).

## Accuracy Characteristics

- **Accurate when** the full context prefix is cached (typical for long Copilot sessions).
- **May over-count by at most** `fresh_input × delta_rate` for requests where the context
  was not actually cached (very short contexts, no system prompt). In practice this is rare
  and the error is small relative to total session cost.

## OTel DB Fallback (Future)

`vscode.agent_traces_db_paths()` discovers all `agent-traces.db` paths across
Code / Code - Insiders on every platform. When VS Code eventually populates
`gen_ai.usage.cache_creation.input_tokens` in the OTel database, reading the
exact value from the DB will replace this proxy and the approximation can be
retired.

## Related

- [`findings/cache-write-cost-not-tracked.md`](../findings/cache-write-cost-not-tracked.md) — Supporting empirical evidence
- [`concepts/session-cost-analysis.md`](../concepts/session-cost-analysis.md) — Cost analysis overview
