---
type: Finding
title: "title-*.jsonl adds 1 LLM call and its tokens to tool totals; VS Code panel
  excludes it"
description: The VS Code Agent Debug panel "Model Turns" counter excludes
  title-generation calls. copilot-session-usage counts them. The delta is
  exactly the title-*.jsonl file's token counts.
tags: [token-counting, title-generation, panel-vs-tool, verified]
confidence: confirmed
context: >-
  Observed by comparing VS Code Agent Debug panel metrics against
  copilot-session-usage output for session 438d24a8. The delta in turns,
  input tokens, and output tokens matched exactly the title-generation
  JSONL file.
timestamp: 2026-07-02T22:00:00Z
links: []
backlinks: [structures/subagent-cost-tracking.md,
    structures/vscode-copilot-extension.md]
---

# Finding: title-*.jsonl not counted as "Model Turn" by VS Code panel

## Observed

Session `438d24a8` at the same snapshot:

| Metric | VS Code panel | copilot-session-usage | Delta |
|--------|---------------|-----------------------|-------|
| Turns/calls | 96 | 97 | +1 |
| Input tokens | 8,831,919 | 8,832,360 | +441 |
| Output tokens | 58,784 | 60,029 | +1,245 |
| Cached tokens | 8,097,846 | 8,097,846 | 0 |

The delta matches exactly the `title-ca686498-...jsonl` file:
`model=Kimi-K2.6-azure  input=441  cached=0  output=1,245`

## Explanation

VS Code "Model Turns" counts only the main conversation turns.
The title-generation call (one `llm_request` in `title-*.jsonl`) is a
background call VS Code excludes from the panel display.

`copilot-session-usage` counts **all** `llm_request` events across all
`*.jsonl` files in the session directory, including `title-*.jsonl`.

## Implication

The tool over-counts by 1 call and the title call's tokens vs. the panel.
This is intentional: title-generation consumes real tokens and should be
included in cost tracking.
