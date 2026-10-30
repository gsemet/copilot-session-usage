# Export to JSON

Use `--format json` to get machine-readable output for scripting, dashboards,
or storage.

## Write to stdout

```bash
copilot-session-usage latest --format json
```

## Write to a file

```bash
copilot-session-usage latest --format json --output session.json
```

## Extract a single field with jq

```bash
# Estimated cost
copilot-session-usage latest --format json | jq '.total.estimated_usd'

# All model names called in the session
copilot-session-usage latest --format json | jq '[.models[].model]'

# Total cached tokens (input_tokens already includes them)
copilot-session-usage latest --format json | jq '.total.cached_tokens'
```

Session JSON carries `"schema_version": 2`. Token fields are explicit
(`input_tokens` includes cache reads and writes; see
[Don't recompute costs yourself](../explanation/how-cost-estimation-works.md#dont-recompute-costs-yourself)).
`total_tokens`, `cost_per_1m_*`, `split_ratio` and `avg_cache_ratio` no longer
exist.

## Batch export

Export the last 20 sessions as a single JSON document:

```bash
copilot-session-usage batch 20 --format json --output week.json
```

The document has `schema_version`, `summary` (aggregate) and `sessions`
(per-session list).

```bash
# Total cost across all sessions
cat week.json | jq '.summary.estimated_usd'

# Cost per session, sorted descending
cat week.json | jq '[.sessions[] | {title, cost: .total.estimated_usd}] | sort_by(-.cost)'
```

## Export every LLM call (JSONL)

```bash
copilot-session-usage --agent all calls --last 7d --output calls.jsonl
```

One JSON object per line, with `session_id`, `provider`, `ts`, `model`,
`input_tokens`, `cached_tokens`, `cache_write_tokens`, `uncached_input_tokens`,
`output_tokens`, `estimated_usd`, `cost_source`, `kind` and more. Use it
instead of parsing the raw logs.

## Use with the Python API

```python
from pathlib import Path
from copilot_session_usage.api import analyze_latest, batch_analyze, list_calls
import json

# Latest session as a dict
result = analyze_latest(detail="full")
print(json.dumps(result, indent=2))

# Last 10 sessions
batch = batch_analyze(10, detail="compact")
for s in batch["sessions"]:
    print(f"{s['title']}: ${s['total']['estimated_usd']:.4f}")

# Normalized per-call records
calls = list_calls(agent="cli", since="2026-07-01T00:00:00Z")
```
