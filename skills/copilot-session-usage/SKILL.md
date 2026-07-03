---
name: copilot-session-usage
description: 'Extract VS Code Copilot session cost KPIs (tokens, estimated USD, model, duration, subagent attribution) from local debug logs. Supports per-model pricing with cache-hit discounts, threshold-aware tier switching, and multi-model session analysis.'
---

# copilot-session-usage

Extract VS Code Copilot session cost KPIs from local debug logs.

## When to use

- You need to estimate how much a Copilot chat session cost in tokens and USD
- You want to compare costs across sessions, models, or time periods
- You need to attribute costs to subagents (e.g. `runSubagent` calls)
- You want batch analysis of multiple sessions

## Installation

```bash
uv tool install copilot-session-usage
```

## CLI Usage

```bash
# Analyze the most recent session
copilot-session-usage latest

# Analyze a specific session by its debug-log directory
copilot-session-usage analyze /path/to/session/debug-logs

# List recent sessions (metadata only)
copilot-session-usage list

# Batch analyze the last 10 sessions
copilot-session-usage batch 10

# Full detail JSON output
copilot-session-usage latest --detail full --format json
```

## Key Features

- **Per-model pricing** with cache-hit discounts
- **Multi-model sessions** correctly handled
- **Threshold-aware pricing** for long-context tiers
- **Subagent cost attribution**
- **Cross-platform** (macOS, Linux, Windows, WSL2)
- **Three detail levels**: minimal, compact, full
- **JSON, table and detailed output**

## Pricing Data

Pricing data is bundled withing the copilot-session-usage package in `src/copilot_session_usage/data/`:

- `models-and-pricing.yml` — Standard model pricing
- `models-and-pricing.lock` — Lock file for reproducibility
- `custom-models-pricing.yml` — Custom / organization-specific pricing

## Provider Support

| Provider | Status | Notes |
|----------|--------|-------|
| VS Code  | ✅ Supported | Auto-detects workspaceStorage |
| CLI      | 🚧 Planned | Not yet implemented |

## Output Formats

- `table` — Human-readable aligned table (default)
- `json` — Machine-readable JSON
- `detailed` — Alias for `table` with `full` detail

## Detail Levels

- `minimal` — Total tokens, cost, duration only
- `compact` — Adds models list, fallback flags, pricing note
- `full` — Everything including per-model breakdown and subagent attribution
