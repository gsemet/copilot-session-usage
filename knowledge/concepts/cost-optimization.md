---
type: Playbook
title: Cost Optimization Patterns
description: Common patterns that inflate session costs and strategies to reduce
  them.
tags: [optimization, cost-reduction, context-window, caching]
timestamp: 2026-06-30T22:00:00Z
---

# Cost Optimization Patterns

## Cost Drivers

### 1. Large Context Windows

Every `llm_request` includes the full conversation history plus file context. Long sessions accumulate tokens rapidly.

| Pattern | Impact | Mitigation |
|---------|--------|------------|
| Iterative refinement | High — same files re-read each turn | Use `replace_string_in_file` instead of regenerating full files |
| Broad semantic searches | High — many files loaded into context | Narrow search scope with `includePattern` |
| Recursive directory reads | Medium — unnecessary file contents | Read specific files, not entire trees |

### 2. Subagent Overhead

Each subagent spawns a new context. Parallel subagents multiply costs:

| Scenario | Typical Cost | Alternative |
|----------|-------------|-------------|
| 3 parallel eval subagents | 3× single agent cost | Sequential execution if latency allows |
| Deep subagent chains | Exponential growth | Flatten hierarchy where possible |
| Subagents with large file reads | Amplified by parallel count | Pre-filter files in parent |

### 3. Cache Efficiency

`cachedTokens` represents prompt tokens served from cache (not billed). High cache ratios are good.

| Cache Ratio | Interpretation |
|-------------|---------------|
| >80% | Excellent — most context reused |
| 50-80% | Good — some reuse |
| <50% | Poor — context churning, investigate |

## Strategies for Agents

1. **Prefer targeted edits** over full-file regeneration
2. **Use `grep_search` before `semantic_search`** for precise lookups
3. **Batch tool calls** where possible (reduces round-trips)
4. **Terminate subagents early** when task is complete
5. **Reuse context** by keeping related work in the same session

## Related

- [Subagent Cost Tracking](./subagent-cost-tracking.md) — Understanding subagent cost distribution
- [Automation Scripts](../guides/automation-scripts.md) — Scripts to measure before/after
