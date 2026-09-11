# Track Spending Over Time

Use `span` with `--since` and `--until` for a compact total/model/session
breakdown of a time window. It is preferred over manually listing sessions
and analyzing them one by one.

For a specific set of related sessions (for example, all sessions whose title
matches a PRD or feature), prefer `analyze --name ... --aggregate`. It reads
only matching sessions and returns a single summary in one command.

```bash
copilot-session-usage analyze --name "feature-x" --aggregate --format table
```

## Daily cost report

```bash
# All sessions today (replace bounds with the local timezone)
copilot-session-usage --agent all span \
  --since 2026-07-02T00:00:00+02:00 \
  --until 2026-07-02T23:59:59+02:00 \
  --format table
```

## Weekly report

```bash
# Rolling seven-day report
copilot-session-usage --agent all span --last 7d --format table
```

Sample output:

```
Span report (since 2026-07-02T00:00:00+02:00, until 2026-07-02T23:59:59+02:00)

Total:
  Sessions:       23
  Input:          8,412,304 tokens
  Output:         142,887 tokens
  Cached:         7,103,220 tokens (avg ratio 84%)
  LLM calls:      312
  Estimated cost: $11.7400

Per model:
  Model                  Sessions       Input    Output   Cached  Calls     Cost
  Claude Sonnet 4.6             18   7,900,000   130,000  6,900,000    280  $10.5000

Per session:
  Session                         Provider  Started              Duration  Calls      Cost
  Implement new feature X        vscode    2026-07-02 09:14:00       42s      8   $0.4200
  Debug failing CI pipeline      cli       2026-07-01 18:03:00      8m      31   $1.8700
...
```

The JSON form follows the stable contract in the packaged
`span-analysis-template.md` reference. A session with missing cost evidence
has `null` token/cost fields and is counted separately; it is not silently
treated as a zero-cost session.

## Save to a file and diff

```bash
copilot-session-usage --agent all span --last 7d \
  --format json --output weekly-costs.json
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
55 23 * * 0 copilot-session-usage --agent all span --last 7d \
  --format json >> ~/copilot-costs.jsonl
```
