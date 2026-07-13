# Contributing to copilot-session-usage

## Setup

```bash
# Clone the repository
git clone https://github.com/gsemet/copilot-session-usage
cd copilot-session-usage

# Install dependencies (uses uv)
just dev
```

## Development workflow

```bash
# Run tests
just test

# Run full validation
just preflight

# Build documentation
just docs

# Serve docs with auto-reload
just docs-serve
```

## Code style

- **Formatter**: ruff (line length 100)
- **Linter**: ruff, ty, mypy
- **Type checker**: mypy (strict)
- **Test runner**: pytest with pytest-cov

## Adding features

1. Add or update code in `src/copilot_session_usage/`
2. Add tests in `tests/`
3. Update documentation in `docs/source/`
4. Run `just preflight` to validate
5. Submit a pull request

## Release process

1. Open the **Release** workflow under the repository's Actions tab.
2. Run it from the default branch, choosing `auto` to derive the major, minor, or
	patch bump from conventional commits, or choose an explicit bump. Enable
	`force` to create a patch release when `auto` finds no eligible commit.
3. The workflow uses Commitizen to calculate the next version, prepares a local
	`vX.Y.Z` tag on the existing default-branch commit, generates notes with the
	`gh-release-notes` skill through `gh copilot`, and pushes the tag only after
	note generation succeeds. It does not create a version/changelog commit.
4. The generated notes are uploaded as an artifact and used to create the GitHub
	Release. Enable the `draft` option if the release needs review before publishing.
5. Publishing the GitHub Release triggers CI and publishes the package to PyPI via
	OIDC.

The workflow requires a repository secret named `COPILOT_GITHUB_TOKEN`. It must be
a fine-grained token with the **Copilot Requests** permission. The normal Actions
`GITHUB_TOKEN` is used for repository writes and GitHub Release creation.

The **Generate release notes (manual)** workflow remains available when notes need
to be regenerated for an existing tag without creating a new release.
