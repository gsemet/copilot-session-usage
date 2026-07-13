# Automated release process

This document is the operational guide for maintainers taking over
`copilot-session-usage`. It describes how to prepare, run, monitor, recover, and
maintain the automated release process.

The normal release process is intentionally started by a human from GitHub
Actions. The workflow performs the mechanical versioning and publication steps,
but the person starting it remains responsible for choosing the bump, checking
the generated notes, and deciding whether to publish a draft release.

## Process at a glance

The normal flow is:

1. Merge the changes intended for release into the repository's default branch.
2. Start the **Release** workflow from the default branch.
3. Choose `auto`, `major`, `minor`, or `patch` for the version increment.
4. Optionally enable `force` to create a patch release when `auto` finds no
   eligible conventional commit.
5. Choose whether the GitHub Release should be published immediately or created
   as a draft.
6. Commitizen calculates the next version without modifying files or creating a
   release commit.
7. The workflow creates a local `vX.Y.Z` tag on the existing default-branch
   commit.
8. GitHub Copilot CLI, invoked through `gh copilot`, runs the repository skill
   `gh-release-notes` against the actual tag-to-tag diff.
9. After clean notes are generated, the workflow pushes the tag and creates the
   GitHub Release.
10. Publishing the GitHub Release triggers CI and the PyPI publication workflow.

The normal workflow is defined in
[`.github/workflows/release.yml`](../../.github/workflows/release.yml).

## Important files and responsibilities

| File | Responsibility |
| --- | --- |
| `.github/workflows/release.yml` | Normal end-to-end release: bump, local tag, note generation, tag push, and GitHub Release creation. |
| `.github/workflows/release-notes.yml` | Manual fallback for generating notes and creating a draft release for an existing tag. It does not bump versions or create tags. |
| `.github/workflows/publish.yml` | Runs when a GitHub Release is published, executes CI, builds the package, and publishes to PyPI using OIDC. |
| `.github/workflows/ci.yml` | Reusable CI workflow required before PyPI publication. |
| `.github/skills/gh-release-notes/SKILL.md` | The custom Copilot skill that interprets the actual diff and writes user-facing release notes. |
| `pyproject.toml` | Defines dynamic SCM versioning and Commitizen configuration. |
| `CHANGELOG.md` | Changelog maintained by Commitizen. |
| `uv.lock` | Locked development and release-tool dependencies. |
| `CONTRIBUTING.md` | Short contributor-facing release instructions. |

There is no hard-coded version in `pyproject.toml`. The package uses Hatch VCS
versioning:

```toml
[tool.hatch.version]
source = "vcs"
```

The Git tag is therefore the source of the released package version. Tags use
this Commitizen format:

```toml
[tool.commitizen]
tag_format = "v$version"
```

## One-time GitHub configuration

A maintainer must verify the following before attempting the first release.

### Actions write permission

The normal release workflow uses the built-in `GITHUB_TOKEN` to push the release
tag and to create the GitHub Release. The repository must allow workflows to
write repository contents:

1. Open the repository's **Settings**.
2. Go to **Actions → General**.
3. Under **Workflow permissions**, select **Read and write permissions**.
4. Save the setting.

Branch protection may allow tag pushes while prohibiting branch updates. The
workflow deliberately does not update the default branch, so the protected
branch's pull-request requirement does not block a release tag. Do not work
around branch protection with an unnecessarily broad personal token without
reviewing the security implications.

The workflow itself declares:

```yaml
permissions:
  contents: write
```

That declaration cannot grant more access than the repository or organization
policy permits.

### Copilot token secret

The notes step requires the repository secret:

```text
COPILOT_GITHUB_TOKEN
```

This is separate from the built-in `GITHUB_TOKEN`:

- `COPILOT_GITHUB_TOKEN` authenticates Copilot requests made by `gh copilot`.
- `GITHUB_TOKEN` authenticates repository pushes and `gh release create`.

Create a fine-grained personal access token from:

<https://github.com/settings/personal-access-tokens/fine-grained/new>

Recommended configuration:

- Resource owner: the maintainer's personal GitHub account.
- Expiration: a short, managed lifetime such as 30 or 90 days.
- Repository access: restrict it to this repository when GitHub requests a
  repository selection.
- Account permission: enable **Copilot requests** with the access level offered
  by GitHub for the account.
- Do not add repository write, workflow, administration, or unrelated account
  permissions. The workflow does not use this token for Git pushes or releases.

The account must have an eligible Copilot entitlement. A GitHub Free account and
Copilot access are separate concerns; a token cannot grant Copilot access that
the account does not have. Copilot requests consume the account's Copilot
allowance. Review the current GitHub Copilot plan and usage limits before using
this workflow frequently.

Add the generated token as a repository secret:

