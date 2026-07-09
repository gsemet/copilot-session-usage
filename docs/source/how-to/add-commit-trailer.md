# Add a Session Cost Trailer to a Commit

Use `amend-commit` to append per-model token usage to the current Git commit
as machine-readable trailers. This is useful for attributing cost to a change
after a Copilot coding session, without editing the commit message by hand.

## What the trailer looks like

One `Copilot-Session-Usage-Acc` trailer is added per model used in the
session, followed by a single `Copilot-Session-Usage-AIC` total-cost trailer:

```text
Copilot-Session-Usage-Acc: Moonshot AI:Kimi K2.7 Code,in:24.90,out:0.06,cache:21.88,aic:231
Copilot-Session-Usage-Acc: Anthropic:Claude Haiku 4.5,in:0.03,out:0,cache:0,aic:1
Copilot-Session-Usage-AIC: 232
```

Beware, the costs are **accumulated** for the entire session, not just the current commit.
If you commit multiple times during a session, the trailers will reflect the total usage
up to that point.

When a change spans several VS Code Copilot sessions, pass each session ID
with a separate `--session-id` argument. The costs are merged before the
trailers are written. Add `--with-session-id` to also burn one
`Copilot-Session-Usage-Session-ID` trailer per session ID, which is useful
when you later want to rewrite the commit chain with commit-accurate costs.

The vendor and model name come from the bundled pricing data. Vendor names are
rendered with human-readable casing (`Moonshot AI`, `Anthropic`, `OpenAI`, …),
and model names keep the casing from `data/models-and-pricing.yml`.

Token counts are expressed in millions of tokens with two decimals. The
`aic` value and the `Copilot-Session-Usage-AIC` line show the cost in AI
credits (1 AIC = $0.01) with two decimals. If the commit already contains
`Copilot-Session-Usage-Acc` or `Copilot-Session-Usage-AIC` trailers, they are
replaced so the values stay fresh. Other trailers, such as `Signed-off-by`,
are preserved and kept at the end of the message.

## From VS Code Copilot context

When running inside a VS Code Copilot agent session, the session log is exposed
as the context variable `VSCODE_TARGET_SESSION_LOG`. Its value looks like:

```text
# Mac:
/Users/<you>/Library/Application Support/Code/User/workspaceStorage/<hash>/GitHub.copilot-chat/debug-logs/<session-id>
```

The session ID is the last path component. Extract it and pass it to
`amend-commit`:

```bash
SESSION_ID=$(basename "{{VSCODE_TARGET_SESSION_LOG}}")
copilot-session-usage amend-commit --session-id "$SESSION_ID"
```

`VSCODE_TARGET_SESSION_LOG` is provided by VS Code Copilot as a **context**
variable, not as an environment variable. If it is not available, use one of
the methods below to locate the session ID manually.

## Find the session ID manually

List recent sessions and pick the right one:

```bash
# Show recent sessions with IDs and titles
copilot-session-usage list --format table

# Search by title substring
copilot-session-usage list --title "refactor auth" --format table
```

Then pass the UUID to `amend-commit`:

```bash
copilot-session-usage amend-commit --session-id 3a91c012-1b4e-4c8a-9f72-ab12cd34ef56
```

## Multiple sessions per commit

If a single change spanned several VS Code Copilot sessions, provide all
session IDs. The token counts and costs are accumulated and written as one
trailer block:

```bash
copilot-session-usage amend-commit \
  --session-id "abc-123" \
  --session-id "def-456" \
  --session-id "ghi-789"
```

Add `--with-session-id` to also record every contributing session ID:

```bash
copilot-session-usage amend-commit \
  --session-id "abc-123" \
  --session-id "def-456" \
  --with-session-id
```

This produces:

```text
Copilot-Session-Usage-Session-ID: abc-123
Copilot-Session-Usage-Session-ID: def-456
Copilot-Session-Usage-Acc: Moonshot AI:Kimi K2.7 Code,in:24.90,out:0.06,cache:21.88,aic:231
Copilot-Session-Usage-AIC: 232
```

This will allow another process, not done by Copilot-Session-Cost, to later rewrite
the commit chain with commit-accurate costs.

## Preview before amending

Use `--dry-run` to see the trailers that would be injected without modifying
the commit:

```bash
copilot-session-usage amend-commit --session-id "$SESSION_ID" --dry-run
```

## Work in a different repository

By default the current working directory is used to locate the Git repository.
Override it with `--repo`:

```bash
copilot-session-usage amend-commit --session-id "$SESSION_ID" --repo /path/to/repo
```

## Full command reference

See [CLI reference](../reference/cli.md) for all options and exit codes.
