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
[no-cd]
dev:
    uv sync --all-groups

# ─── Code quality ─────────────────────────────────────────────────────────────

# Auto-format code
[no-cd]
style:
    uv run -- ruff format src tests

# Check formatting without modifying files
[no-cd]
style-check:
    uv run -- ruff format --check src tests

# Run all linters
[no-cd]
lint:
    uv run -- ruff check src tests
    uv run -- mypy src

# Run type checker only
[no-cd]
typecheck:
    uv run -- mypy src

# ─── Testing ──────────────────────────────────────────────────────────────────

# Run unit tests
[no-cd]
test:
    uv run -- pytest tests/ -v

# Run tests fast (parallel)
[no-cd]
test-fast:
    uv run -- pytest tests/ -v -n auto

# Run tests with coverage (enforces 85%)
[no-cd]
tests-coverage:
    uv run -- pytest tests/ --cov=copilot_session_usage --cov-report=term-missing --cov-fail-under=85

# ─── Documentation ────────────────────────────────────────────────────────────

# Build Sphinx docs
[no-cd]
docs:
    uv run -- sphinx-build docs/source docs/_build

# Serve docs locally (auto-reload)
[no-cd]
docs-serve:
    uv run -- sphinx-autobuild docs/source docs/_build --watch src

# ─── Build & release ──────────────────────────────────────────────────────────

# Build wheel + sdist
[no-cd]
build:
    uv build

# Refresh bundled pricing data from upstream
[no-cd]
refresh-pricing:
    uv run -- python -c "from copilot_session_usage._internal.core import refresh_pricing; refresh_pricing()"

# ─── Knowledge (OKF) ──────────────────────────────────────────────────────────

# Validate the OKF knowledge bundle
[no-cd]
knowledge-validate:
    uv run -- okf-schema validate --path knowledge

# Lint (format) OKF knowledge frontmatter in-place
[no-cd]
knowledge-lint:
    uv run -- okf-schema lint --path knowledge
    uv run -- okf-schema index --path knowledge

# Check OKF knowledge frontmatter without modifying files
[no-cd]
knowledge-lint-check:
    uv run -- okf-schema lint --path knowledge --check

# ─── Preflight ────────────────────────────────────────────────────────────────

# Full validation: format → lint → typecheck → test → coverage → knowledge
[no-cd]
preflight:
    just style-check
    just lint
    just typecheck
    just tests-coverage
    just knowledge-lint
    just docs

# ─── Cleanup ──────────────────────────────────────────────────────────────────

# Remove generated artifacts
[no-cd]
clean:
    rm -rf docs/_build dist/ .pytest_cache .coverage htmlcov/ src/copilot_session_usage.egg-info

# ─── Run ──────────────────────────────────────────────────────────────────────

run-cli:
	uv run -- copilot-session-usage batch 6 --format table
	uv run -- copilot-session-usage batch 6 --format detailed
