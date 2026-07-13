# AGENTS.md — copilot-session-usage

**copilot-session-usage** is a PyPI-installable Python package that extracts VS Code Copilot session cost KPIs from local debug logs.

## Quick Navigation

- **[README](README.md)** — User-facing overview and quickstart
- **[CONTRIBUTING](CONTRIBUTING.md)** — Developer setup and conventions
- **[.github/guidelines/knowledge-base.guidelines.md](.github/guidelines/knowledge-base.guidelines.md)** - How to use, update and maintain the knowledge base
- **[.github/guidelines/git-commit-message.guideline.md](.github/guidelines/git-commit-message.guideline.md)** — Commit message conventions

## Technology Stack

- **Language**: Python 3.10+
- **CLI Framework**: Click
- **YAML Processing**: ruamel.yaml
- **Package Manager**: uv
- **Build Tool**: hatchling + hatch-vcs
- **Task Runner**: just

## Project Structure

```
copilot-session-usage/
├── src/copilot_session_usage/      # Main package
│   ├── __init__.py                 # Version re-export
│   ├── api.py                      # Public Python API
│   ├── cli.py                      # Click CLI entry point
│   ├── _internal/                  # Internal implementation
│   │   ├── core.py                 # Cost analysis, JSONL parsing, shaping
│   │   ├── vscode.py               # VS Code workspace discovery
│   │   └── copilot_cli.py          # Stub for future CLI support
│   └── data/                       # Bundled pricing data
│       ├── models-and-pricing.yml
│       ├── models-and-pricing.lock
│       └── custom-models-pricing.yml
├── tests/                          # pytest test suite
├── docs/                           # Sphinx documentation
├── knowledge/                      # OKF knowledge base
├── skills/                         # Agent skill definition
├── justfile                        # Task automation
├── pyproject.toml                  # Project configuration
└── uv.toml                         # uv configuration
```

## Main Commands

```bash
just dev              # Install dev dependencies
just test             # Run unit tests
just tests-coverage   # Run tests with 85% coverage threshold
just preflight        # Full validation (format → lint → typecheck → test → coverage)
just docs             # Build Sphinx docs
just docs-serve       # Serve docs with auto-reload
just build            # Build wheel + sdist
```

## Knowledge Base operations

When user wants you to debug how VS Code, Copilot CLI, works, how their cost,
billing, pricing works, when you discover important information that you might
have to remember, you have to ask yourself this questions: Is this information
worth remembering for me of for other coding agents, potentially run on
a different developer's machine ?

If you think some discoveries are worth remembering, you have to update the
knowledge base.
You have to follow the guidelines in `.github/guidelines/knowledge-base.guidelines.md`
to understand the rules of the knowledge base in `knowledge/`.

## Key Conventions

- **Public API**: `api.py` — all functions accept optional `agent` parameter for future routing
- **Internal modules**: `_internal/` — not part of public API
- **Pricing data**: Bundled in `src/copilot_session_usage/data/`; loaded via `load_pricing()`
- **Provider routing**: `--agent {vscode,cli}` — `cli` raises `NotImplementedError`
- **Detail levels**: `minimal` < `compact` < `full`
- **Output formats**: `json`, `table`, `detailed` (alias for table + full detail)

## Git History and Pull Requests

This repository must maintain a linear history. **Never create a merge commit.**

- Rebase a feature branch onto the current target branch before opening or updating a pull request: `git fetch origin main && git rebase origin/main`.
- When the target branch advances, rebase again; do not merge `main` into the feature branch.
- Resolve conflicts during the rebase, run the relevant checks, and update the remote branch with `git push --force-with-lease` when required.
- Merge pull requests only with a squash merge or a rebase/fast-forward merge. Never use a merge commit or `--no-ff`.
- Do not force-push protected branches; `--force-with-lease` is permitted only for the contributor's feature branch.

## Before You Commit

```bash
just preflight
```

All checks must pass. Coverage threshold is 85%.
