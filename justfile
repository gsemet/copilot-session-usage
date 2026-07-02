# justfile — copilot-session-usage
# https://github.com/casey/just

set dotenv-load

# ─── Default ──────────────────────────────────────────────────────────────────

# Show available recipes
[private]
default:
    @just --list

# ─── Development ──────────────────────────────────────────────────────────────

# Install dev dependencies
dev:
    uv sync --all-groups

# Update dependencies
update:
    rm -rf uv.lock
    uv sync --all-groups

# ─── Code quality ─────────────────────────────────────────────────────────────

# Auto-format code
style:
    uv run -- ruff format src tests

# Check formatting without modifying files
style-check:
    uv run -- ruff format --check src tests

# Run all linters
lint:
    uv run -- ruff check src tests
    uv run -- mypy src

# Run type checker only
typecheck:
    uv run -- mypy src

# ─── Testing ──────────────────────────────────────────────────────────────────

# Run unit tests
test:
    uv run -- pytest tests/ -v

# Run tests fast (parallel)
test-fast:
    uv run -- pytest tests/ -v -n auto

# Run tests with coverage (enforces 85%)
tests-coverage:
    uv run -- pytest tests/ --cov=copilot_session_usage --cov-report=term-missing --cov-report=xml --cov-fail-under=85

# ─── Documentation ────────────────────────────────────────────────────────────

# Build Sphinx docs (regenerates CHANGELOG first)
[group("docs")]
docs: changelog
    uv run -- sphinx-build docs/source docs/_build

# Serve docs locally (auto-reload)
[group("docs")]
docs-serve:
    uv run -- sphinx-autobuild docs/source docs/_build --watch src

# Open built docs in browser (macOS)
[group("docs")]
[macos]
docs-open:
    open docs/_build/index.html

# Open built docs in browser (Linux)
[group("docs")]
[linux]
docs-open:
    xdg-open docs/_build/index.html

# ─── Build & release ──────────────────────────────────────────────────────────

# Regenerate CHANGELOG.md from conventional commits
changelog:
    uv run -- cz changelog

# Build wheel + sdist
build:
    uv build

# Refresh bundled pricing data from upstream
refresh-pricing:
    uv run -- python scripts/refresh_pricing.py

# ─── Knowledge (OKF) ──────────────────────────────────────────────────────────

# Validate the OKF knowledge bundle
knowledge-validate:
    uv run -- okf-schema validate --path knowledge

# Lint (format) OKF knowledge frontmatter in-place
knowledge-lint:
    uv run -- okf-schema lint --path knowledge
    uv run -- okf-schema index --path knowledge

# Check OKF knowledge frontmatter without modifying files
knowledge-lint-check:
    uv run -- okf-schema lint --path knowledge --check

# ─── Preflight ────────────────────────────────────────────────────────────────

# Full validation: format → lint → typecheck → test → coverage → knowledge
preflight:
    just style-check
    just lint
    just typecheck
    just tests-coverage
    just knowledge-lint
    just knowledge-validate
    just docs

# ─── Cleanup ──────────────────────────────────────────────────────────────────

# Remove generated artifacts
clean:
    rm -rf docs/_build dist/ .pytest_cache .coverage htmlcov/ src/copilot_session_usage.egg-info

# ─── Run ──────────────────────────────────────────────────────────────────────

run-cli:
	uv run -- copilot-session-usage batch 6 --format table
	uv run -- copilot-session-usage batch 6 --format detailed
