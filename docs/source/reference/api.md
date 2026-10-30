# Python API Reference

## `copilot_session_usage.api`

All public functions are in `copilot_session_usage.api`.

```{eval-rst}
.. automodule:: copilot_session_usage.api
   :members:
   :undoc-members:
   :show-inheritance:
```

## Internal models

These return types are produced by the API. They are plain dicts shaped
by the `detail` parameter — see [How Cost Estimation Works](../explanation/how-cost-estimation-works.md)
for the field semantics. JSON-shaped results carry `schema_version: 2`.

Every token block (session `total`, `model_breakdown`, `subagents`,
`skills.breakdown`, span/batch totals) uses the same explicit fields:
`input_tokens` (includes cache reads and writes), `cached_tokens`,
`cache_write_tokens` (`None` on VS Code), `uncached_input_tokens`,
`output_tokens`, `llm_calls`, `estimated_usd` and `cost_source`
(`billed`, `estimated` or `mixed`). Totals also have a token-weighted
`cache_ratio` and `compaction` (`calls`, `estimated_usd`); sessions add
`initiator_breakdown`, and sessions and summaries add a `reconciliation` block
(`billed_usd`, `estimated_from_tokens_usd`, `delta_pct`,
`calls_without_billing`, plus `snapshot_usd`/`snapshot_delta_usd` for CLI).

`aggregate_sessions` returns a flat summary with the same fields. The old
`total_tokens`, `cost_per_1m_*`, `split_ratio`, `avg_cache_ratio`,
`total_*`-prefixed aggregate keys, aggregate `total_*_duration`,
`provider_usage.subagents` and `unattributed_usd` fields no longer exist.

## Exporting calls

`list_calls(...)` returns every priced LLM call as a list of dicts sorted by
`(ts_ms, session_id)`; `iter_calls(...)` iterates the same records. It accepts
`path`, `agent`, `workspace_roots`, `since`, `until`, `name_pattern`,
`workspace_filter`, `limit` and `auto_refresh`. Each dict has `session_id`,
`provider`, `ts_ms`, `ts`, `model`, `input_tokens`, `cached_tokens`,
`cache_write_tokens`, `uncached_input_tokens`, `output_tokens`, `llm_calls`,
`nano_aiu`, `estimated_usd`, `cost_source`, `agent`, `agent_id`, `initiator`,
`kind` (`request` or `compaction`) and `skill`. Consume these records instead of
parsing logs or recomputing costs.

```python
from copilot_session_usage.api import list_calls

calls = list_calls(agent="cli", since="2026-07-01T00:00:00Z")
total = sum(c["estimated_usd"] for c in calls)
```

`since`/`until` (and `--last` on the CLI) filter **calls** by timestamp; a
session with no in-window call is dropped.

## Pricing lifecycle

`load_pricing(ref_dir=None, *, auto_refresh=False)` loads the newest valid
pricing source offline: the user cache if present, otherwise the bundled
table. Analysis functions never refresh pricing implicitly; pass
`auto_refresh=True` (to `load_pricing` or the analysis functions that accept it)
to opt in to a throttled runtime refresh attempt. Supplying `ref_dir` always
loads that directory directly and never contacts the network. The table is a
fallback only, used for calls that have no billed nanoAIU.

`refresh_pricing(force=False)` explicitly refreshes the user cache and returns a
`PricingRefreshResult` with a status of `updated`, `unchanged`, `skipped`, or
`failed`. Use `force=True` to bypass the rolling 24-hour limit. The
`pricing_status()` helper returns cache paths and the last refresh metadata.
