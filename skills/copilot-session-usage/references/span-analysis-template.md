# Date-span analysis reference

Use this contract for requests covering multiple sessions in a date window
("today", "yesterday", "last week", or explicit dates). The goal is to make
one CLI call and return only the evidence needed for a useful breakdown.

## Preferred invocation

Resolve a natural-language period to ISO 8601 bounds in the user's local
timezone, then run one command:

```bash
copilot-session-usage --agent all span \
  --since 2026-09-11T00:00:00+02:00 \
  --until 2026-09-11T20:19:00+02:00 \
  --format json
```

Use `--agent cli` or `--agent vscode` when the user explicitly limits the
provider. Use `--last 7d` for a rolling window when calendar boundaries are not
important. Add `--title`, `--name`, or `--workspace` before analysis when the
user requests a narrower subset.

Do not implement this workflow as `list` followed by one `analyze` call per
session. The `span` command discovers and analyzes the matching sessions in a
single invocation and omits full skills, subagents, diagnostics, and pricing
notes from its JSON output.

## JSON contract

The compact report has exactly these top-level sections:

```json
{
  "schema_version": 2,
  "report": "span",
  "period": {
    "since": "ISO bound or null",
    "until": "ISO bound or null",
    "last": "rolling duration or null"
  },
  "total": {},
  "reconciliation": {},
  "models": [],
  "sessions": []
}
```

`--since`, `--until` and `--last` select **calls** by timestamp. A session is
listed only if it has an in-window call, and its figures count only those calls.

`total` contains the cross-session totals (flat keys, no `total_` prefix):

- `session_count`
- `input_tokens` (INCLUDES cache reads and writes)
- `cached_tokens` (cache read)
- `cache_write_tokens` (`null` when the provider does not log it, i.e. VS Code)
- `uncached_input_tokens` (input minus cached minus cache-written)
- `output_tokens`
- `llm_calls`
- `estimated_usd`
- `cost_source` (`billed`, `estimated` or `mixed`)
- `cache_ratio` (token-weighted: cached / input)
- `compaction` (`calls`, `estimated_usd`)
- `fallback_pricing_models`
- `sessions_with_unavailable_cost`

`reconciliation` holds `billed_usd`, `estimated_from_tokens_usd`, `delta_pct`
and `calls_without_billing`; it is also present on each session (CLI adds
`snapshot_usd` and `snapshot_delta_usd`).

Each `models` row contains `model`, `session_count`, the same explicit token
fields, `llm_calls`, `estimated_usd` and `cost_source`.

Do not compute `total_tokens`, cost per million tokens, split ratios or
average cache ratios: they were removed because they double-count cache or mix
scopes. Never recompute costs from the token counts; use `estimated_usd`, or
`copilot-session-usage calls` for per-call records.

Each `sessions` row is intentionally minimal: `session_id`, `provider`,
`title`, `started_at`, `ended_at`, `duration_seconds`,
`active_duration_seconds`, `models`, a `total` block and a `reconciliation`
block. A `null` value means
the source did not provide reliable evidence; it must not be presented as
zero. Sessions with unavailable cost evidence are counted in
`sessions_with_unavailable_cost` and excluded from estimated cost totals.

## Response template

Render the result in this order:

```markdown
## Cost breakdown: <period>

### Total

| Sessions | Input (incl. cache) | Output | Cached | Cache ratio | LLM calls | Cost |
|---:|---:|---:|---:|---:|---:|---:|
| <...> | <...> | <...> | <...> | <...> | <...> | <...> |

### Per model

| Model | Sessions | Input | Output | Cached | Calls | Estimated cost |
|---|---:|---:|---:|---:|---:|---:|
| <...> | <...> | <...> | <...> | <...> | <...> | <...> |

### Per session

| Started | Title | Provider | Duration | Calls | Input | Output | Cached | Cost |
|---|---|---|---:|---:|---:|---:|---:|---:|
| <...> | <...> | <...> | <...> | <...> | <...> | <...> | <...> | <...> |

### Evidence notes

- <Mention unavailable sessions, fallback pricing, or other material caveats.>
```

Keep the answer focused on the requested period. Do not reproduce the raw
session payload unless the user asks for diagnostics or skill/subagent detail.
