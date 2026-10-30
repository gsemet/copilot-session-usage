# Analyze Copilot CLI / Copilot App Sessions

Use `--agent cli` to analyze sessions from Copilot CLI or the Copilot App
(the macOS Copilot App runs a bundled Copilot CLI runtime and shares its
session-state layout). Everything below is local-only: no network access or
credentials are involved.

## Auto-discovery

By default, sessions are discovered below `~/.copilot/session-state/`:

```bash
# Analyze the most recently modified Copilot CLI/App session
copilot-session-usage --agent cli latest

# List recent Copilot CLI/App sessions (metadata only)
copilot-session-usage --agent cli list --format table

# Analyze the 10 most recent Copilot CLI/App sessions in one pass
copilot-session-usage --agent cli batch 10
```

Override the discovery root with `--session-root` when your session-state
tree lives somewhere else (for example, a synced copy or a non-default
`$HOME`):

```bash
copilot-session-usage --agent cli --session-root /path/to/session-state latest
```

## By session UUID

```bash
copilot-session-usage --agent cli id 3a91c012-1b4e-4c8a-9f72-ab12cd34ef56
```

## By title substring

```bash
copilot-session-usage --agent cli find "release notes"
```

Title matching only works for sessions that have a title recorded in their
`workspace.yaml` sidecar (set via a session rename) — a session without one
is still fully analyzable by UUID or path, just not searchable by title.

## By explicit path

Point directly at a session directory, or at a relocated/exported
`events.jsonl` file, without any discovery step:

```bash
# A session directory (the common case)
copilot-session-usage --agent cli analyze ~/.copilot/session-state/<uuid>

# A relocated/exported events.jsonl file
copilot-session-usage --agent cli analyze /path/to/exported/events.jsonl
```

## Combined mode (`--agent all`)

`--agent all` is an explicit, opt-in mode that discovers and aggregates
sessions from **both** the `vscode` and `cli` providers in one command,
deduplicated by session UUID. Missing provider roots are ignored, including
when both roots are absent. It never runs unless you ask for it — every other
command defaults to `vscode` only, and PATH-based `analyze` always requires a
single explicit provider.

```bash
# List sessions from VS Code and Copilot CLI/App together
copilot-session-usage --agent all list --format table

# Analyze whichever session (from either provider) is most recent
copilot-session-usage --agent all latest --format table
```

With the CLI, `--workspace-storage` and `--session-root` can be supplied
independently with `--agent all`; each override applies only to its matching
provider. A missing override is ignored in combined mode. The Python API's
single `workspace_roots` override remains unsupported for `agent="all"` because
one list cannot unambiguously apply to two different discovery layouts.

## Missing or partial evidence

Totals come from the per-call `session.usage_record` events plus
`session.compaction_complete` events, so a session that is still active, was
interrupted, or continued after its last `session.shutdown` is fully analyzed.
`session.shutdown`/`session.usage_checkpoint` snapshots are incomplete and are
used only for reconciliation: `reconciliation.snapshot_usd` and
`snapshot_delta_usd` show the gap, and a diagnostic is added when the snapshot
exceeds the records total by more than $0.005 (records are authoritative).

Only a session with neither usage records nor compaction usage has no totals.
Rather than reporting zero tokens and zero cost as if that were measured, the
report says so explicitly with `null`/`n/a` and a diagnostic. See
[How cost estimation works](../explanation/how-cost-estimation-works.md)
(Copilot CLI / Copilot App provider section) for details.

Batch and aggregate operations (`batch`, `--aggregate`) exclude sessions with
unavailable cost evidence from their totals rather than counting them as
zero; `summary.sessions_with_unavailable_cost` reports how many were
excluded.

## Export every call

`calls` emits one JSON object per LLM call (JSONL), including compactions
(`kind: "compaction"`). Every total this tool reports is a sum of these records:

```bash
copilot-session-usage --agent cli calls --last 7d --output calls.jsonl
```

## Subagent and skill attribution

`subagent.started`/`subagent.completed` events and each event's top-level
`agentId` field attribute tool calls and LLM calls (and the skill active at
that moment) to the subagent that actually made them, instead of collapsing
everything into `main`. `--tool-breakdown` shows the resolved subagent name
(or the raw `agentId` when a `subagent.started` event wasn't captured) in its
`subagent` column. The `subagents` cost block and `skills.breakdown` are
summed from the per-call records (`session.usage_record` carries the
`agentId`; skills are attributed per agent at the call timestamp).
`initiator_breakdown` groups calls by `user`/`agent`/`sub-agent`/`compaction`.

## What's different from the VS Code provider

- Calls carry a real `cache_write_tokens` count (`null` on VS Code), and
  compactions are separate billed events that are included in the totals.
- Costs use Copilot's billed per-call `totalNanoAiu`; a call without it is
  priced from the table using the exact `cacheWriteTokens` count and a tier
  chosen from that call's own input size.
- `--since`/`--until`/`--last` select calls by timestamp; see
  [How cost estimation works](../explanation/how-cost-estimation-works.md#dont-recompute-costs-yourself)
  before recomputing any figure yourself.
- Analysis never refreshes pricing over the network for either provider. Run
  `copilot-session-usage pricing refresh` to update pricing explicitly.
