---
type: Structure
title: VS Code Copilot Extension Debug Logs
description: How the VS Code Copilot extension stores session logs and what
  agents need to know about path resolution.
tags: [vscode, copilot-extension, paths, workspace-storage, cross-platform]
timestamp: 2026-07-01T00:00:00Z
links: [concepts/copilot-cli.md, reference/debug-log-format.md]
backlinks: [concepts/copilot-cli.md, reference/debug-log-format.md,
    structures/session-discovery-algorithm.md]
---

# VS Code Copilot Extension Debug Logs

## Log Directory Structure

```
<workspaceStorage>/
├── <workspace-id-1>/
│   └── GitHub.copilot-chat/
│       └── debug-logs/
│           ├── <session-id-1>/
│           │   ├── main.jsonl
│           │   ├── runSubagent-...jsonl
│           │   └── ...
│           └── <session-id-2>/
│               └── ...
└── <workspace-id-2>/
    └── ...
```

## Platform-Specific workspaceStorage Paths

The script (`vscode_session_cost.py`) auto-detects all paths that exist on the
current platform.  Use `--workspace-storage PATH` to override when auto-detection
is not sufficient (e.g., WSL2 connecting to a Windows VS Code host).

| Platform | workspaceStorage location |
|----------|--------------------------|
| **macOS** | `~/Library/Application Support/Code/User/workspaceStorage` |
| **macOS Insiders** | `~/Library/Application Support/Code - Insiders/User/workspaceStorage` |
| **Windows** | `%APPDATA%\Code\User\workspaceStorage` |
| **Windows Insiders** | `%APPDATA%\Code - Insiders\User\workspaceStorage` |
| **Linux (XDG)** | `~/.config/Code/User/workspaceStorage` |
| **Linux Insiders** | `~/.config/Code - Insiders/User/workspaceStorage` |
| **VS Code Server / WSL2 server-side** | `~/.vscode-server/data/User/workspaceStorage` |
| **VS Code Server Insiders** | `~/.vscode-server-insiders/data/User/workspaceStorage` |

> **WSL2 note**: if VS Code runs on the *Windows* host and you access logs from inside
> WSL2, the storage is on the Windows filesystem.  Pass the mounted path explicitly:
> `--workspace-storage /mnt/c/Users/<you>/AppData/Roaming/Code/User/workspaceStorage`

## Path Resolution for Agents

The `<workspace-id>` is a hash, not human-readable. To find logs for the current workspace:

1. **Current session ID** is available in the VS Code context or from the debug panel URL
2. **All workspace IDs** can be enumerated by scanning `workspaceStorage/`
3. **Session matching** is done by timestamp or by aggregating token counts and comparing to the debug panel

## Session Identification Strategies

When the session ID is unknown, match by:

1. **Creation time** — First line timestamp in `main.jsonl`
2. **Last activity** — Last line timestamp
3. **Token totals** — Aggregate and compare to debug panel
4. **Subagent count** — Number of `runSubagent-*.jsonl` files

## What the Debug Panel Shows vs. Raw Logs

| Debug Panel Metric | Raw Source |
|-------------------|------------|
| Total Input Tokens | Sum of `inputTokens` across ALL `.jsonl` files |
| Total Output Tokens | Sum of `outputTokens` across ALL `.jsonl` files |
| Total Cached Input Tokens | Sum of `cachedTokens` across ALL `.jsonl` files |
| Tool Calls | Count of `tool_call` events in `main.jsonl` |
| Model Turns | Count of `model_turn` events |

## Related

- [Debug Log Format](../reference/debug-log-format.md) — Event structure
- [Copilot CLI Differences](../concepts/copilot-cli.md) — How CLI differs from extension
