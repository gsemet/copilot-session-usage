---
type: Reference
title: Pricing Data Formats
description: Schema and format documentation for models-and-pricing.yml,
  custom-models-pricing.yml, and the internal pricing dict.
tags: [pricing, yaml, schema, reference]
timestamp: 2026-06-30T22:00:00Z
links: []
backlinks: []
---

# Pricing Data Formats

## models-and-pricing.yml

Standard pricing file with the following schema:

```yaml
- model: "Model Name"
  provider: "Provider Name"
  input: "$X.XX"
  cached_input: "$X.XX"
  output: "$X.XX"
  threshold_tokens: NNNNNN  # Optional: context length threshold for tier switching
```

## custom-models-pricing.yml

Organization-specific overrides with the same schema as `models-and-pricing.yml`.

Custom models are merged with standard models and take precedence on name collision.

## models-and-pricing.lock

Lock file for reproducible pricing data. Contains a timestamp and checksum.

## Internal Pricing Dict

After loading, pricing data is transformed into an internal dict:

```python
{
    "models": {
        "model-name": [
            {
                "input_per_m": float,
                "output_per_m": float,
                "cache_per_m": float,
                "tier": str,
                "threshold_tokens": int | None,
            }
        ]
    }
}
```

Model names are normalized to lowercase with hyphens.
