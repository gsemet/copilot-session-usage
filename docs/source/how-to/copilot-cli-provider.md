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

A session that is still active, or was interrupted before it could shut down
cleanly, has no final usage summary yet. Rather than reporting zero tokens
and zero cost as if that were measured, the report says so explicitly with
`null`/`n/a`:

```bash
$ copilot-session-usage --agent cli latest --format table
Session:   c3bda2f6-fc42-4959-9672-8e087225f251
Provider:  cli
...
Input:     n/a
...
Diagnostics:
  - no session.shutdown or session.usage_checkpoint event found in this session; usage totals and cost are unavailable.
```

When a `session.usage_checkpoint` is available (a periodic cumulative
counter), its provider-native counters (`total_nano_aiu`,
`total_premium_requests`) are still reported under `provider_usage`, but the
shared `total` block (tokens, cost, cache ratio) stays unavailable — there is
no per-model token breakdown at checkpoint granularity to price. See
[How cost estimation works](../explanation/how-cost-estimation-works.md)
(Copilot CLI / Copilot App provider section) for the full breakdown of what
is and isn't available at each stage.

Batch and aggregate operations (`batch`, `--aggregate`) exclude sessions with
unavailable cost evidence from their totals rather than counting them as
zero; `summary.sessions_with_unavailable_cost` reports how many were
excluded.

## Subagent and skill attribution

`subagent.started`/`subagent.completed` events and each event's top-level
`agentId` field are used to attribute tool calls (and the skill active at
that moment) to the subagent that actually made them, instead of collapsing
everything into `main`. `--tool-breakdown` shows the resolved subagent name
(or the raw `agentId` when a `subagent.started` event wasn't captured) in its
`subagent` column. `provider_usage.subagents` separately preserves the raw
per-subagent evidence available from the event log (name, model, tool-call
count, a combined `total_tokens_reported`, and duration) — this is kept
apart from the shared, per-subagent `subagents` cost contract, which stays
empty for `cli` sessions because `subagent.completed` reports only a single
combined token count, not a validated input/output/cached split.

## What's different from the VS Code provider

- Per-skill **cost** breakdown (`--skill-breakdown`) has no data to report for
  `cli` sessions: `events.jsonl` only exposes cumulative session-level token
  totals, not per-request ones. `skills.detected` and `--tool-breakdown` are
  still fully populated, including subagent attribution (see above).
- The shared, per-subagent `subagents` block (cost split by subagent) is
  always empty for `cli` sessions — see "Subagent and skill attribution"
  above for the separate, evidence-preserving `provider_usage.subagents`.
- Provider-native counters (`total_nano_aiu`, `total_premium_requests`, and
  similar) are reported separately under `provider_usage` and never replace
  the shared token/estimated-USD calculation — including nanoAiu, which is
  informational only for this provider and is never used to compute
  `total.estimated_usd`.
- Pricing lookups for `cli`/`all` are local-only by default (no runtime
  pricing refresh attempt), unlike the `vscode` provider's default daily
  refresh attempt. Run `copilot-session-usage pricing refresh` to update
  pricing explicitly.
