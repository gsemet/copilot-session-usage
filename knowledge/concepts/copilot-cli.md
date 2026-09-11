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

The provider uses the final `session.shutdown` event for shared token and
estimated-cost totals. Active or interrupted sessions can expose only
provider-native checkpoint counters, so shared totals remain unavailable
instead of being represented as zero. Copilot-native counters such as
`totalNanoAiu` and premium-request counts are preserved separately.

Per-skill cost and validated per-subagent cost attribution require per-request
token evidence. CLI/App logs may provide skill detection, tool-call
attribution, and raw subagent counters without enough evidence to populate
those shared cost breakdowns.

Use `--agent cli` for CLI/App discovery, or `--agent all` for explicit
combined discovery. Missing provider roots are ignored in combined mode.
Exported or relocated `events.jsonl` files can be analyzed directly when they
contain recognizable events and a canonical UUID.

## Related

- [VS Code Copilot Extension](../structures/vscode-copilot-extension.md) — The reference implementation
- [Overview](./overview.md) — General principles that apply to both providers
- [Debug Log Format](../reference/debug-log-format.md) — VS Code event structure reference
