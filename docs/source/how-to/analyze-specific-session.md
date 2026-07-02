# Analyze a Specific Session

Use this when you know the path to a session's debug-log directory or its UUID,
and `latest` would pick the wrong session.

## By debug-log path

Each session is a directory inside VS Code's `workspaceStorage`:

```bash
copilot-session-usage analyze \
  "/path/to/workspaceStorage/<hash>/GitHub.copilot-chat/debug-logs/<session-uuid>"
```

The path always ends in a UUID directory. Use `list` to find the right one if
you're unsure.

## By UUID

If you have a session ID from a previous `list` or `find` run:

```bash
copilot-session-usage id 3a91c012-1b4e-4c8a-9f72-ab12cd34ef56
```

The tool searches all workspaceStorage roots automatically.

## By title substring

```bash
copilot-session-usage find "CI pipeline"
```

Matching is case-insensitive substring search. If multiple sessions match,
the tool lists them and exits without analyzing — then use `id` to pick one.

## Locating workspaceStorage manually

| Platform | Default path |
|----------|-------------|
| macOS | `~/Library/Application Support/Code/User/workspaceStorage/` |
| Linux | `~/.config/Code/User/workspaceStorage/` |
| Windows | `%APPDATA%\Code\User\workspaceStorage\` |

Each subdirectory under `workspaceStorage/` corresponds to one VS Code workspace.
Inside it, `GitHub.copilot-chat/debug-logs/` contains one directory per session.
