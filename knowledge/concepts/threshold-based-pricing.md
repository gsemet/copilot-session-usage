---
type: Concept
title: Threshold-Based Pricing
description: How multi-tier model pricing (e.g. GPT-5.4 ≤272K vs >272K) is 
  parsed from YAML and applied during cost estimation.
tags: [pricing, thresholds, tiers, yaml, github-copilot]
timestamp: 2026-07-02T10:00:00Z
---

# Threshold-Based Pricing

## Problem

GitHub Copilot's official pricing table uses **multi-tier rates** for some
models.  The same model name appears twice with different token thresholds:

| Model | Threshold | Tier | Input | Output |
|-------|-----------|------|-------|--------|
| GPT-5.4 | ≤ 272K | Default | $2.50 | $15.00 |
| GPT-5.4 | > 272K | Long context | $5.00 | $22.50 |
| GPT-5.5 | ≤ 272K | Default | $5.00 | $30.00 |
| GPT-5.5 | > 272K | Long context | $10.00 | $45.00 |
| Gemini 3.1 Pro | ≤ 200K | Default | $2.00 | $12.00 |
| Gemini 3.1 Pro | > 200K | Long context | $4.00 | $18.00 |

A flat JSON structure like `{"gpt-5.4": {"input_per_m": 2.5}}` **loses this
information**, causing long-context sessions to be under-priced by 2×.

## Solution: Tier-Aware Pricing Dict

The pricing data structure stores **a list of tiers per model**:

```python
{
  "models": {
    "gpt-5.4": [
      {
        "input_per_m": 2.50,
        "output_per_m": 15.00,
        "cache_per_m": 0.25,
        "tier": "Default",
        "threshold_tokens": 272_000,
      },
      {
        "input_per_m": 5.00,
        "output_per_m": 22.50,
        "cache_per_m": 0.50,
        "tier": "Long context",
        "threshold_tokens": None,  # unbounded — catch-all
      },
    ]
  }
}
```

Single-tier models (e.g. Claude Sonnet, most Gemini models) use a
one-element list with `threshold_tokens: None`.

## Tier Selection Algorithm

When estimating cost for a request with `input_tok` tokens:

1. Look up the model's tier list (exact match → prefix match → `default`)
2. If only one tier, use it
3. Otherwise, iterate tiers in ascending threshold order:
   - If `input_tok <= threshold_tokens`, use this tier
   - If no threshold matches, use the last (unbounded) tier

```python
# Example: 300K input tokens on GPT-5.4
# Tier 0: threshold=272K → 300K > 272K → skip
# Tier 1: threshold=None → catch-all → selected ($5.00/M input)
```

## YAML Source → Internal Format Pipeline

```
GitHub docs/models-and-pricing.yml
    ↓  curl (just refresh-pricing)
references/models-and-pricing.yml   ← bare YAML, never hand-edited
    ↓  _build_pricing_from_yaml()
internal pricing dict (tier-aware)
    ↓  _get_model_rates(model, input_tok, pricing)
rates for this specific request volume
```

### YAML Parsing Details

The raw YAML uses human-friendly strings that need normalization:

| YAML Field | Example | Parsed Value |
|------------|---------|--------------|
| `model` | `GPT-5.4` | `gpt-5.4` |
| `model` | `Claude Sonnet 4.6` | `claude-sonnet-4.6` |
| `model` | `Claude Sonnet 5[^sonnet-5-promo]` | `claude-sonnet-5` |
| `threshold` | `≤ 272K` | `272000` |
| `threshold` | `> 272K` | `None` (unbounded) |
| `threshold` | `Not applicable` | `None` |
| `input` | `$2.50` | `2.5` |

### Sidecar Lock File

`references/models-and-pricing.lock` captures metadata about the YAML:

```json
{
  "_captured": "2026-07-02T10:00:00+00:00",
  "_source": "https://raw.githubusercontent.com/github/docs/main/...",
  "_yaml_path": "references/models-and-pricing.yml",
  "model_count": 42,
  "checksum": "a1b2c3d4..."
}
```

This lets scripts detect stale pricing without re-parsing the YAML.

## Backward Compatibility

The old `pricing.json` flat format is still supported via
`_migrate_legacy_pricing()`.  It wraps each model's rates into a
single-element tier list, so the rest of the code works unchanged.

## Files

| File | Purpose |
|------|---------|
| `references/models-and-pricing.yml` | Bare YAML from GitHub (source of truth) |
| `references/models-and-pricing.lock` | Sidecar metadata (capture date, checksum) |
| `references/pricing.json` | Legacy flat format (deprecated, still readable) |
| `scripts/_cost_core.py` | `_build_pricing_from_yaml()`, `_get_model_rates()` |
| `scripts/generate_lock.py` | Generates `.lock` from `.yml` |
