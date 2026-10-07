---
type: Concept
title: Copilot CLI and App Differences
description: How session cost tracking differs when using Copilot CLI or the
  Copilot App instead of the VS Code extension.
tags: [copilot-cli, cli, differences, limitations]
timestamp: 2026-09-11T00:00:00Z
links: [concepts/overview.md, reference/debug-log-format.md,
    structures/vscode-copilot-extension.md]
backlinks: [structures/vscode-copilot-extension.md]
---

# Copilot CLI and App Differences

The Copilot CLI and Copilot App share a local session format that differs from
the VS Code extension's workspace debug logs. On macOS, sessions are stored
under `~/.copilot/session-state/<session-uuid>/events.jsonl`; the root can be
overridden with `--session-root`. A session directory may also contain a
`workspace.yaml` sidecar with metadata such as title, working directory,
branch, and timestamps.

| Aspect | VS Code Extension | Copilot CLI/App |
|--------|------------------|-----------------|
| Log location | `~/Library/Application Support/Code/User/workspaceStorage/...` | `~/.copilot/session-state/<session-uuid>/events.jsonl` |
| File format | JSONL with `llm_request` events | Structured JSONL event stream |
| Subagent logs | Separate JSONL files | Subagent events in the session stream |
| Session ID format | UUID directory | UUID directory and session events |
| Debug panel | Built into VS Code | No equivalent cost panel |
| Final shared totals | Per-request evidence | Final `session.shutdown` cumulative usage |

The session-level `totalNanoAiu` is cumulative across resumes and is the
billed session total. Per-model and per-agent (`agentMetrics`) metrics carry
their own billed `totalNanoAiu` and exact `cacheWriteTokens`, but omit
segments that ended without `session.shutdown`; that remainder is reported as
unattributed. Active sessions expose only checkpoint totals, so their cost is
entirely unattributed.

Per-skill cost attribution requires per-request evidence, which CLI/App logs
do not provide. Subagent cost comes from `agentMetrics`.

Use `--agent cli` for CLI/App discovery, or `--agent all` for explicit
combined discovery. Missing provider roots are ignored in combined mode.
Exported or relocated `events.jsonl` files can be analyzed directly when they
contain recognizable events and a canonical UUID.

## Related

- [VS Code Copilot Extension](../structures/vscode-copilot-extension.md) — The reference implementation
- [Overview](./overview.md) — General principles that apply to both providers
- [Debug Log Format](../reference/debug-log-format.md) — VS Code event structure reference
