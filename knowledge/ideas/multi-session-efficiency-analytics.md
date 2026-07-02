---
type: Concept
title: Multi-Session Efficiency Analytics — Idea Specification
description: Cross-session analytics that group related VS Code Copilot sessions
  into coding tasks, score subagent efficiency, and surface trends in cost,
  latency, and behavior over time.
tags: [idea, vscode, copilot, multi-session, efficiency, trends, analytics, kpi]
timestamp: 2026-07-01T00:00:00Z
links: []
backlinks: []
---

# Multi-Session Efficiency Analytics — Idea Specification

## Status

Idea

## Problem Statement

A single coding task often spans multiple VS Code chat sessions due to network
issues, session restarts, or natural breaks. Analyzing sessions in isolation
misses the bigger picture: which subagent types are consistently expensive,
whether tasks are getting cheaper over time, and where agent behavior is
inefficient.

## Scope

- **Multi-session grouping:** Automatically or manually group related sessions
  into a single "coding task."
- **Subagent efficiency scoring:** Quantify how much value each subagent
  delivers relative to its cost.
- **Trend analysis:** Compare KPIs across tasks, time periods, or model
  migrations.
- **Out-of-scope:** Real-time monitoring (this is post-hoc analytics only).

## Session Grouping Strategy

A "coding task" is a logical unit of work that may span one or more VS Code
sessions. Grouping signals (in priority order):

1. **Same workspace folder** — sessions rooted in the same repo/folder.
2. **Time gap threshold** — sessions separated by less than *N* minutes
   (default 30 min) are considered contiguous.
3. **Shared git branch / Jira ticket** — if the session title or user messages
   reference the same ticket (e.g., `NESTOR-35603`).
4. **Manual override** — user provides an explicit list of session IDs.

If grouping is ambiguous, the tool emits candidate groups and lets the user
select or confirm.

## Top 10 KPIs

### 1. Task Cost (USD)

**Definition:** Sum of estimated USD cost across all sessions in the task.
**Why it matters:** The bottom-line metric for budgeting and ROI.
**Source:** Token sums × pricing table.

### 2. Cache Hit Ratio

**Definition:** `cachedTokens / inputTokens` across all sessions.
**Why it matters:** Higher ratios mean faster, cheaper runs. A drop signals
context-window churn or cache invalidation issues.
**Source:** `llm_request` events.

### 3. Subagent Cost Breakdown

**Definition:** Per-subagent-type aggregation of tokens, calls, and USD.
**Why it matters:** Identifies which subagent types are the biggest cost
drivers (e.g., "Explore" vs. "Task Inspector").
**Source:** `runSubagent-*.jsonl` files + `child_session_ref` mapping.

### 4. Subagent Efficiency Score

**Definition:** A composite score per subagent instance:

```
efficiency = (outputTokens + fileEdits * weight) / (inputTokens + durationSeconds * tokenRate)
```

where `fileEdits` is inferred from `create_file` / `replace_string_in_file`
events and `tokenRate` normalizes time to token-equivalent cost.

**Why it matters:** Distinguishes high-value subagents from token-wasting ones.
**Source:** `llm_request` + tool-call events.

### 5. Token Efficiency

**Definition:** `outputTokens / inputTokens` per session and per task.
**Why it matters:** Low ratio = lots of context for little result. Indicates
prompt bloat or overly broad subagent instructions.
**Source:** `llm_request` events.

### 6. Duration Breakdown (Think Time vs. API Time)

**Definition:**

- **API time:** Sum of individual LLM call durations (if available) or
  `llm_request` event density.
- **Think time:** Total task duration minus API time — tool execution,
  parsing, orchestration overhead.

**Why it matters:** Reveals whether latency is in the model or in the agent
framework.
**Source:** Event timestamps.

### 7. Tool-Call Frequency & Distribution

