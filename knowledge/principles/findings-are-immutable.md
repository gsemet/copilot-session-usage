---
type: Principle
title: Findings Are Immutable
description: A recorded Finding's body is never reworded or deleted — only
  linked.
tags: [meta, findings, immutability, integrity]
timestamp: 2026-07-02T00:00:00Z
rationale: >-
  Findings are the honest historical record of what someone believed at a point
  in time. Rewriting them would destroy the audit trail and let hindsight
  rewrite the past. Contradictions must be expressed by adding new knowledge,
  not by editing old knowledge.
authority: human-reviewed
links: []
backlinks: []
---

# Findings Are Immutable

## Rule

Once a Finding is written, its **body and claim are frozen**. Never reword,
soften, or delete a Finding — even when it turns out to be wrong.

## Allowed changes

Only the reserved lifecycle frontmatter fields may be appended:

- `status: contradicted | superseded`
- `contradicted_by: [<finding-id>, …]`
- `superseded_by: [<finding-id>, …]`

Everything else in the file stays exactly as first recorded.

## How contradictions are expressed

A newer Finding carries `contradicts:` / `supersedes:` pointing at the old
Finding's ID. The `consolidate-knowledge-base` skill then appends the
metadata-only backlink on the old Finding. The old claim remains readable as a
record of what was believed then.
