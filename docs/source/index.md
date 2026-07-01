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

## Contents

```{toctree}
:maxdepth: 2

cli
api
```

## Indices and tables

- {ref}`genindex`
- {ref}`modindex`
- {ref}`search`
