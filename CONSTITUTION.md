# copilot-session-usage Constitution

This document defines the durable rules for modifying, testing, packaging, and
releasing `copilot-session-usage`. Detailed task workflows belong in skills; scoped
rules belong in `.github/guidelines/`.

## Mission and scope

The project provides a reliable Python API and CLI for extracting usage, model, token,
and cost KPIs from local GitHub Copilot session logs. It must remain installable as a
Python package, usable from automation, and honest about unavailable evidence.

## 1. Supported platform and project tools

- Support Python `>=3.10` as declared in `pyproject.toml`.
- Use `uv` for dependency synchronization, builds, and project execution.
- Use `justfile` recipes as the authoritative development workflow.
- Keep package code under `src/copilot_session_usage/` and tests under `tests/`.
- Preserve the hatchling plus hatch-vcs build configuration unless a deliberate
  packaging change includes tests and documentation updates.

## 2. Public API and provider boundaries

- Public API belongs in `src/copilot_session_usage/api.py`; internal implementation
  belongs under `src/copilot_session_usage/_internal/`.
- Public API functions retain the optional `agent` parameter used for provider
  routing. The supported provider values are `vscode` and `cli`; the CLI provider
  remains explicitly unsupported until implemented.
- Keep provider discovery separate from parsing, pricing, shaping, and presentation.
- Do not expose internal modules as public API merely to avoid a proper API change.

## 3. Evidence integrity

The package must never manufacture telemetry. When session logs do not provide a
session ID, transcript, model identity, token count, cost, activation signal, or
other evidence, preserve the absence and report an explicit unavailable reason where
the output contract supports one.

Keep distinct metrics distinct: accuracy, duration, tokens, cost, completeness, and
activation must not be silently collapsed into a default composite score.

## 4. Pricing data is controlled input

- Bundled pricing data lives under `src/copilot_session_usage/data/`.
- Load pricing through the package's pricing loader rather than duplicating tables in
  code or tests.
- Refresh pricing only through the maintained pricing-refresh workflow, and review
  lock or provenance changes with the data update.
- Custom model pricing must remain separate from the standard model pricing source.

## 5. Output contracts remain stable and explicit

- Preserve the documented detail ordering: `minimal` < `compact` < `full`.
- Preserve the documented output formats: `json`, `table`, and `detailed`; `detailed`
  is the table format with full detail.
- CLI failures must be actionable and must use the project's Click conventions rather
  than leaking implementation tracebacks by default.
- Changes to public output or CLI options require corresponding tests and updates to
  the README or Sphinx documentation.

## 6. Quality gates are mandatory

`just preflight` must pass before a normal code change is complete. It performs:

1. formatting verification;
2. Ruff linting and mypy type checking;
3. unit tests with an 85% coverage floor;
4. OKF knowledge format checking and validation; and
5. Sphinx documentation generation.

`just preflight` is a non-mutating quality gate. Run `just knowledge-lint` separately
when knowledge documents need formatting or index regeneration, then rerun preflight.

Use the narrower recipe that matches the changed area during iteration, but do not
skip the relevant gate when reporting completion. New behavior requires regression
tests; bug fixes should include a test that would have failed before the fix.

## 7. Code standards

- Keep functions and public classes typed and documented according to the configured
  Ruff, pydocstyle, and mypy rules.
- Prefer small, composable functions with clear boundaries between parsing,
  aggregation, pricing, and rendering.
- Use specific exceptions and preserve useful context in error messages.
- Avoid global mutable state and hidden filesystem or environment side effects.
- Keep formatting at the configured 100-character line length and let Ruff perform
  formatting rather than hand-maintaining competing styles.

## 8. Knowledge-base integrity

`knowledge/` is an OKF bundle, not a general notes folder. Its scoped guideline is
authoritative for document types, frontmatter, Finding immutability, promotion, and
validation.

- Do not rewrite or delete an existing Finding's claim or body.
- Record corrections as new Findings with explicit contradiction or supersession
  links.
- Format knowledge changes with `just knowledge-lint`, then validate them with
  `just knowledge-lint-check` and `just knowledge-validate`.
- Do not add knowledge for facts that are trivial to rediscover from the code or
  documentation.

## 9. Documentation and release artifacts

- Keep `CHANGELOG.md` generated through the Commitizen workflow; do not hand-edit
  generated release sections.
- The canonical generated release-note filename is lowercase `release-notes.md`.
- Release notes describe user-visible changes, include relevant public documentation
  links, and must pass the bundled generation/validation workflow before release.
- Release automation must not publish a package or GitHub Release before its checks
  and release-note validation succeed.
- Never commit credentials, tokens, `.env`, local caches, coverage reports, or other
  machine-generated artifacts unless an explicit project workflow tracks them.

## 10. Git history and contribution workflow

- Use Conventional Commits so Commitizen can generate changelogs and releases.
- Keep commit titles concise and focused on user impact; follow the scoped commit
  guideline for exact formatting and wrapping.
- Maintain a linear history: rebase feature branches instead of merging the target
  branch, and use squash or fast-forward integration.
- Preserve unrelated working-tree changes and keep each change focused and reversible.

When a requested change conflicts with this constitution or an applicable scoped
guideline, surface the conflict before weakening the rule.
