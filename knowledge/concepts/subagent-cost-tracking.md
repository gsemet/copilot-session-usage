---
type: Concept
title: Subagent Cost Tracking
description: How subagent costs are logged, aggregated, and correlated with 
  parent sessions.
tags: [subagents, cost-aggregation, parallel-agents, runSubagent]
timestamp: 2026-06-30T22:00:00Z
---

# Subagent Cost Tracking

## Architecture

When a parent agent spawns subagents via `runSubagent`:

1. **Parent session** (`main.jsonl`) gets `child_session_ref` events marking subagent boundaries
2. **Each subagent** gets its own `.jsonl` file: `runSubagent-<name>-functions.runSubagent:<id>.jsonl`
3. **Subagent `.jsonl` files contain `llm_request` events** with full token data
4. **The debug panel aggregates all files** in the session directory

## Critical Discovery

> Subagent `.jsonl` files DO contain `llm_request` events. Previous assumptions that they only contained lifecycle events (`session_start`, `turn_end`) were incorrect. The token data is there — agents must iterate over ALL `.jsonl` files, not just `main.jsonl`.

## File Naming Convention

```
runSubagent-<agent-name>-functions.runSubagent:<id>.jsonl
```

Example: `runSubagent-default-functions.runSubagent:19.jsonl`

The `<id>` is a sequential number assigned per `runSubagent` call in the parent session.

## Cost Distribution Pattern

In typical skill evaluation sessions:

| Component | Typical Share | Notes |
|-----------|--------------|-------|
| Parent (`main.jsonl`) | 20-30% | Orchestration, planning, result aggregation |
| Subagent 1 | 15-25% | First parallel task |
| Subagent 2 | 15-25% | Second parallel task |
| Additional subagents | 10-20% each | Grading, comparison, follow-up |

Subagents often account for **70-80% of total cost**.

## Sessions Without Subagents

Not all sessions spawn subagents. When a session contains only direct
agent-user interaction (no `runSubagent` calls), the debug log directory
contains only:

```
debug-logs/<session-id>/
├── main.jsonl              ← all token data lives here
├── title-<uuid>.jsonl      ← title generation (negligible tokens)
├── models.json
├── system_prompt_*.json
└── tools_*.json
```

In this case **100% of token costs are in `main.jsonl`**. The debug panel
totals match exactly what `main.jsonl` contains. This is common for:

- Interactive exploration and Q&A
- Single-step tasks that don't parallelize
- Sessions where the agent does research rather than dispatching subagents

Example: a session titled *"Get subagent token costs"* that explores how
cost tracking works without actually spawning subagents will show 7 files
but only 2 `.jsonl` files, with `main.jsonl` containing all ~8.7M input
tokens.

## Mixed-Model Files and Cost Attribution

A single `.jsonl` file (including `main.jsonl`) can contain calls from
**multiple models** in the same session. This happens when:

- The user switches the active model between turns
- The orchestrator routes different turns to different models (e.g., cheap
  model for planning, expensive model for coding)

**Observed real-world case:** "Create get-session-costs skill" session —
`main.jsonl` had 22 calls on `claude-sonnet-4.6` (1.89M tokens) and 1 call
on `Kimi-K2.6-azure` (6k tokens). Alphabetical sort places `Kimi` before
`claude`, so a naive implementation priced all tokens at Kimi's cheap rate:
reported **$0.127** vs. true **$0.265** — a **2× underestimate**.

**Correct approach:** build per-model token buckets inside the JSONL parser
and price each bucket independently:

```python
per_model = {}
for event in llm_requests:
    m = event["attrs"]["model"]
    bucket = per_model.setdefault(m, {"input": 0, "output": 0, "cached": 0})
    bucket["input"]  += event["attrs"]["inputTokens"]
    bucket["output"] += event["attrs"]["outputTokens"]
    bucket["cached"] += event["attrs"]["cachedTokens"]

total_cost = sum(estimate_cost(**b, model=m, pricing=pricing) for m, b in per_model.items())
```

## Correlating Subagents to Tasks

The `child_session_ref` event in `main.jsonl` links the numeric ID to the agent name:

```json
{
  "type": "child_session_ref",
  "attrs": {
    "childSessionId": "functions.runSubagent:19",
    "childTitle": "Skill Eval Grader"
  }
}
```

## Extraction Script Pattern

```python
from pathlib import Path
import json

session_dir = Path(".../debug-logs/<session-id>")

for jsonl_file in session_dir.glob("*.jsonl"):
    agent_name = jsonl_file.name
    total_input = total_output = total_cached = calls = 0
    model = "unknown"

    with open(jsonl_file) as f:
        for line in f:
            obj = json.loads(line)
            if obj.get("type") == "llm_request":
                attrs = obj["attrs"]
                total_input += attrs.get("inputTokens", 0)
                total_output += attrs.get("outputTokens", 0)
                total_cached += attrs.get("cachedTokens", 0)
                calls += 1
                if model == "unknown":
                    model = attrs.get("model", "unknown")

    if calls > 0:
        print(f"{agent_name}: {model} | {total_input:,} in / {total_output:,} out | {calls} calls")
```

## Related

- [Debug Log Format](../reference/debug-log-format.md) — Event structure
- [Automation Scripts](../guides/automation-scripts.md) — Complete reference implementations
