# CLI Reference

This page is auto-generated from the Click command definitions. For a
step-by-step guide on using `amend-commit` to inject session cost trailers
into Git commits, see [How to add a session cost trailer](../how-to/add-commit-trailer.md).

```{eval-rst}
.. click:: copilot_session_usage.cli:cli
   :prog: copilot-session-usage
   :nested: full
```

## Pricing commands

Use `pricing refresh` to explicitly update the user-level pricing snapshot.
The command respects the rolling 24-hour limit unless `--force` is supplied.
Its output includes the attempt timestamp and, after a successful refresh, the
latest captured pricing timestamp.
Use `pricing status` to inspect the cache location, timestamps, checksum, and
the most recent refresh error.

The legacy top-level `refresh-pricing` command remains available as an alias
for `pricing refresh`.
