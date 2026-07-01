# Update Log

## 2026-07-01

### refresh-pricing hardening
- **`just refresh-pricing` failure diagnosed as environmental, not a bug**:
  `curl` returned `502 Bad Gateway` from the corporate proxy (`rnproxy`/
  `zscaler` at `localhost:3128`) for *every* external HTTPS domain tested
  (`raw.githubusercontent.com`, `github.com`, `pypi.org`) — a transient
  proxy/network outage, unrelated to this skill.
- **Found and fixed real data loss risk while investigating**: the recipe's
  `curl | uv run convert_pricing.py > references/pricing.json` truncates
  `pricing.json` via shell redirection *before* the pipeline even runs, so a
  failed fetch silently wiped the file to 0 bytes (confirmed — it happened
  during this investigation; restored via `git checkout`). Fixed the recipe
  to write to a `mktemp` temp file and only `mv` it into place after success,
  with `set -euo pipefail` so a curl failure never reaches that `mv`.
- **Improved error message**: `convert_pricing.py` now checks for empty/
  whitespace-only stdin up front and raises "No YAML input received... check
  connectivity... and re-run `just refresh-pricing`" instead of the
  confusing `ValueError: ... got NoneType` that came from feeding empty
  input to `yaml.safe_load`. Added regression tests for both the empty-input
  error and (via traced manual repro) the temp-file/mv protection.

### final pass same day
- **Root-caused and fixed the real alignment bug**: `Per-Model Breakdown`/
  `Subagents` numeric columns (Input/Cached/Output) used a *fixed* width
  (9 or 10 chars). Token counts of 45,382,133 (10 chars with separators)
  silently overflowed a 9-char field, adding 1-2 extra characters to that
  row only and desyncing every column after it — visually "columns not
  aligned" for large sessions while looking fine for small ones. Replaced
  both tables with a shared `_render_columns(headers, rows, left_cols)`
  helper: width is computed per column from the actual formatted cell
  strings (never a guess), so it can't overflow regardless of magnitude.
  Also switched the inter-column separator from 1 to 2 spaces per the
  explicit request for more margin. Added a regression test that asserts
  every line within a table block has identical length even with 10-digit
  token counts.

### yet later same day
- **Bug fix**: the "Per-Model Breakdown" and "Subagents" tables inside
  `render_table_single` (used by `--format table`/`detailed` at `--detail
  full`) still used hardcoded column widths (`Model` capped at 24, `Name` at
  20, `Model` at 14 via the now-removed `_abbrev_model` helper which hard-cut
  to 10 chars). Long model names like `claude-sonnet-5`/`Kimi-K2.6-azure`
  were clipped. Switched both tables to the same `_col_width` dynamic-sizing
  approach used for the row tables — columns now fit the actual content,
  never truncating model or subagent names. Removed `_abbrev_model` (dead
  code once nothing truncates model names for display).
- **Fixed `just all`**: it was failing at the `lint` step on 8 pre-existing
  ruff findings unrelated to this skill's recent changes (`EM102`/`DTZ011`/
  `T201` in `convert_pricing.py`, `PT006` x2 + `DTZ011` in
  `test_convert_pricing.py`, `PT006` x2 in `test_cost_core.py`). Fixed all of
  them: assigned exception messages to variables before raising, replaced
  `datetime.date.today()` with `datetime.now(tz=UTC).date()` (both in the
  script and its test, so they compare in the same timezone), converted
  `pytest.mark.parametrize` argnames from comma-strings to tuples, and added
  a targeted `# noqa: T201` on the one `print()` that is the CLI's actual
  purpose (`convert_pricing.py` writes JSON to stdout by design). `just all`
  now passes clean.

### later same day
- **Bug fix / consistency**: `--format table` row tables were truncating
  session IDs (8 chars) and model names (10 chars) to fit an assumed 80-col
  terminal, and the per-session model/subagent breakdown ("detailed" view)
  was completely lost for `batch`/list rendering — it only worked for a
  single session via `--detail full`. Fixed: `render_table_list` now detects
  full-detail items and renders each session in full (like the old
  `--format details`) with an aggregate footer; row-table columns are sized
  dynamically from actual content instead of hardcoded, so IDs and model
  names are never clipped.
- **Bug fix / consistency**: `--format detailed` didn't exist as a valid
  `--format` value (only `json`/`table`), so users following muscle memory
  from the pre-refactor CLI (which had `--format details`) got a hard error.
  Added `detailed` as a third `--format` choice, wired identically into all
  6 subcommands via two small helpers (`core.resolve_detail`,
  `core.normalize_format`): `--format detailed` now always forces the full
  per-model/per-subagent breakdown, human-readable, regardless of
  `--detail`, on every command (analyze/latest/find/id/batch; `list` treats
  it the same as `table` since it has no cost data to break down further).

### main refactor
- **Refactor**: Split the monolithic `vscode_session_cost.py` (1219 lines, 15
  CLI flags) into `scripts/_cost_core.py` (provider-agnostic pricing, JSONL
  parsing, output shaping, rendering, shared Click options) and a thin
  `scripts/vscode_session_cost.py` (VS Code-specific discovery + 6 subcommands:
  `analyze`, `latest`, `find`, `id`, `list`, `batch`). Goal: make adding a new
  provider (Copilot CLI, opencode, ...) a ~150-line discovery module instead of
  copy-pasting ~800 lines.
- **Breaking CLI change**: replaced 6 mutually-exclusive action flags
  (`--log-dir/--session-id/--title/--latest/--list/--analyze-latest`) and 3
  overlapping verbosity flags (`--compact/--totals-only/--totals-first`) with
  subcommands + a single `--detail {minimal,compact,full}` option (default
  `compact`). Fixed a real bug where `--totals-first` was silently ignored
  outside batch mode. `batch` (formerly `--analyze-latest`) now always returns
  `{summary, sessions}` — no separate flag needed.
- **Bug fix**: the `models` list was alphabetically sorted, so an uppercase
  model name (`Kimi-...`) always appeared "dominant" in table output even when
  a lowercase model (`claude-...`) did nearly all the work — same class of bug
  as the known per-file pricing issue, now also guarded in `models` ordering
  (sorted by cost instead).
- **New**: `fallback_pricing_models` field flags any model priced via the
  generic `default` rate, so callers know a cost figure may be inaccurate.
- **Docs**: trimmed `guides/automation-scripts.md` and
  `concepts/session-discovery-algorithm.md` from duplicated (and drifting)
  code samples to pointers at the real implementation; removed the
  superseded `ideas/vs-code-usage-tools.md` idea spec (it shipped).

## 2026-06-30
- **Creation**: Initial knowledge base established from live debugging session.
- **Discovery**: Subagent `.jsonl` files DO contain `llm_request` events with
  full token counts — previous assumption that they did not was incorrect.
- **Discovery**: VS Code Copilot debug panel aggregates tokens from ALL
  `.jsonl` files in the session directory, not just `main.jsonl`.
