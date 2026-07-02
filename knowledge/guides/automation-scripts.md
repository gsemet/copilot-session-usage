---
type: Playbook
title: Automation Scripts for Cost Extraction
description: Where the real, maintained token-extraction logic lives, and how to
  reuse it instead of re-deriving it from scratch.
tags: [automation, python, scripts, extraction]
timestamp: 2026-07-01T00:00:00Z
links: [reference/debug-log-format.md, structures/subagent-cost-tracking.md]
backlinks: [guides/cost-optimization.md, structures/subagent-cost-tracking.md]
---

# Automation Scripts for Cost Extraction

## Don't Re-derive This — Reuse `_cost_core.py`

Earlier revisions of this document contained hand-rolled Python patterns for
parsing `.jsonl` files and aggregating token counts. Those patterns are now
**superseded by the actual, maintained, unit-tested implementation** in
`scripts/_cost_core.py`, and pasting the old patterns verbatim reintroduces a
known bug (see below) — this document is now just a pointer to that code.

If you need to extract or aggregate token costs outside of running the CLI:

```python
import sys
from pathlib import Path

sys.path.insert(0, "skills/Engineering/Generic/get-session-costs/scripts")
import _cost_core as core

pricing = core.load_pricing(Path("skills/Engineering/Generic/get-session-costs/scripts/vscode_session_cost.py"))
result = core.analyze_session(Path("/path/to/debug-logs/<session-id>"), pricing)
```

`core.analyze_session()` handles everything: reading every `.jsonl` file (not
just `main.jsonl`), per-model token bucketing, subagent name resolution, active
vs. wall-clock duration, and fallback-pricing detection. `core.shape_session()`
and `core.shape_batch()` apply the `--detail` levels described in `SKILL.md`.

## The Bug This Replaces

An earlier naive implementation picked a single "dominant model" per file
(often by alphabetical sort) and priced the whole file at that model's rate.
Because uppercase model names (`Kimi-K2.6-azure`) sort before lowercase ones
(`claude-sonnet-4.6`) in plain string comparison, this silently under-priced
mixed-model sessions by up to 2x. `core.analyze_session()` fixes this by
bucketing tokens per model and pricing each bucket independently — see
`knowledge/structures/subagent-cost-tracking.md` for the full story and
`tests/test_cost_core.py::test_analyze_session_multi_model_correct_cost` for
the regression test.

## Related

- `scripts/_cost_core.py` — the actual, maintained implementation
- [Debug Log Format](../reference/debug-log-format.md) — event schema reference
- [Subagent Cost Tracking](../structures/subagent-cost-tracking.md) — subagent aggregation details
