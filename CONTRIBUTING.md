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

1. Tag a release: `git tag v1.2.3`
2. Push tags: `git push --tags`
3. CI builds and publishes to PyPI via OIDC
