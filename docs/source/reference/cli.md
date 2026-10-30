# CLI Reference

This page is auto-generated from the Click command definitions. For a
step-by-step guide on using `amend-commit` to inject session cost trailers
into Git commits, see [How to add a session cost trailer](../how-to/add-commit-trailer.md).

```{eval-rst}
.. click:: copilot_session_usage.cli:cli
   :prog: copilot-session-usage
   :nested: full
```

## Per-call usage

All commands share one per-call pipeline for VS Code and Copilot CLI/App
sessions; JSON reports carry `"schema_version": 2`. Analysis is offline: pricing
is never refreshed automatically (see below).

- `--since`, `--until` and `--last` select **calls** by their own timestamp.
  A session is included when it has at least one in-window call, and its totals
  then reflect only those calls; sessions with no in-window call are dropped.
  `--last` is available on `span`, `skills` and `calls`.
- `calls` exports one JSON object per priced LLM call (JSONL):
  `session_id`, `provider`, `ts_ms`, `ts`, `model`, `input_tokens` (includes
  cache read and write), `cached_tokens`, `cache_write_tokens` (`null` on VS
  Code), `uncached_input_tokens`, `output_tokens`, `llm_calls`, `nano_aiu`,
  `estimated_usd`, `cost_source` (`billed`/`estimated`), `agent`, `agent_id`,
  `initiator`, `kind` (`request`/`compaction`) and `skill`. It accepts
  `--last`, `--since`, `--until`, `--workspace`, `--name`, `--title`, `--limit`
  and `--output`; use the global `--agent` to pick the provider.

  ```bash
  copilot-session-usage --agent cli calls --last 7d --output calls.jsonl
  ```

- Reports no longer contain `total_tokens`, `cost_per_1m_*`, `split_ratio`,
  `avg_cache_ratio`, `total_*`-prefixed aggregate keys, aggregate
  `total_*_duration`, `provider_usage.subagents` or `unattributed_usd`. They add
  `schema_version`, `cache_write_tokens`, `uncached_input_tokens`, `llm_calls`,
  `cost_source`, a weighted `cache_ratio`, `compaction`, `initiator_breakdown`
  and a `reconciliation` block.
- Don't recompute costs yourself: see
  [the pitfalls](../explanation/how-cost-estimation-works.md#dont-recompute-costs-yourself).

## Pricing commands

Analysis commands never refresh pricing. Use `pricing refresh` to explicitly update the user-level pricing snapshot.
The command respects the rolling 24-hour limit unless `--force` is supplied.
Its output includes the attempt timestamp and, after a successful refresh, the
latest captured pricing timestamp.
Use `pricing status` to inspect the cache location, timestamps, checksum, and
the most recent refresh error.

The legacy top-level `refresh-pricing` command remains available as an alias
for `pricing refresh`.