1. Open **Settings → Secrets and variables → Actions**.
2. Click **New repository secret**.
3. Set the name to `COPILOT_GITHUB_TOKEN`.
4. Paste the token as the secret value.
5. Never commit the token, place it in a tracked file, or print it in logs.

The local `.env` placeholder, if present, is only documentation for development
and must not contain a real token.

### PyPI trusted publishing

The publication workflow uses PyPI's OIDC action:

```yaml
- uses: pypa/gh-action-pypi-publish@release/v1
```

The PyPI project must have a trusted publisher configured for this GitHub
repository and the `pypi` environment used by
[`.github/workflows/publish.yml`](../../.github/workflows/publish.yml). Verify
this before the first production release. No PyPI API token is expected in the
repository secrets when trusted publishing is configured correctly.

## Running a normal release

### Before starting

Confirm all of the following:

- The default branch contains the intended merged changes.
- The working tree was clean when the changes were merged.
- CI is green for the commits being released.
- The latest release tag exists and follows `vMAJOR.MINOR.PATCH`.
- The changes use conventional commit messages where automatic bump detection
  is desired.
- `COPILOT_GITHUB_TOKEN` exists and is not expired.
- The Copilot account has enough request allowance for one release-note prompt.
- PyPI trusted publishing and the `pypi` environment are configured.
- There is no existing GitHub Release for the version that will be created.

A useful local preview of the pending conventional-commit decision is:

```text
uv run --no-sync cz bump --get-next --yes
```

This command only calculates the next version. It does not modify files, create a
commit, or create a tag. Run the repository's normal validation before starting a
production release:

```text
just preflight
```

### Start the workflow

1. Open the repository's **Actions** tab.
2. Select **Release**.
3. Click **Run workflow**.
4. Select the default branch.
5. Choose the `increment` input:
   - `auto` — recommended; infer the bump from conventional commits.
   - `major` — explicitly request a major bump.
   - `minor` — explicitly request a minor bump.
   - `patch` — explicitly request a patch bump.
6. Choose the `force` input:
   - `false` — stop if `auto` finds no eligible conventional commit.
   - `true` — in `auto` mode, force a patch bump with
     `--allow-no-commit`. This does not override other errors.
7. Choose the `draft` input:
   - `false` — create a published GitHub Release after notes are generated.
   - `true` — create a draft GitHub Release for review.
8. Start the workflow and monitor the run.

The workflow serializes all releases using the `release` concurrency group. A
second release run will not run concurrently with the first one.

## Version bump behavior

The project uses Commitizen's Conventional Commits adapter. In automatic mode,
the workflow first runs:

```text
uv run --no-sync cz bump --get-next --yes
```

It then performs the actual bump with:

```text
uv run --no-sync cz bump --yes
```

Commitizen normally interprets conventional commits approximately as follows:

| Commit pattern | Usual automatic bump |
| --- | --- |
| `fix: ...`, `perf: ...` | Patch |
| `feat: ...` | Minor |
| `feat!: ...`, another `!` breaking marker, or `BREAKING CHANGE:` | Major |
| `docs: ...`, `chore: ...`, `ci: ...`, `test: ...` | Usually no release bump |

The exact result is controlled by the installed Commitizen version and its
configuration. Use the dry-run command above instead of guessing.

If automatic detection reports no eligible commits and `force` is disabled, the
workflow stops before creating a tag. This is expected for
changes such as a standalone `ci:` or `chore:` commit.

If `force` is enabled, the workflow intentionally falls back to a patch bump:

```text
uv run --no-sync cz bump --increment PATCH --yes --allow-no-commit
```

This is useful for an intentional maintenance or data-only release, but it can
create a release with no conventional-commit change that Commitizen would
normally consider user-visible. The force checkbox does not hide unrelated
Commitizen errors or invalid version output.

For an explicit `major`, `minor`, or `patch` input, the workflow runs the
corresponding Commitizen increment with `--allow-no-commit`. This permits a
maintainer to make an intentional release even when no eligible conventional
commit is present. Use that option carefully; it can create a release containing
no user-visible change.

The release workflow does not update `CHANGELOG.md` or create a release commit.
It creates a lightweight local `vX.Y.Z` tag on the current default-branch commit,
generates and validates release notes, then pushes only that tag. This ordering
prevents a failed note-generation step from leaving a remote tag without a
release. It is required because the default branch is protected and requires
changes to be made through a pull request. Release notes are generated from the
actual previous-tag-to-new-tag diff by `gh-release-notes`.

## What the normal workflow does internally

The steps occur in this order:

1. **Checkout** — fetches the complete repository history from the default branch
   so tags and tag ranges are available.
2. **Install tooling** — installs the pinned `uv.lock` environment, including
   Commitizen.
