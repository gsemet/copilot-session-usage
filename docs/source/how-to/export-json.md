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
copilot-session-usage latest --format json | jq '.estimated_cost_usd'

# All model names called in the session
copilot-session-usage latest --format json | jq '[.models[].model]'

# Total cached tokens
copilot-session-usage latest --format json | jq '.total_cached_tokens'
```

## Batch export

Export the last 20 sessions as a single JSON document:

```bash
copilot-session-usage batch 20 --format json --output week.json
```

The document has two top-level keys: `summary` (aggregate) and `sessions`
(per-session list).

```bash
# Total cost across all sessions
cat week.json | jq '.summary.estimated_cost_usd'

# Cost per session, sorted descending
cat week.json | jq '[.sessions[] | {title, cost: .estimated_cost_usd}] | sort_by(-.cost)'
```

## Use with the Python API

```python
from pathlib import Path
from copilot_session_usage.api import analyze_latest, batch_analyze
import json

# Latest session as a dict
result = analyze_latest(detail="full")
print(json.dumps(result, indent=2))

# Last 10 sessions
batch = batch_analyze(10, detail="compact")
for s in batch["sessions"]:
    print(f"{s['title']}: ${s['estimated_cost_usd']:.4f}")
```
