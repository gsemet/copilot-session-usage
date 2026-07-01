---
type: Concept
title: Session Discovery Algorithm
description: How a coding agent finds the correct session directory when the 
  user only knows the title, date, or workspace from the Agent Debug Panel.
tags: [discovery, algorithm, vscode, state, sqlite]
timestamp: 2026-07-01T00:00:00Z
---

# Session Discovery Algorithm

## The Problem

The VS Code **Agent Debug Panel** shows session metadata (title, creation date,
last activity, token totals) but **does not expose the session ID**.
The session ID is required to locate the `debug-logs/<session-id>/` directory
where per-subagent `.jsonl` files live.

## Where the Session ID Lives

VS Code stores a session index in an SQLite database inside each workspace
storage folder:

```
~/Library/Application Support/Code/User/workspaceStorage/
└── <workspace-hash>/
    └── state.vscdb          ← SQLite database
        └── ItemTable
            └── key = "chat.ChatSessionStore.index"
                └── value = JSON session index
```

The JSON value maps every session to:

| Field | Meaning |
|-------|---------|
| `sessionId` | UUID — this IS the debug-logs directory name |
| `title` | Session title shown in the debug panel |
| `timing.created` | Creation timestamp (epoch ms) |
| `lastMessageDate` | Last activity timestamp (epoch ms) |

## The Implementation, Not a Re-derivation

The actual, maintained discovery logic lives in `scripts/vscode_session_cost.py`
(not duplicated here, to avoid drift):

| Function | Purpose |
|----------|---------|
| `_get_sessions_from_workspace(ws_dir)` | Query one workspace's `state.vscdb`, cached per workspace directory |
| `find_session_dir_by_id(session_id, ws_roots)` | Resolve a UUID to its `debug-logs/<id>/` directory — backs the `id` command |
| `find_sessions_by_title(title, ws_roots)` | Case-insensitive substring match across all workspaces — backs the `find` command |
| `find_latest_session_dir(ws_roots)` | Most recently modified session directory — backs the `latest` command |
| `list_recent_sessions(ws_roots, ...)` | Sorted, filterable session metadata — backs the `list` and `batch` commands |
| `_get_workspace_folder(ws_dir)` | Resolve a workspace hash to its actual folder path via `workspace.json` |

## Disambiguation

Multiple sessions may share similar titles. The `find` command:

1. Prints all title/date/UUID matches to stderr
2. Exits with an error and instructs the caller to re-run with `id <SESSION_ID>`

There is no auto-pick-most-recent fallback — ambiguity is surfaced rather than
silently resolved, since picking the wrong session produces a plausible-looking
but wrong cost report.

## Why This Is Necessary

The Agent Debug Panel is a **read-only view**. It does not write the session ID
anywhere accessible to agents except through the SQLite state database.
The `state.vscdb` file is the only source of truth that links:
- Human-visible title → machine-readable session ID
- Session ID → debug log directory

## Related

- `scripts/vscode_session_cost.py` — the actual, maintained discovery implementation
- [VS Code Copilot Extension](vscode-copilot-extension.md) — Extension-specific
  log storage behavior
- [Debug Log Format](../reference/debug-log-format.md) — Event structure inside
  the discovered directory
