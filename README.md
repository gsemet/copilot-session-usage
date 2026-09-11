# copilot-session-usage

[![CI](https://github.com/gsemet/copilot-session-usage/actions/workflows/ci.yml/badge.svg)](https://github.com/gsemet/copilot-session-usage/actions/workflows/ci.yml)
[![Coverage](https://img.shields.io/codecov/c/github/gsemet/copilot-session-usage)](https://codecov.io/gh/gsemet/copilot-session-usage)
[![PyPI](https://img.shields.io/pypi/v/copilot-session-usage)](https://pypi.org/project/copilot-session-usage/)
[![Python Versions](https://img.shields.io/pypi/pyversions/copilot-session-usage)](https://pypi.org/project/copilot-session-usage/)
[![Docs](https://readthedocs.org/projects/copilot-session-usage/badge/?version=stable)](https://copilot-session-usage.readthedocs.io/en/stable/)
[![Code style: ruff](https://img.shields.io/badge/code%20style-ruff-000000.svg)](https://github.com/astral-sh/ruff)
[![Type checked](https://img.shields.io/badge/type%20checked-mypy%2Fty-blue.svg)](./)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

Extract Copilot session cost KPIs (tokens, estimated USD, model, duration) from local
VS Code Copilot debug logs and/or local Copilot CLI/Copilot App session logs.

**Full documentation:** [copilot-session-usage.readthedocs.io](https://copilot-session-usage.readthedocs.io/en/stable/)

## Chronicle and copilot-session-usage

GitHub Copilot provides **Chronicle** session tools for conversational access to your
Copilot history. Chronicle and this project are complementary, but they answer different
questions.

### What Chronicle is good at

Use Chronicle when you want to:

- Find a past session by its title or session ID.
- Search or summarize what happened in a session.
- Inspect conversational history, checkpoints, referenced files, and session metadata.
- Get a quick, conversational summary of aggregate session KPIs when cost analysis is
  available in the current Copilot environment.

### What Chronicle is not designed to provide

Chronicle's session store is not a token-accounting database. Its stored session records
contain history and metadata, but do not expose a standard set of per-request pricing
fields. A Chronicle cost answer may therefore provide an aggregate estimate and a list of
models without providing a reproducible split of tokens and dollars by model or subagent.

### What this project adds

`copilot-session-usage` reads the original VS Code Copilot debug logs and local
Copilot CLI/App event logs and turns them into repeatable reports. It provides:

| Need | Chronicle | `copilot-session-usage` |
| --- | --- | --- |
| Conversational search and summaries | ✅ | ✅ CLI reports are interpreted by your agent |
| Session discovery by title or ID | ✅ | ✅ |
| Aggregate tokens | ✅  | ✅ |
| Aggregate estimated cost | ⚠️ When available; aggregate only | ✅ |
| Tokens **per model** | ⚠️ LLM digging each time; consumes tokens | ✅ |
| Estimated cost (`$`) **per model** | ❌ No accurate cost per breakdown | ✅ |
| Tokens **per subagent** | ⚠️ LLM digging each time; consumes tokens | ✅ |
| Estimated cost (`$`) **per subagent** | ❌ No accurate cost per breakdown | ✅ |
| Cost attribution to skills | ❌ Cannot provide cost per breakdown | ✅ |
| Tool-call counts by skill and subagent | ⚠️ LLM digging each time | ✅ |
| Batch analysis, filtering, and aggregation | Limited/conversational | ✅ |
| Stable JSON, table, and detailed output | No stable contract | ✅ |
| Python API for embedding in third-party tools | ❌ | ✅ |
| Pricing provenance and custom model rates | ⚠️ Only for aggregated costs | ✅ |
| Git commit cost trailers | ❌ | ✅ |

In the table, `⚠️` means that Chronicle may answer the question in a particular
environment or with additional analysis, but does not guarantee a stable, reproducible
breakdown for it.

Use Chronicle for **“What did I do?”** and use this project for **“How much did it cost,
which model or subagent consumed it, and can I export the evidence?”**

## Providers

`copilot-session-usage` supports two local session sources, selected explicitly
with `--agent` (default `vscode`):

- **`vscode`** (default) — VS Code Copilot Chat debug logs.
- **`cli`** — Copilot CLI and Copilot App local sessions, stored under
  `~/.copilot/session-state/<session-id>/events.jsonl`. The macOS Copilot App
  runs a bundled Copilot CLI runtime and uses the same session-state layout.
- **`all`** — an explicit, opt-in combined mode that discovers and
  aggregates sessions from both providers, deduplicated by session UUID.
  Commands never mix providers unless `--agent all` is passed. Missing
  provider roots are ignored, including when both roots are absent.

Both providers share the same model catalog, pricing data, cache rules, and
estimated-USD calculation. Copilot CLI/App sessions additionally expose
provider-native counters (`provider_usage`: nanoAiu, premium requests) as
separate fields, and never turn missing evidence (for example, a session that
has not shut down yet) into a fabricated zero — see `diagnostics` in the
output when data is unavailable.

```bash
# Analyze the latest Copilot CLI/App session
copilot-session-usage --agent cli latest

# Analyze a specific Copilot CLI/App session by its session-state directory
copilot-session-usage --agent cli analyze ~/.copilot/session-state/<uuid>

# List and aggregate sessions from both VS Code and Copilot CLI/App
copilot-session-usage --agent all list --format table
```

## Installation

```bash
uv tool install copilot-session-usage
```

## Quick start

```bash
# Analyze the most recent session
copilot-session-usage latest

# Analyze a specific session by its debug-log directory
copilot-session-usage analyze /path/to/session/debug-logs

# List recent sessions (metadata only)
copilot-session-usage list

# Batch analyze the last 10 sessions
copilot-session-usage batch 10

# Compact total/model/session report for a date span
copilot-session-usage --agent all span \
  --since 2026-07-01T00:00:00Z \
  --until 2026-07-08T00:00:00Z \
  --format table

# Aggregate cost across all sessions matching a PRD path
copilot-session-usage analyze --name "PRD: /path/to/prd" --aggregate --format table

# List sessions in a debug-logs folder with cost columns
copilot-session-usage list --dir /path/to/debug-logs --format table
```

## Features

- **Token-level cost estimation** — per-model pricing with cache-hit discounts
- **Multi-model sessions** — correctly handles sessions that call multiple models (e.g. Claude + Kimi)
- **Threshold-aware pricing** — long-context tier switching (e.g. GPT-5.4 > 272k tokens)
- **Subagent cost attribution** — tracks `runSubagent` calls and their token usage
- **VS Code and Copilot CLI/App providers** — `--agent vscode` (default), `--agent cli`, or the opt-in combined `--agent all`
- **Cross-platform** — macOS, Linux, Windows, WSL2
- **Three output formats** — `json` (default), `table`, `detailed`
- **Three detail levels** — `minimal`, `compact`, `full`
- **JSON and table output** — machine-readable or human-friendly
- **Session filtering** — regex match by name, date-range filtering
- **Aggregation** — roll up costs across many sessions in one command
- **Skill-aware cost attribution** — detect skills, attribute LLM and tool calls to the active skill
- **Skill cost breakdown** — per-skill token counts and estimated cost (VS Code provider)
- **Tool-call attribution** — per-skill/per-subagent tool-call counts
- **Title filtering** — find sessions by title substring
- **Efficiency summaries** — cache ratio, model split, cost per 1M tokens
- **Field extraction** — pull specific values with `--query`

## How it works

### VS Code provider (`--agent vscode`, default)

`copilot-session-usage` reads VS Code Copilot debug logs stored in
`~/Library/Application Support/Code/User/workspaceStorage/` (macOS),
`%APPDATA%\Code\User\workspaceStorage\` (Windows), or
`~/.config/Code/User/workspaceStorage/` (Linux).

Each session directory contains a `GitHub.copilot-chat/debug-logs/` folder with
JSONL files. The tool parses these files, extracts token counts per model,
applies per-model pricing (including cache-hit discounts and long-context tier
switching), and estimates the session cost in USD.

Subagent calls (`runSubagent`) are tracked separately so you can see how much
token usage was delegated to helper agents.

### Copilot CLI/App provider (`--agent cli`)

Copilot CLI and the Copilot App store one directory per session under
`~/.copilot/session-state/<session-id>/` (override with `--session-root`).
Each session directory has a structured `events.jsonl` event log — the
primary evidence source — plus an optional `workspace.yaml` sidecar with
title, working directory, git branch, and timestamps.

`copilot-session-usage` also accepts an explicit session directory or a
relocated/exported `events.jsonl` file directly (for example
`copilot-session-usage --agent cli analyze /path/to/exported/events.jsonl`),
without requiring auto-discovery. An explicit source is only analyzed when it
contains recognizable Copilot CLI event records and a canonical session UUID
can be determined (from the directory name or a `session.start` event) —
otherwise it is rejected with an actionable error instead of being analyzed
with a fabricated identity.

Per-model token totals and cost come from the session's final
`session.shutdown` event and use the same shared, token-based pricing
calculation as the VS Code provider. GitHub Copilot's own `totalNanoAiu`
billing figure is kept separate under `provider_usage.total_nano_aiu` and
never substituted into the shared cost calculation. For a session that has
not shut down yet (still active, or interrupted), only provider-native
counters from the last usage checkpoint are available; token totals and cost
are reported as unavailable (`null`) via the shared `total` block, with
`diagnostics` explaining why, rather than as fabricated zeros. Tool calls and
skill attribution are scoped to the subagent that made them, using
`subagent.started`/`subagent.completed` events and each event's `agentId`;
`provider_usage.subagents` separately preserves the raw per-subagent evidence
available (name, model, tool-call count, reported tokens, duration). Parsing
tolerates unrecognized event types and schema versions other than the one
currently validated, recording a diagnostic instead of failing.

Pricing lookups for `--agent cli`/`--agent all` are local-only by default
(no runtime pricing refresh attempt over the network), unlike the `vscode`
provider's default daily refresh attempt. Run
`copilot-session-usage pricing refresh` to update pricing explicitly.

## Knowledge base

This project includes an OKF knowledge bundle in `knowledge/` with structured
guidelines for contributors. Validate it with:

```bash
just knowledge-validate
```

## Usage

### Commands

| Command | Description |
|---------|-------------|
| `analyze [PATH]` | Analyze one session by PATH, or many by `--name` regex |
| `latest` | Analyze the most recently modified session |
| `find TITLE` | Find and analyze a session by title (case-insensitive substring match) |
| `id SESSION_ID` | Analyze a session by exact UUID |
| `list` | List recent sessions (metadata only by default) |
| `batch N` | Analyze the N most recent sessions in one pass |
| `span` | Emit a compact total, per-model, and per-session date-span report |
| `skills` | List skills used across sessions with aggregated cost |

### Analysis options

| Option | Description |
|--------|-------------|
| `--name REGEX` | Filter sessions by title/ID regex (case-insensitive) |
| `--title SUBSTRING` | Filter sessions by title substring (case-insensitive) |
| `--since DATE` | Only sessions created after DATE (ISO 8601 with timezone) |
| `--until DATE` | Only sessions created before DATE (ISO 8601 with timezone) |
| `--last DURATION` | Use a rolling window such as `7d`, `24h`, or `30m` with `span` |
| `--workspace PATH` | Only sessions from this workspace folder |
| `--aggregate` | Aggregate all matching sessions into one summary |
| `--summary` | Output a cost-efficiency summary |
| `--skill-breakdown` | Emit a per-skill cost breakdown |
| `--tool-breakdown` | Emit a per-skill/per-subagent tool-call count breakdown |
| `--skill NAME` | Filter the report to a single skill |
| `--query PATH` | Extract a single field with dot notation |
| `--query-help` | Print all `--query` field paths |

### Global options

| Option | Description |
|--------|-------------|
| `--workspace-storage PATH` | Override workspaceStorage directory (auto-detected by default). Used by `--agent vscode`/`all` |
| `--session-root PATH` | Override the Copilot CLI/App session-state root (default: `~/.copilot/session-state`). Used by `--agent cli`/`all` |
| `--agent {vscode,cli,all}` | Provider for session discovery: `vscode` (default), `cli`, or the explicit opt-in combined mode `all` |
| `--detail {minimal,compact,full}` | Detail level (default: `compact`) |
| `--format {json,table,detailed}` | Output format (default: `json`) |
| `--output PATH` | Write output to file instead of stdout |

### Examples

```bash
# Full detail for the latest session
$ copilot-session-usage latest --detail full
{
  "session_id": "f5cbde8a-ec40-466f-86e6-f95c343b6c58",
  "session_dir": "/Users/az02065/Library/Application Support/Code/User/workspaceStorage/c016ff4fabbe9f918719a00c9c741058/GitHub.copilot-chat/debug-logs/f5cbde8a-ec40-466f-86e6-f95c343b6c58",
  ...
}

# JSON output for a specific session
$ copilot-session-usage analyze /path/to/debug-logs --format json --output report.json

# Find sessions containing "implem" in the title
$ copilot-session-usage find "implem"
Multiple sessions match 'implem':
  2026-07-01T21:15:12Z  'Implement copilot-session-usage spec'  (id: c890dd60-43d6-44f0-b57c-ab505dfa003b)
  2026-06-26T18:21:21Z  'Resume PRD implementation'  (id: 9368ab3e-1c93-4125-8271-d5bd024b057a)
  2026-06-26T09:19:52Z  'Resume Workflow PRD implementation'  (id: 1214eb3f-add0-41a5-84d4-88720218e60e)
...

# Get summary for a given session (found by `find`)
$ copilot-session-usage id 19e03be0-9cfa-4f21-a19a-4bdb754b3965 --format table
Session:   19e03be0-9cfa-4f21-a19a-4bdb754b3965
Title:     Implementation of new feature X
Started:   2026-07-01T20:37:34Z
Duration:  40588s  (active: 1083s)
Models:    claude-sonnet-4.6, claude-haiku-4.5, Kimi-K2.6-azure
Input:     1,425,790 tokens
Output:    22,166 tokens
Cached:    1,224,340 (86%)
LLM calls: 28
Est. cost: $1.0880
# Per-skill cost breakdown
$ copilot-session-usage id 19e03be0-9cfa-4f21-a19a-4bdb754b3965 --skill-breakdown --format table
Per-Skill Breakdown:
  Skill                              Input      Cached  Output  Calls     Cost
  ----------------------------------------------------------------------------
  /compendium-generic get-session-costs  1,137,864  1,015,825  15,729     24  $0.3636

# Per-skill/per-subagent tool-call counts
$ copilot-session-usage id 19e03be0-9cfa-4f21-a19a-4bdb754b3965 --tool-breakdown --format table
Tool Breakdown:
  Tool                          Calls  Skill                         Subagent
  ---------------------------------------------------------------------------
  read_file                        25  /compendium-generic get-session-costs  main
  vscode_askQuestions               3  /compendium-generic get-session-costs  main
  runSubagent                       1  /compendium-generic get-session-costs  main

# Concise skill cost (great for scripts)
$ copilot-session-usage id 19e03be0-9cfa-4f21-a19a-4bdb754b3965 \
    --skill "/compendium-generic get-session-costs" \
    --format json --detail minimal
{
  "skill": "/compendium-generic get-session-costs",
  "cost_usd": 0.3636,
  "input_tokens": 1137864,
  "output_tokens": 15729,
  "cached_tokens": 1015825,
  "llm_calls": 24
}

# List skills used across the last 7 days
$ copilot-session-usage skills --last 7d --format table
Skills across 23 sessions:
  Skill                              Sessions        Input     Output       Cached   Calls       Cost
  ---------------------------------------------------------------------------------------------------
  /compendium-generic get-session-costs       3    1137864      15729      1015825      24  $0.3636

# Filter sessions by title substring
$ copilot-session-usage list --title "get-session-costs"
$ copilot-session-usage analyze --title "grill-me" --latest
# Batch analyze last 5 sessions since July 1st
copilot-session-usage batch 5 --since 2026-07-01

# Aggregate all PRD-related sessions from the last week
copilot-session-usage analyze \
  --name "PRD: /path/to/prd" \
  --since 2026-06-30T00:00:00Z \
  --until 2026-07-07T00:00:00Z \
  --aggregate \
  --format table

# Cost-efficiency summary for a single session
copilot-session-usage analyze /path/to/debug-logs --summary --format table

# Extract just the total cost from a session
copilot-session-usage analyze /path/to/debug-logs --query .total.estimated_usd

# WSL2: point to Windows host workspaceStorage
copilot-session-usage latest \
  --workspace-storage /mnt/c/Users/$USER/AppData/Roaming/Code/User/workspaceStorage
```

## Python API

```python
from pathlib import Path

from copilot_session_usage.api import (
    analyze_session,
    analyze_latest,
    batch_analyze,
    aggregate_sessions,
    list_sessions,
)

# Analyze a session by path
result = analyze_session(Path("/path/to/debug-logs"), detail="full")

# Analyze the most recent session
result = analyze_latest(detail="compact")

# Batch analyze the last 10 sessions
batch = batch_analyze(10, detail="minimal")

# Aggregate multiple full analyses into one efficiency summary
aggregate = aggregate_sessions([result1, result2])

# List sessions with regex and date-range filtering
sessions = list_sessions(
    name_pattern=r"PRD",
    since="2026-07-01T00:00:00Z",
    until="2026-07-07T00:00:00Z",
)

# Analyze a Copilot CLI/App session, or discover/aggregate across all
# providers with the explicit opt-in agent="all"
cli_result = analyze_session(Path("~/.copilot/session-state/<uuid>"), agent="cli")
combined = list_sessions(agent="all")
```

## Development

```bash
# Install dependencies
just dev

# Run tests
just test

# Run full validation
just preflight

# Build docs
just docs

# Serve docs with auto-reload
just docs-serve
```

## License

MIT — see [LICENSE](LICENSE).
