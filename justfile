# justfile — copilot-session-usage
# https://github.com/casey/just

set dotenv-load

# ─── Default ──────────────────────────────────────────────────────────────────

# Show available recipes
[private]
[group("base")]
default:
    @just --list

# ─── Development ──────────────────────────────────────────────────────────────

# Install dev dependencies
[group("dev")]
dev:
    uv sync --all-groups

# Update dependencies
[group("dev")]
update:
    rm -rf uv.lock
    uv sync --all-groups

# ─── Code quality ─────────────────────────────────────────────────────────────

# Auto-format code
[group("style")]
style:
    uv run -- ruff format src tests .github/skills/gh-release-notes/scripts

# Check formatting without modifying files
[group("style")]
style-check:
    uv run -- ruff format --check src tests .github/skills/gh-release-notes/scripts

# Run all linters
[group("check")]
lint:
    uv run -- ruff check src tests .github/skills/gh-release-notes/scripts
    uv run -- mypy src .github/skills/gh-release-notes/scripts

# Run type checker only
[group("check")]
typecheck:
    uv run -- mypy src .github/skills/gh-release-notes/scripts

# ─── Testing ──────────────────────────────────────────────────────────────────

# Run unit tests
[group("test")]
test:
    uv run -- pytest tests/ -v

# Run tests fast (parallel)
[group("test")]
test-fast:
    uv run -- pytest tests/ -v -n auto

# Run tests with coverage (enforces 85%)
[group("test")]
tests-coverage:
    uv run -- pytest tests/ --cov=copilot_session_usage --cov-report=term-missing --cov-report=xml --cov-fail-under=85

# ─── Documentation ────────────────────────────────────────────────────────────

# Build Sphinx docs (regenerates CHANGELOG first)
[group("docs")]
docs: changelog
    uv run -- sphinx-build docs/source docs/_build

# Check Sphinx docs without regenerating tracked release artifacts
[group("check")]
docs-check:
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
[group("release")]
changelog:
    uv run -- cz changelog

# Build wheel + sdist
[group("release")]
build:
    uv build

# Refresh bundled pricing data from upstream
[group("release")]
refresh-pricing:
    uv run -- python scripts/refresh_pricing.py

# Generate and validate release notes for the Git range FROM_REF..TO_REF.
# FROM_REF is excluded; TO_REF is included. Both arguments may be tags, branches, or commits.
[group("release")]
release-notes FROM_REF TO_REF OUTPUT="release-notes.md" MODEL="":
    uv run -- python .github/skills/gh-release-notes/scripts/generate_release_notes.py --from-ref "{{FROM_REF}}" --to-ref "{{TO_REF}}" --output "{{OUTPUT}}" --model "{{MODEL}}"

# ─── Knowledge (OKF) ──────────────────────────────────────────────────────────

# Validate the OKF knowledge bundle
[group("check")]
knowledge-validate:
    uv run -- okf-schema validate --path knowledge

# Lint (format) OKF knowledge frontmatter in-place
[group("check")]
knowledge-lint:
    uv run -- okfkb update knowledge

# Check OKF knowledge frontmatter without modifying files
[group("check")]
knowledge-lint-check:
    uv run -- okf-schema lint --path knowledge --check

# ─── Preflight ────────────────────────────────────────────────────────────────

# Full validation: format → lint/typecheck → test → coverage → knowledge
[group("check")]
preflight:
    just style-check
    just lint
    just tests-coverage
    just knowledge-lint-check
    just knowledge-validate
    just docs-check

# Run the complete quality gate from CI.
[group("ci")]
ci-check:
    just preflight

# ─── Cleanup ──────────────────────────────────────────────────────────────────

# Remove generated artifacts
[group("base")]
clean:
    rm -rf docs/_build dist/ .pytest_cache .coverage htmlcov/ src/copilot_session_usage.egg-info

# ─── Run ──────────────────────────────────────────────────────────────────────

# Run representative CLI commands.
[group("demo")]
run-cli:
	uv run -- copilot-session-usage batch 6 --format table
	uv run -- copilot-session-usage batch 6 --format detailed

# Amend a commit with usage from a recorded session.
[group("demo")]
run-amend-commit SESSION_ID:
    uv run copilot-session-usage amend-commit --session-id {{SESSION_ID}}
