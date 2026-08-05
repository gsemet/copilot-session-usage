# AGENTS.md — copilot-session-usage

`copilot-session-usage` is a PyPI-installable Python package that extracts usage and
cost analytics from local VS Code Copilot and Copilot CLI session logs.

Read [`CONSTITUTION.md`](CONSTITUTION.md) before changing code, tests, packaging,
release automation, or knowledge. It contains the durable project rules. This file
is the navigation guide; it should not duplicate those rules.

## Authority order

When guidance conflicts, use this order:

1. [`CONSTITUTION.md`](CONSTITUTION.md)
2. Scoped rules in `.github/guidelines/`
3. This `AGENTS.md`
4. Task-specific skills and prompts

## Quick navigation

- [`README.md`](README.md) — user-facing overview and quickstart
- [`CONTRIBUTING.md`](CONTRIBUTING.md) — contributor workflow and release process
- [`pyproject.toml`](pyproject.toml) — package metadata, dependencies, and tool config
- [`justfile`](justfile) — authoritative development and quality commands
- [`docs/source/`](docs/source/) — Sphinx documentation
- [`knowledge/`](knowledge/) — OKF knowledge bundle
- [Knowledge base guideline](.github/guidelines/knowledge-base.guidelines.md) — rules
  for maintaining `knowledge/`
- [Commit guideline](.github/guidelines/git-commit-message.guideline.md) — commit
  format and user-impact wording

## Repository map

```text
src/copilot_session_usage/
├── api.py                    Public Python API
├── cli.py                    Click CLI entry point
├── _internal/core.py         Session parsing, cost analysis, and shaping
├── _internal/vscode.py       VS Code workspace discovery
├── _internal/copilot_cli.py  Future Copilot CLI provider stub
└── data/                     Bundled model and pricing data
tests/                        Pytest suite
scripts/                      Maintenance scripts, including pricing refresh
skills/                       Copilot skills maintained with the package
```

## Main commands

Run `just dev` when dependencies need to be installed or synchronized. From the
repository root:

```text
just style             Format Python and bundled skill scripts
just style-check       Check formatting without modifying files
just lint              Run Ruff and mypy
just typecheck         Run mypy only
just test              Run the unit tests
just test-fast         Run tests in parallel
just tests-coverage    Run tests with the 85% coverage gate
just docs              Build the Sphinx documentation
just build             Build the wheel and source distribution
just ci-check          Run the full CI-equivalent quality gate
just preflight         Run the complete local quality gate
```

For focused release-note generation, use the `release-notes` recipe. Its range is
`FROM_REF..TO_REF`: the starting ref is excluded and the ending ref is included. The
canonical output filename is `release-notes.md`.

## Change workflow

- Put package code in `src/copilot_session_usage/` and matching tests in `tests/`.
- Update `docs/source/` when public behavior or APIs change.
- Load the knowledge-base guideline before modifying `knowledge/`; use the
  knowledge-specific validation recipes rather than editing generated indexes by
  hand.
- Load the relevant skill under `.github/skills/` for specialized workflows.
- Run targeted checks while iterating and `just preflight` before completion.
- Preserve unrelated working-tree changes and inspect `git diff` before committing.

If the development environment is incomplete, run `just dev` and retry. Never commit
`.env`, tokens, coverage artifacts, caches, or other local-only files.
