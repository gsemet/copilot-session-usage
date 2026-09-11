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
  "report": "span",
  "period": {
    "since": "ISO bound or null",
    "until": "ISO bound or null",
    "last": "rolling duration or null"
  },
  "total": {},
  "models": [],
  "sessions": []
}
```

`total` contains the cross-session totals:

- `session_count`
- `total_input_tokens`
- `total_output_tokens`
- `total_cached_tokens`
- `total_tokens`
- `total_llm_calls`
- `total_estimated_usd`
- `avg_cache_ratio`
- `cost_per_1m_tokens`
- `total_duration_seconds`
- `total_active_duration_seconds`
- `fallback_pricing_models`
- `sessions_with_unavailable_cost`

Each `models` row contains `model`, `session_count`, input/output/cached
tokens, `llm_calls`, `estimated_usd`, `split_ratio`, and
`cost_per_1m_input_tokens`.

Each `sessions` row is intentionally minimal: `session_id`, `provider`,
`title`, `started_at`, `ended_at`, `duration_seconds`,
`active_duration_seconds`, `models`, and a `total` block. A `null` value means
the source did not provide reliable evidence; it must not be presented as
zero. Sessions with unavailable cost evidence are counted in
`sessions_with_unavailable_cost` and excluded from estimated cost totals.

## Response template

Render the result in this order:

```markdown
## Cost breakdown: <period>

### Total

| Sessions | Input | Output | Cached | Cache ratio | LLM calls | Estimated cost |
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