**Definition:** Count and breakdown of tool calls by type (`read_file`,
`run_in_terminal`, `semantic_search`, etc.).
**Why it matters:** Thrashing (e.g., 50 `read_file` calls for a small task)
indicates poor context management or redundant exploration.
**Source:** Tool-call events in `main.jsonl`.

### 8. Task Retry / Rework Rate

**Definition:** Percentage of tasks that required a follow-up session for the
same stated goal (inferred from session titles or user messages).
**Why it matters:** High rework = agent failing to complete tasks in one shot.
**Source:** Multi-session grouping + title/message similarity.

### 9. Model Migration Impact

**Definition:** Before/after comparison of cost and latency when the model
changes (e.g., GPT-5.4 → Claude Sonnet 4.6).
**Why it matters:** Quantifies the trade-off of switching models for specific
subagent types.
**Source:** `attrs.model` in `llm_request` events + time-bucketing.

### 10. Cost per Deliverable

**Definition:** Total task cost divided by a proxy for deliverables:
`git diff --stat` lines changed, files created, or test cases added.
**Why it matters:** Normalizes cost against actual output. A $5 task that
touches 200 lines is more efficient than a $2 task that touches 2 lines.
**Source:** Token cost ÷ git diff metrics (requires repo access).

## Proposed CLI Interface (illustrative)

```bash
# Auto-group sessions in a workspace into tasks and emit analytics
uv run multi-session-analytics.py --workspace /path/to/repo --since 2026-06-01

# Analyze a specific task by manual session IDs
uv run multi-session-analytics.py --sessions sessionA,sessionB,sessionC

# Compare two time periods
uv run multi-session-analytics.py --workspace /path/to/repo \
  --period-a 2026-05-01,2026-05-31 \
  --period-b 2026-06-01,2026-06-30

# Output JSON for dashboard ingestion
uv run multi-session-analytics.py --workspace /path/to/repo --format json
```

## Output Schema (illustrative)

```json
{
  "task_id": "auto-generated-or-user-provided",
  "workspace": "/path/to/repo",
  "session_count": 3,
  "sessions": ["uuid-a", "uuid-b", "uuid-c"],
  "time_range": {
    "started_at": "2026-06-30T09:00:00Z",
    "ended_at": "2026-06-30T11:30:00Z"
  },
  "kpis": {
    "total_cost_usd": 2.45,
    "cache_hit_ratio": 0.32,
    "token_efficiency": 0.28,
    "think_time_seconds": 4200,
    "api_time_seconds": 1800,
    "tool_calls": {
      "read_file": 45,
      "run_in_terminal": 12,
      "semantic_search": 8
    },
    "rework_rate": 0.15
  },
  "subagents": [
    {
      "type": "Explore",
      "instances": 4,
      "total_cost_usd": 0.98,
      "avg_efficiency_score": 1.24,
      "model_breakdown": {
        "gpt-5.4": 3,
        "claude-sonnet-4.6": 1
      }
    }
  ],
  "deliverables": {
    "lines_changed": 187,
    "files_created": 3,
    "cost_per_line_changed": 0.013
  }
}
```

## Tech Stack

- **Self-contained PEP 723 Python scripts** — same pattern as the shipped
  `get-session-costs` skill (`scripts/_cost_core.py` + provider CLIs).
- **Dependencies:** `gitpython` (for diff stats), `thefuzz` (for title
  similarity / grouping), `ruamel.yaml` (pricing table).
- **Output:** Structured JSON to stdout.

## UNRESOLVED Items

1. **Session grouping algorithm threshold** — what time gap (15 min, 30 min,
   60 min) optimally separates distinct tasks?
2. **Efficiency score weighting** — what is the right `weight` for file edits
   vs. output tokens? Needs empirical calibration.
3. **Git diff attribution** — how to attribute a git diff to a specific task
   when the user may have made manual edits between sessions?
4. **Model migration detection** — automatic or manual annotation of when a
   model switch occurred?

## Related Ideas

- `SKILL.md` / `scripts/_cost_core.py` — Single-session KPI extraction (already
  shipped; foundation for this idea).
