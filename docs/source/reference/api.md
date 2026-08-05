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
for the full field list.

## Pricing lifecycle

`load_pricing(ref_dir=None, auto_refresh=True)` loads the newest valid pricing
source. With the default arguments it performs a throttled runtime refresh
attempt before selecting between the user cache and bundled fallback. Set
`auto_refresh=False` for offline or tightly controlled callers. Supplying
`ref_dir` always loads that directory directly and never contacts the network.

`refresh_pricing(force=False)` explicitly refreshes the user cache and returns a
`PricingRefreshResult` with a status of `updated`, `unchanged`, `skipped`, or
`failed`. Use `force=True` to bypass the rolling 24-hour limit. The
`pricing_status()` helper returns cache paths and the last refresh metadata.
