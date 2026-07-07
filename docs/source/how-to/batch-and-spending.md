# Track Spending Over Time

Use `batch` with `--since` to aggregate costs for a time window.

For a specific set of related sessions (for example, all sessions whose title
matches a PRD or feature), prefer `analyze --name ... --aggregate`. It reads
only matching sessions and returns a single summary in one command.

```bash
copilot-session-usage analyze --name "feature-x" --aggregate --format table
```

## Daily cost report

```bash
# All sessions today
copilot-session-usage batch 50 --since $(date +%Y-%m-%d)
```

## Weekly report

```bash
copilot-session-usage batch 100 --since 2026-06-25
```

Sample output:

```
Sessions analyzed: 23
Total input:       8,412,304 tokens
Total output:      142,887 tokens
Total cached:      7,103,220 (84%)
Total LLM calls:   312
Est. total cost:   $11.74

Session                            Started              Cost
Implement new feature X            2026-07-02 09:14Z   $0.42
Debug failing CI pipeline          2026-07-01 18:03Z   $1.87
...
```

## Save to a file and diff

```bash
copilot-session-usage batch 100 --since 2026-07-01 \
  --format json --output july-costs.json
```

Then open `july-costs.json` in any tool that understands JSON arrays.

## Filter by workspace

If you work in multiple repositories, limit the report to one workspace:

```bash
copilot-session-usage batch 50 \
  --since 2026-07-01 \
  --workspace-filter myproject
```

`--workspace-filter` matches against the workspace folder name (substring,
case-insensitive).

## Skill spending report

Use the `skills` command to see which skills drove the most cost over a time
window:

```bash
# Skills used in the last 7 days
copilot-session-usage skills --last 7d --format table

# Skills used since a specific date
copilot-session-usage skills --since 2026-07-01 --format table
```

Output:

```
Skills across 23 sessions:
  Skill                              Sessions        Input     Output       Cached   Calls       Cost
  ---------------------------------------------------------------------------------------------------
  /compendium-generic get-session-costs       3    1137864      15729      1015825      24  $0.3636
```

## Automate with cron (macOS/Linux)

```bash
# ~/.zshrc or crontab -e
# Run every Sunday at 23:55, append weekly cost to a log
55 23 * * 0 copilot-session-usage batch 200 \
  --since $(date -v-7d +%Y-%m-%d) \
  --format json >> ~/copilot-costs.jsonl
```