3. **Clean-tree guard** — refuses to proceed if the checked-out tree is dirty.
4. **Branch setup** — switches to the remote default branch without changing it.
5. **Previous tag resolution** — finds the nearest reachable tag with
   `git describe --tags --abbrev=0`.
6. **Version calculation** — calculates the selected next version without
   modifying files; in forced `auto` mode, allows the patch fallback.
7. **Tag validation** — verifies that the new tag matches the semantic-version
   pattern `vX.Y.Z`, with optional prerelease/build suffixes.
8. **Skill verification** — checks that `gh-release-notes` is discoverable with
   `gh copilot -- skill list` and that `COPILOT_GITHUB_TOKEN` is present.
9. **Note generation** — invokes `gh copilot` with `/gh-release-notes` and the
    exact previous-to-target tag range.
10. **Artifact upload** — stores `release-notes.md` as a workflow artifact named
    `release-notes-vX.Y.Z`.
11. **Push and release creation** — verifies that the remote tag does not already
   exist, pushes only the new tag, refuses to overwrite an existing release, and
   calls `gh release create` with the generated Markdown.

The Copilot invocation disables the built-in GitHub MCP server and exposes only
reading, Git inspection, and the file tools needed to create `release-notes.md`.
It explicitly instructs the skill not to modify, commit, or push any other
repository files. The workflow discards the Copilot response stream and uses the
skill-written file directly, after normalizing harmless titles and preambles and
rejecting traces, code fences, or unusable content. Polluted no-product fallbacks
are replaced with the canonical maintenance wording. The allowed documentation
hosts are the project repository and the published Read the Docs site.

## Release-note generation

The skill source is
[`.github/skills/gh-release-notes/SKILL.md`](../../.github/skills/gh-release-notes/SKILL.md).
It is expected to:

- inspect the actual commit range and diff rather than copying commit subjects;
- translate implementation changes into user impact;
- group changes into features, enhancements, bug fixes, breaking changes,
  examples, and documentation;
- omit empty sections;
- include concrete user examples when the diff supports them;
- use public documentation links with fragments where appropriate; and
- write only release-note Markdown to the requested output file in CI mode.

Do not replace this step with GitHub's generic `--generate-notes` behavior unless
the project intentionally changes its release-note policy. The custom skill exists
to provide richer, project-specific notes.

## Draft versus published releases

| `draft` input | GitHub Release state | Does `publish.yml` run? |
| --- | --- | --- |
| `false` | Published | Yes, after the reusable CI job succeeds |
| `true` | Draft | No; it runs only after a maintainer publishes the draft |

For a draft release:

1. Review the generated notes artifact and the notes shown on the draft Release
   page.
2. Edit the release notes on GitHub if necessary.
3. Publish the draft when the version and notes are approved.
4. Monitor the resulting **Publish to PyPI** workflow.

Publishing is the gate that starts package publication. Creating a tag or draft
release alone does not publish to PyPI.

## Manual notes fallback

Use **Generate release notes (manual)** when a tag already exists but the normal
release workflow stopped before creating the GitHub Release, or when notes need
to be generated for an existing tag.

The fallback workflow is defined in
[`.github/workflows/release-notes.yml`](../../.github/workflows/release-notes.yml).
It requires a tag such as `v0.7.0` and then:

1. Checks out that tag with complete history.
2. Finds the previous merged version tag.
3. Verifies `COPILOT_GITHUB_TOKEN` and skill discovery.
4. Runs the same `gh-release-notes` skill with the exact tag range.
5. Uploads the generated notes artifact.
6. Creates a **draft** GitHub Release.

The fallback does not bump the version, create a commit, or push a tag. It also
refuses to create a release if a GitHub Release already exists for the requested
tag. If a release already exists, edit its notes directly on GitHub or use a
separate reviewed administrative procedure rather than creating a second release.

## Failure and recovery guide

### Failure before the bump

Examples include a dirty tree, no previous tag, no eligible commits in `auto`
mode with `force` disabled, or an invalid Commitizen result.

Expected state:

- No new tag was pushed.
- No GitHub Release was created.

Fix the underlying issue, merge the required changes if necessary, and run the
workflow again.

### Tag push fails

The default branch is not modified by this workflow, so a failed tag push leaves
the branch unchanged. Do not immediately run another release if the target tag
may have been created remotely; first inspect the remote tag and release state.

First inspect GitHub for:

- whether the target tag exists remotely; and
- whether a GitHub Release exists.

If the tag is missing, rerun the release workflow after verifying the calculated
version. If the tag exists, use the manual notes fallback for that tag.

### Copilot note generation fails

The normal workflow now pushes the tag only after clean notes have been generated,
so a note-generation failure should not leave a remote tag.

1. Read the failed job logs and identify whether the problem is the token,
   Copilot allowance, CLI availability, skill discovery, or the prompt itself.
