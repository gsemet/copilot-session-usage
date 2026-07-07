# Skill-aware cost attribution and faster session lookup

## Context

`copilot-session-usage` extracts VS Code Copilot session cost KPIs from local debug logs. It already supports per-model pricing, subagent attribution, and multiple output formats.

However, when a user invokes a skill (e.g. `/compendium-generic get-session-costs`), the CLI has no first-class way to report:

- which skill(s) were active in a session,
- how much each skill cost,
- which tool calls each skill triggered,
- or how to find a session by its title without manually scanning `copilot-session-usage list` output.

Investigating a single skill's cost currently requires ad-hoc Python scripts that grep raw JSONL files for slash-command names, skill discovery events, and tool-call records. This is slow, token-heavy, error-prone, and not reproducible.

## Problem

1. **No skill cost attribution.** A session may be dominated by one skill, but the CLI only reports per-model and per-subagent totals.
2. **Session lookup by title is manual.** Users must run `list`, visually scan titles, copy the UUID, then run `id <uuid>`.
3. **Subagent names are often `unknown`.** The subagent spawned by `runSubagent` is reported as `unknown` even though its name appears in the debug-log filename.
4. **No tool-call attribution.** It is impossible to see which tools a skill consumed tokens on.
5. **No stable, concise report format.** Full JSON dumps are large; users often only need skill + cost + token counts.

## Goals

Make `copilot-session-usage` **faster, safer, cheaper, and more reproducible** for skill-centric cost analysis by:

- detecting skills from system prompts, tool definitions, and user messages,
- attributing LLM calls and tool calls to the active skill,
- allowing users to filter sessions by title and skill,
- fixing subagent name extraction,
- providing a concise, stable output mode.

## Proposed features

### 1. Skill cost breakdown

Add a `--skill-breakdown` flag to `id` and `analyze` that emits a per-skill table:

```markdown
| Skill | Input Tokens | Output Tokens | Cached Tokens | LLM Calls | Cost |
|-------|--------------|---------------|---------------|-----------|------|
| /compendium-generic get-session-costs | 1,137,864 | 15,729 | 1,015,825 | 24 | $0.3636 |
```

Implementation notes:

- Parse `system_prompt_0.json` for loaded skill lists.
- Parse `tools_0.json` for the `skill` tool definition and any skill-related slash commands.
- Parse `user_message` events for slash-command invocations (`/<skill-name> ...`).
- Parse `discovery` events of type `Skill Discovery` as a fallback.
- Attribute each turn to the most recently invoked skill.

### 2. Filter sessions by title

Add `--title <substring>` to `list` and `analyze`:

```bash
copilot-session-usage list --title "get-session-costs"
copilot-session-usage analyze --title "grill-me" --latest
```

This avoids analyzing irrelevant sessions and reduces token consumption.

### 3. Filter analysis by skill

Add `--skill <name>` to `id` and `analyze`:

```bash
copilot-session-usage id <uuid> --skill "/compendium-generic get-session-costs"
```

When combined with `--format json --minimal`, this returns only the numbers the user asked for.

### 4. Tool-call attribution per skill

Add `--tool-breakdown` to `id` and `analyze`:

```markdown
| Tool | Calls | Skill | Subagent |
|------|-------|-------|----------|
| read_file | 25 | /compendium-generic get-session-costs | main, Explore |
| vscode_askQuestions | 3 | /compendium-generic get-session-costs | main |
| runSubagent | 1 | /compendium-generic get-session-costs | main |
```

### 5. Fix subagent name extraction

The subagent log file is named `runSubagent-Explore-functions.runSubagent:4.jsonl`. The CLI should extract `Explore` from the filename instead of reporting `unknown`.

Also handle `child_session_ref` events in `main.jsonl` as an additional source of subagent metadata.

### 6. Concise / minimal output mode

Add `--minimal` (or extend `--detail minimal`) to return only essential fields:

```bash
copilot-session-usage id <uuid> --skill "/compendium-generic get-session-costs" --format json --minimal
```

```json
{
  "skill": "/compendium-generic get-session-costs",
  "cost_usd": 0.3636,
  "input_tokens": 1137864,
  "output_tokens": 15729,
  "llm_calls": 24
}
```

### 7. Skill discovery across sessions

Add a `skills` command to list skills used over a time window:

```bash
copilot-session-usage skills --last 7d
```

Output:

```markdown
| Skill | Sessions | LLM Calls | Cost |
|-------|----------|-----------|------|
| /compendium-generic get-session-costs | 3 | 42 | $0.89 |
```

### 8. Metadata cache for faster repeated queries

Cache session metadata (title, created_at, has_debug_logs, debug_log_dir) in a small local index keyed by workspace hash. Invalidate when `state.vscdb` mtime changes. This makes `list --title` and `batch` operations near-instant.

## Acceptance criteria

- [ ] `copilot-session-usage id <uuid> --skill-breakdown` prints a per-skill cost table.
- [ ] `copilot-session-usage list --title <substring>` returns only matching sessions.
- [ ] `copilot-session-usage analyze --title <substring> --latest` analyzes the most recent matching session.
- [ ] `copilot-session-usage id <uuid> --skill "<name>"` filters the report to that skill.
- [ ] Subagents spawned by `runSubagent` show their real name, not `unknown`.
- [ ] `copilot-session-usage id <uuid> --tool-breakdown` prints per-skill/per-subagent tool-call counts.
- [ ] `copilot-session-usage id <uuid> --format json --minimal` returns a small, stable JSON object.
- [ ] `copilot-session-usage skills --last 7d` lists skills with aggregated cost.
- [ ] All new features are covered by unit tests.
- [ ] `just preflight` passes.

## Non-goals

- Do not modify pricing data or model detection logic.
- Do not add support for non-VS-Code providers (CLI provider remains planned).
- Do not persist raw debug logs or user message content in the metadata cache.

## Suggested first slice

1. Add `--title` filter to `list` and `analyze`.
2. Add `--skill-breakdown` to `id` / `analyze`.
3. Fix subagent name extraction (`unknown` → real name).

These three changes alone remove the most common manual steps and make skill-cost investigations reproducible from a single CLI command.

## Reference session

- Session ID: `44f6a978-243c-4115-aa90-d11c2ccf56e0`
- Title: `/compendium-generic grill-me here are proposal of improvement in copilot-session-usage, to make its use even way more token efficient:`
- Skill invoked: `/compendium-generic get-session-costs`
- Total cost: $0.3636 | 1,137,864 input + 15,729 output tokens | 24 LLM calls
