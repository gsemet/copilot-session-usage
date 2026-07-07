# Analyze a Specific Session

Use this when you know the path to a session's debug-log directory or its UUID,
and `latest` would pick the wrong session.

## By name regex across all sessions

When you want to analyze several related sessions at once, use `analyze --name`
with a case-insensitive regex. This is more efficient than running `find` or
`list` and then analyzing each session separately.

```bash
# Analyze all sessions whose title matches a PRD or feature
copilot-session-usage analyze --name "feature-x" --format table

# Aggregate them into a single summary
copilot-session-usage analyze --name "feature-x" --aggregate --format table

# Cost-efficiency summary for each matching session
copilot-session-usage analyze --name "feature-x" --summary --format table
```

Add `--since` and `--until` to narrow the date range, or `--workspace` to
restrict to one workspace folder.

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

You can also filter `list` and `analyze` by title substring with `--title`:

```bash
# List only sessions whose title contains "get-session-costs"
copilot-session-usage list --title "get-session-costs"

# Analyze the most recent matching session
copilot-session-usage analyze --title "grill-me" --latest --format table
```

## Skill-aware analysis

When a session invokes a skill (for example `/compendium-generic get-session-costs`),
you can attribute costs and tool calls to that skill.

```bash
# Per-skill cost breakdown for a session
copilot-session-usage id 3a91c012-1b4e-4c8a-9f72-ab12cd34ef56 --skill-breakdown

# Per-skill/per-subagent tool-call counts
copilot-session-usage id 3a91c012-1b4e-4c8a-9f72-ab12cd34ef56 --tool-breakdown

# Concise cost for a single skill
copilot-session-usage id 3a91c012-1b4e-4c8a-9f72-ab12cd34ef56 \
  --skill "/compendium-generic get-session-costs" \
  --format json --detail minimal
```

## List skills across sessions

```bash
# Skills used in the last 7 days, with aggregated cost
copilot-session-usage skills --last 7d --format table
```

## Locating workspaceStorage manually

| Platform | Default path |
|----------|-------------|
| macOS | `~/Library/Application Support/Code/User/workspaceStorage/` |
| Linux | `~/.config/Code/User/workspaceStorage/` |
| Windows | `%APPDATA%\Code\User\workspaceStorage\` |

Each subdirectory under `workspaceStorage/` corresponds to one VS Code workspace.
Inside it, `GitHub.copilot-chat/debug-logs/` contains one directory per session.
