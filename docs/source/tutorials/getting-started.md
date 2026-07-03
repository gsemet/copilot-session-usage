# Getting Started

This tutorial walks you through analyzing a Copilot session and reading the
output. It assumes you have installed `copilot-session-usage` — see
[Installation](../installation.md) if not.

---

## Analyze the latest session

Run this after any VS Code Copilot chat session:

```bash
copilot-session-usage latest --format table
```

Sample output:

```
Session:   f5cbde8a-ec40-466f-86e6-f95c343b6c58
Title:     Implement new feature X
Started:   2026-07-02T09:14:21Z
Duration:  2847s  (active: 312s)
Models:    claude-sonnet-4.6, claude-haiku-4.5
Input:     487,203 tokens
Output:    8,941 tokens
Cached:    412,100 (85%)
LLM calls: 14
Est. cost: $0.4231
```

Each field:

- **Session / Title** — the UUID and the workspace title VS Code stored for the session.
- **Duration / active** — wall-clock duration vs. time with active LLM calls.
- **Models** — all models called in this session, in call order.
- **Input / Output** — total tokens billed.
- **Cached** — input tokens served from the provider's prompt cache (cheaper).
- **LLM calls** — total requests across all models.
- **Est. cost** — estimated USD, after applying cache discounts and any long-context tier.

---

## Details Tables

`--format` controls the output type. Default is `json`:

```bash
# Just cost and model names
copilot-session-usage latest --format table

# Default: summary + per-subagent breakdown
copilot-session-usage latest --format detailed
```

---

## Get JSON output

Use `--format json` when scripting or piping to `jq`:

```bash
copilot-session-usage latest --format json | jq '.estimated_cost_usd'
```

Save to a file:

```bash
copilot-session-usage latest --format json --output session.json
```

---

## List recent sessions

See which sessions exist without computing costs (limit set to 20 by default):

```bash
copilot-session-usage list

# Limit to 5 sessions
copilot-session-usage list --limit 5

# Since a date
copilot-session-usage list --since 2026-07-01
```

Output:

```
2026-07-02T09:14Z  Implement new feature X          (id: f5cbde8a-...)
2026-07-01T18:03Z  Debug failing CI pipeline        (id: 3a91c012-...)
2026-07-01T11:22Z  Code review and refactor          (id: 9be4f330-...)
```

---

## Find a session by name

```bash
copilot-session-usage find "feature X"
```

If exactly one session matches, it analyzes it immediately. If several match,
it lists them so you can pick the right UUID.

---

## Analyze a specific session by UUID

```bash
# Default json output
copilot-session-usage id f5cbde8a-ec40-466f-86e6-f95c343b6c58

# Human readable summary
copilot-session-usage id f5cbde8a-ec40-466f-86e6-f95c343b6c58 --format table

# Human readable details with per-subagent breakdown
copilot-session-usage id f5cbde8a-ec40-466f-86e6-f95c343b6c58 --format detailed
```

---

## Analyze multiple sessions at once

```bash
# Last 10 sessions (json output)
copilot-session-usage batch 10

# Summary table for last 10 sessions
copilot-session-usage batch 10 --format table
```

Output includes a summary row with aggregate totals and a per-session table.

---

## Next steps

- [How-To Guides](../how-to/index.md) — export to JSON, filter by date, WSL2 setup
- [CLI Reference](../reference/cli.md) — all commands and options
- [How Cost Estimation Works](../explanation/how-cost-estimation-works.md) — pricing model details
