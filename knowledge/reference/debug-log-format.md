---
type: Reference
title: Debug Log JSONL Format
description: Structure of Copilot debug log events, with focus on fields 
  relevant to cost extraction.
tags: [jsonl, debug-logs, events, schema]
timestamp: 2026-06-30T22:00:00Z
---

# Debug Log JSONL Format

## File Format

Each `.jsonl` file contains one JSON object per line. All events share a common envelope:

```json
{
  "ts": 1782843180454,
  "dur": 4690,
  "sid": "functions.runSubagent:16",
  "type": "llm_request",
  "name": "chat:Kimi-K2.6-azure",
  "spanId": "d038da43016b3a73",
  "parentSpanId": "2bced85c2ac2b7ac",
  "status": "ok",
  "attrs": { ... }
}
```

## Event Types Relevant to Cost

### `llm_request` — The Only Event With Token Data

This is the only event type that contains cost information. All other events (`session_start`, `user_message`, `turn_end`, `model_turn`, `tool_call`, etc.) do not contribute to token counts.

```json
{
  "type": "llm_request",
  "name": "chat:Kimi-K2.6-azure",
  "attrs": {
    "model": "Kimi-K2.6-azure",
    "inputTokens": 38393,
    "outputTokens": 275,
    "cachedTokens": 7552,
    "ttft": 3691,
    "responseId": "a0818079-6703-4688-89f9-80649e1bfb0a"
  }
}
```

| Field | Type | Meaning |
|-------|------|---------|
| `attrs.model` | string | Model identifier (e.g., `Kimi-K2.6-azure`, `gpt-4o`) |
| `attrs.inputTokens` | integer | Tokens consumed from context window |
| `attrs.outputTokens` | integer | Tokens generated |
| `attrs.cachedTokens` | integer | Tokens served from prompt cache |
| `attrs.ttft` | integer | Time to first token (ms) |

> **Mixed-model sessions:** A single `.jsonl` file can contain `llm_request` events from
> different models (e.g., 22 calls on `claude-sonnet-4.6` and 1 on `Kimi-K2.6-azure`).
> This happens when the user switches the active model mid-session or when the orchestrator
> selects different models for different turns.
>
> **Critical:** never pick a single "dominant model" by alphabetical sort to price the
> whole file — uppercase model names (like `Kimi-K2.6-azure`) sort before lowercase ones
> (like `claude-sonnet-4.6`), causing the cheaper model to be selected even when it handled
> less than 1% of the tokens. Always aggregate token counts per model and price each bucket
> independently.

### `child_session_ref` — Subagent Boundary Marker

Appears in `main.jsonl` to mark when a subagent starts and ends. Does NOT contain token data — the subagent's tokens are in its own `.jsonl` file.

```json
{
  "type": "child_session_ref",
  "attrs": {
    "childSessionId": "functions.runSubagent:16",
    "childTitle": "Skill Eval Grader"
  }
}
```

## Fields to Ignore for Cost Calculation

- `model_turn` — Marks a turn boundary, no token data
- `tool_call` / `tool_result` — Tool execution, no token data
- `user_message` / `assistant_message` — Message content, no token data
- `session_start` / `session_end` — Lifecycle events

## Extraction Pattern

```python
import json
from pathlib import Path

session_dir = Path(".../debug-logs/<session-id>")
for jsonl_file in session_dir.glob("*.jsonl"):
    with open(jsonl_file) as f:
        for line in f:
            obj = json.loads(line)
            if obj.get("type") == "llm_request":
                attrs = obj["attrs"]
                print(attrs["model"], attrs["inputTokens"], attrs["outputTokens"])
```

## Related

- [VS Code Copilot Extension](../structures/vscode-copilot-extension.md) — Where logs are stored
- [Subagent Cost Tracking](../structures/subagent-cost-tracking.md) — How subagent files correlate
