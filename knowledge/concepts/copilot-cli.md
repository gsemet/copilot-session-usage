---
type: Concept
title: Copilot CLI Differences
description: How session cost tracking differs when using copilot-cli instead of
  the VS Code extension.
tags: [copilot-cli, cli, differences, limitations]
timestamp: 2026-06-30T22:00:00Z
---

# Copilot CLI Differences

## Known Unknowns

This knowledge base was built from the VS Code Copilot extension. The `copilot-cli` tool MAY differ in the following ways — agents should verify each point when working with CLI sessions:

## Potential Differences

| Aspect | VS Code Extension | Copilot CLI (To Verify) |
|--------|------------------|------------------------|
| Log location | `~/Library/Application Support/Code/User/workspaceStorage/...` | Unknown — possibly `~/.copilot/logs/` or similar |
| File format | JSONL with `llm_request` events | Unknown — may use different event types or structured logging |
| Subagent logs | Separate `.jsonl` per subagent | Unknown — may log to single file or different naming |
| Session ID format | UUID | Unknown — may use different identifier |
| Debug panel | Built into VS Code | No GUI — may require manual log parsing |
| Real-time metrics | Available in panel | Unknown — may only be available post-hoc |

## What Agents Should Do

When asked to extract costs from a Copilot CLI session:

1. **Search for log directories** in common locations:
   - `~/.copilot/`
   - `~/.config/copilot/`
   - `~/.local/share/copilot/`
   - The current working directory

2. **Look for JSONL or structured log files** with timestamps and token counts

3. **If no logs are found**, ask the user for:
   - The CLI version (`copilot --version`)
   - Any `--verbose` or `--debug` flags used
   - Output from the session (stdout/stderr may contain metrics)

## Related

- [VS Code Copilot Extension](../structures/vscode-copilot-extension.md) — The reference implementation
- [Overview](./overview.md) — General principles that likely apply to both
- [Debug Log Format](../reference/debug-log-format.md) — Event structure reference
