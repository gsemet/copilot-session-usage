# Finding

An empirical, dated, falsifiable record of what an agent or human truthfully observed and believed at a point in time. The body is immutable once written; only lifecycle frontmatter (status, contradicted_by, superseded_by) may be appended later.

- [cache_write approximated via fresh_input — matches AIC panel exactly](cache-write-cost-not-tracked.md) — VS Code JSONL logs and agent-traces.db both lack cache_creation token counts. Approximating cache_creation as fresh_input = inputTokens - cachedTokens and billing only the incremental delta (cache_write - input) / 1M produces an exact match to the VS Code AIC panel. Implemented in estimate_cost since v0.3.  [Finding]
- [Subagent Logs Use runSubagent Prefix](subagent-logs-use-runsubagent-prefix.md) — Subagent activity is recorded in separate JSONL files prefixed with "runSubagent-" inside the session debug-logs directory.  [Finding]
- [title-*.jsonl adds 1 LLM call and its tokens to tool totals; VS Code panel excludes it](title-jsonl-not-counted-as-model-turn.md) — The VS Code Agent Debug panel "Model Turns" counter excludes title-generation calls. copilot-session-usage counts them. The delta is exactly the title-*.jsonl file's token counts.  [Finding]
