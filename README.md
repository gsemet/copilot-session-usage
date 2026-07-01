# copilot-session-usage

Extract VS Code Copilot session cost KPIs (tokens, estimated USD, model, duration) from local debug logs.

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
```

## Features

- **Token-level cost estimation** — per-model pricing with cache-hit discounts
- **Multi-model sessions** — correctly handles sessions that call multiple models (e.g. Claude + Kimi)
- **Threshold-aware pricing** — long-context tier switching (e.g. GPT-5.4 > 272k tokens)
- **Subagent cost attribution** — tracks `runSubagent` calls and their token usage
- **Cross-platform** — macOS, Linux, Windows, WSL2
- **Three detail levels** — `minimal`, `compact`, `full`
- **JSON and table output** — machine-readable or human-friendly

## How it works

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
| `analyze PATH` | Analyze one session by its debug-log directory |
| `latest` | Analyze the most recently modified session |
| `find TITLE` | Find and analyze a session by title (fuzzy match) |
| `id SESSION_ID` | Analyze a session by exact UUID |
| `list` | List recent sessions (metadata only, no cost) |
| `batch N` | Analyze the N most recent sessions in one pass |

### Global options

| Option | Description |
|--------|-------------|
| `--workspace-storage PATH` | Override workspaceStorage directory (auto-detected by default) |
| `--agent {vscode,cli}` | Provider to use (`cli` not yet implemented) |
| `--detail {minimal,compact,full}` | Detail level (default: `compact`) |
| `--format {json,table,detailed}` | Output format (default: `table`) |
| `--output PATH` | Write output to file instead of stdout |

### Examples

```bash
# Full detail for the latest session
copilot-session-usage latest --detail full

# JSON output for a specific session
copilot-session-usage analyze /path/to/debug-logs --format json --output report.json

# Find sessions containing "refactor" in the title
copilot-session-usage find refactor

# Batch analyze last 5 sessions since July 1st
copilot-session-usage batch 5 --since 2026-07-01

# WSL2: point to Windows host workspaceStorage
copilot-session-usage latest \
  --workspace-storage /mnt/c/Users/$USER/AppData/Roaming/Code/User/workspaceStorage
```

## Python API

```python
from copilot_session_usage.api import analyze_session, analyze_latest, batch_analyze

# Analyze a session by path
result = analyze_session(Path("/path/to/debug-logs"), detail="full")

# Analyze the most recent session
result = analyze_latest(detail="compact")

# Batch analyze the last 10 sessions
batch = batch_analyze(10, detail="minimal")
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
