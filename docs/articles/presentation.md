## Title

I built `copilot-session-usage`: inspect the token usage and estimated cost of VS Code Copilot sessions

## Post

I’ve released [`copilot-session-usage`](https://github.com/gsemet/copilot-session-usage), an open-source Python CLI for analyzing VS Code Copilot sessions.

VS Code’s UI does not provide a detailed per-session cost report. This tool reads the local Copilot debug logs and reports:

- Input, output, and cached token counts
- Models used during a session
- Estimated cost in USD
- Main-conversation versus subagent usage
- Cost and tool-call attribution by skill
- Aggregate spending across sessions, workspaces, dates, or features
- JSON output for scripts and a Python API for integration
- Optional Git commit trailers containing session usage

It supports multi-model sessions, cache-aware pricing, long-context pricing tiers, macOS, Linux, Windows, and WSL2. For Copilot-plan models, it uses the usage value recorded by VS Code when available. For externally billed Azure-hosted models, it falls back to token-based pricing, so reports should be treated as estimates.


## What this project adds

`copilot-session-usage` reads the original VS Code Copilot debug logs and turns them into
repeatable reports. It provides:

| Need | Chronicle | `copilot-session-usage` |
| --- | --- | --- |
| Conversational search and summaries | ✅ | ✅ CLI reports are interpreted by your agent |
| Session discovery by title or ID | ✅ | ✅ |
| Aggregate tokens | ✅  | ✅ |
| Aggregate estimated cost | ⚠️ When available; aggregate only | ✅ |
| Tokens **per model** | ⚠️ LLM digging each time; consumes tokens | ✅ |
| Estimated cost (`$`) **per model** | ❌ No accurate cost per breakdown | ✅ |
| Tokens **per subagent** | ⚠️ LLM digging each time; consumes tokens | ✅ |
| Estimated cost (`$`) **per subagent** | ❌ No accurate cost per breakdown | ✅ |
| Cost attribution to skills | ❌ Cannot provide cost per breakdown | ✅ |
| Tool-call counts by skill and subagent | ⚠️ LLM digging each time | ✅ |
| Batch analysis, filtering, and aggregation | Limited/conversational | ✅ |
| Stable JSON, table, and detailed output | No stable contract | ✅ |
| Python API for embedding in third-party tools | ❌ | ✅ |
| Pricing provenance and custom model rates | ⚠️ Only for aggregated costs | ✅ |
| Git commit cost trailers | ❌ | ✅ |

## Example

A typical workflow is simply:

`uv tool install copilot-session-usage`

Then search for a session ID:

`copilot-session-usage find "Get execution costs with Chronicle"`

And get details:

```bash
$ copilot-session-usage id "31c51cee-cb1c-4aa5-8c55-83479bcf54da" --format detailed
Session:   31c51cee-cb1c-4aa5-8c55-83479bcf54da
Title:     Get execution costs with Chronicle
Started:   2026-08-08T09:16:00Z
Duration:  1588s  (active: 916s)
Models:    claude-opus-4.8, gpt-5.6-luna
Input:     7,463,752 tokens
Output:    39,243 tokens
Cached:    7,050,320 (94%)
LLM calls: 76
Est. cost: $1.8836

Per-Model Breakdown:
  Model                Input     Cached  Output  Calls   Cost
  -----------------------------------------------------------
  claude-opus-4.8  1,411,792  1,289,047   9,955     13  $1.66
  gpt-5.6-luna     6,051,960  5,761,273  29,288     63  $0.22

Subagents:
  Name                                                      Model                Input     Cached  Output   Cost
  --------------------------------------------------------------------------------------------------------------
  main                                                      gpt-5.6-luna     6,051,960  5,761,273  29,288  $0.22
  Subagent — Claude Opus 4.8-call_CgcUaex8Erf1nChCvxHJtT01  claude-opus-4.8  1,411,792  1,289,047   9,955  $1.66
```

Default output is json, perfect for an agent.

You can also analyze several sessions together or filter them by title, date, workspace, or skill.

This is useful if you use Copilot for substantial agentic work and want a clearer record of what different sessions, models, subagents, or skills actually consumed. It can help with budgeting, comparing workflows, investigating cache usage, and building an auditable usage history without manually inspecting JSONL logs.

It is MIT-licensed and available on [GitHub](https://github.com/gsemet/copilot-session-usage) and [PyPI](https://pypi.org/project/copilot-session-usage/).
