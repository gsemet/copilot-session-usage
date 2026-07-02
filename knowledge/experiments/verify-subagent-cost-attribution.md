---
type: Experiment
title: Verify Subagent Cost Attribution
description: >-
  Check that subagent token costs are attributed to their runSubagent call and
  not double-counted in the parent session total.
tags: [subagent, cost, attribution, verification]
timestamp: 2026-07-02T00:00:00Z
hypothesis: >-
  Tokens consumed inside a runSubagent-*.jsonl stream are counted once, and the
  parent session total equals the sum of the main stream plus each subagent
  stream.
steps: [Pick a session directory that contains at least one runSubagent-*.jsonl 
    file., Run `copilot-session-usage analyze <session-dir> --detail full 
    --format json`., Record the parent total tokens and the per-subagent token 
    subtotals., Independently sum tokens from main.jsonl and each 
    runSubagent-*.jsonl., Compare the tool's total against the independent sum.]
expected_signals: ['Tool total equals independent sum (no double-count, no omission).',
  Each subagent subtotal is attributed to its own runSubagent id.]
max_runs: 2
status: proposed
---

# Verify Subagent Cost Attribution

An example Experiment. Running it produces a dated Finding recording whether the
hypothesis held for the sessions tested, with the reporter's confidence and
context at that time. Link the produced Finding back here via `derived_findings`
and set `derived_from` on the Finding.