2. Fix the secret or configuration problem.
3. Rerun the **Release** workflow after confirming that no remote target tag was
   created. Use **Generate release notes (manual)** only when a tag already exists
   and needs a new draft release.

If a failed run from an older workflow already created the tag, confirm that no
GitHub Release exists and use the manual fallback for that existing tag, or remove
the abandoned tag before retrying the same version.

### Notes are empty or poor quality

The normal workflow uploads `release-notes.md` as an artifact before creating the
release. Review the artifact to distinguish an empty output from a quality issue.

For poor but non-empty notes, edit the draft release manually. For an empty output
or a failed Copilot invocation, use the manual fallback after correcting the
secret or CLI/skill problem.

### GitHub Release creation fails

Check:

- `GITHUB_TOKEN` has `contents: write` at both workflow and repository-policy
  levels;
- the tag was pushed successfully;
- no Release already exists for the target tag;
- the repository name and tag are correct; and
- branch or repository policies did not reject the operation.

If the tag exists and no Release exists, use the manual notes fallback rather
than bumping again.

### PyPI publication fails

A published GitHub Release should trigger **Publish to PyPI**. If that workflow
fails:

1. Open the failed workflow run and identify whether CI, package building, the
   `pypi` environment, or OIDC trusted publishing failed.
2. Fix the configuration or code problem through the normal reviewed process.
3. Re-run the failed workflow job when the failure is transient or configuration
   has been corrected.

Do not create a second GitHub Release for the same version. Do not reuse a version
that has already been successfully published to PyPI; publish a corrective patch
version instead.

## Security and cost controls

- Treat `COPILOT_GITHUB_TOKEN` as a password.
- Keep the token in GitHub Actions secrets only.
- Give the token only the Copilot account permission required for requests.
- Prefer an expiring token and rotate it before expiration.
- The workflow uses `--no-ask-user` because it is headless; review the allowed
  tool flags before changing them.
- Keep `--disable-builtin-mcps` unless the release process explicitly needs GitHub
  MCP access.
- Do not casually replace scoped tool permissions with `--allow-all-tools`.
- Copilot requests consume the account's allowance and may be subject to plan
  limits or billing rules.
- Keep `GH_TOKEN` and `COPILOT_GITHUB_TOKEN` conceptually separate; the former is
  the Actions repository token and the latter is the Copilot request token.
- Generated notes are uploaded as an artifact. Check retention and repository
  access policies if release notes ever contain sensitive information.

## Maintainer checklist

### Before the first release after taking ownership

- [ ] Confirm the default branch and latest `vX.Y.Z` tag.
- [ ] Confirm Actions workflow permissions allow `contents: write`.
- [ ] Confirm branch protection permits the release workflow's push strategy.
- [ ] Create and store `COPILOT_GITHUB_TOKEN` with the Copilot requests permission.
- [ ] Confirm the account has Copilot access and available request allowance.
- [ ] Confirm the `gh-release-notes` skill is present and discoverable.
- [ ] Configure and test PyPI trusted publishing for the `pypi` environment.
- [ ] Run the normal test/preflight checks.
- [ ] Test a draft release if the repository has never used the workflow before.

### For every release

- [ ] Intended changes are merged into the default branch.
- [ ] CI is green.
- [ ] Conventional commit messages support the desired automatic bump, or an
      explicit bump has been selected intentionally.
- [ ] If `force` is enabled, the resulting patch release is intentional even if
   no eligible conventional commit exists.
- [ ] No Release already exists for the version that will be produced.
- [ ] `COPILOT_GITHUB_TOKEN` is present and not expired.
- [ ] Generated notes and the release state have been reviewed.
- [ ] The PyPI workflow succeeds after publication.

### After workflow or skill changes

- [ ] Validate both workflow YAML files.
- [ ] ShellCheck all embedded Bash blocks.
- [ ] Run `just test` or `just preflight` as appropriate.
- [ ] Verify `gh copilot -- skill list` still lists `gh-release-notes`.
- [ ] Re-check the Copilot CLI flags against the current CLI version.
- [ ] Confirm public documentation URLs in the skill still point to live pages.

## Official references

- [Managing personal access tokens](https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/managing-your-personal-access-tokens)
- [About GitHub Copilot CLI](https://docs.github.com/en/copilot/concepts/agents/copilot-cli/about-copilot-cli)
- [Using GitHub Copilot CLI](https://docs.github.com/en/copilot/how-tos/copilot-cli/use-copilot-cli/overview)
- [GitHub Actions workflow permissions](https://docs.github.com/en/actions/security-for-github-actions/security-guides/automatic-token-authentication)
- [PyPI trusted publishers](https://docs.pypi.org/trusted-publishers/)
- [Commitizen documentation](https://commitizen-tools.github.io/commitizen/)
