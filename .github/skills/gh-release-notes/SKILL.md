---
name: gh-release-notes
description: Generate end-user-friendly GitHub release notes from the actual diff between releases, including user impact, examples, breaking changes, and public documentation links.
argument-hint: "from_tag=... to_tag=... repo_path=..."
user-invocable: true
---

# Release Notes Generator (Git Diff Based)

Generate **end-user-friendly, user-impact-only** release notes by analyzing the actual changes between releases.
No scripts required — use git commands to understand what changed and why it matters to someone using the product.

The output is meant to be **copy-pasted into a GitHub Release**. It must contain release-note sections only: never add a document title, preamble, file summary, commit summary, or closing separator.

---

## Quick Start

Provide your repository and range:

```
Generate release notes from v1.0.0 to v1.1.0 in /path/to/repo
```

Or reference the last release:

```
What changed since the last release tag?
```

---

## What It Does

1. **Reads actual diffs** — examines code changes, not just commit messages
2. **Applies a user-impact gate** — includes a change only when a user-visible behavior, supported interface, user workflow, output, compatibility guarantee, or public documentation experience changed
4. **Interprets for end-users** — no technical jargon, functions, variable names, file paths, or implementation summaries
5. **Categorizes intelligently** — Features, Enhancements, Bug Fixes, Breaking Changes, or a no-product-impact classification
6. **Adds concrete examples** — shows what users see or can do after a qualifying change
7. **Links to public docs** — points to published documentation, not repo paths
8. **Consolidates related changes** — groups related diffs and eliminates back-and-forth noise
9. **Outputs clean markdown** — ready to paste into a GitHub Release note

When invoked through Copilot CLI JSON output, the copyable release body is the
`data.content` value of the final `assistant.message` event. Never copy
`assistant.reasoning_delta`, tool calls, system notifications, or any other
session events into the release body.

---

## Input

Accept either:

- **Natural language**: "Show release notes from v1.2.0 to v1.3.0"
- **Range spec**: `from_tag=v1.2.0 to_tag=v1.3.0 repo_path=/path/to/repo`
- **Last release**: `since_tag=v1.2.0` (everything from tag to HEAD)

Required:
- Repository path (optional: defaults to current directory)
- Range: `from_tag` + `to_tag`, OR `since_tag`, OR `last_n_commits`

---

## Analysis Process

### Step 0: Apply the release-worthiness gate

Before writing any bullet, ask: **What can a user do, observe, configure, rely on, or learn differently after this change?** Require evidence from the diff, public CLI/API help, supported configuration, user-facing output, migration behavior, or published documentation.

Include a change only if it has at least one of these effects:

- Adds, removes, fixes, or changes a user-facing feature, command, API, configuration option, output, error message, compatibility guarantee, or supported platform.
- Changes runtime behavior in a way users can observe, such as performance, reliability, pricing data, security behavior, or data handling.
- Changes public documentation that users actually consume to operate the product, including a new guide, changed instructions, or migration guidance.

Do **not** infer user impact from a commit type, changed filename, test coverage, or the fact that a change is large. If the evidence does not show a user consequence, exclude it.

### Step 1: Collect Commits
```bash
git log v1.0.0..v1.1.0 --oneline --no-merges
```
Gather all commits in the specified range with their messages.

### Step 2: Examine relevant diffs
```bash
git diff v1.0.0..v1.1.0 -- . ':(exclude).github' ':(exclude)skills' ':(exclude)guidelines'
```
Read actual code changes line-by-line to understand behavior. Inspect excluded paths only when needed to verify whether they caused a direct user-visible consequence; never report the paths themselves.

Treat these as non-release content by default:

- CI/CD workflows, automation, release jobs, repository settings, and bot configuration
- Internal skills, agent prompts, contributor guidelines, engineering process, and maintainer runbooks
- Tests, fixtures, formatting, linting, refactors, type annotations, and code organization
- Dependency, lockfile, build, packaging, or development-environment changes without a user-visible runtime consequence
- File counts, changed-file lists, commit counts, authors, implementation details, and internal URLs

These exclusions can be overridden only when the diff proves a direct user impact, such as a packaging change that changes the installable artifact or a security fix that changes behavior for users.

### Step 3: Interpret qualifying changes

Translate technical changes into user impact:

| Code Change | User Impact |
|-------------|------------|
| `+ const darkMode = true` in settings | "Dark mode toggle now available in settings" |
| Deleted login retry logic | "Removed automatic retry on login timeout" |
| `+ validateEmail()` function | "Email validation improved during signup" |
| Updated database schema version | "Database schema upgraded (run migration)" |
| Added 10+ calls to cache layer | "Improved performance on large operations" |
| Removed old CSV export code | "CSV export removed; use Excel or PDF instead" |

**Key: Focus on the user's experience, not the code implementation.**

Never turn a repository change into a release note merely by paraphrasing it. For example, “added CI workflow,” “updated contributor guidelines,” “improved project metadata,” and “7 files changed” are not release notes.

### Step 4: Identify Breaking Changes

Breaking changes come from:
- **Commit messages** containing: "BREAKING", "Breaking", "!:"
- **Diffs showing**: removed public APIs, changed file formats, data migrations
- **Config changes**: renamed settings, changed defaults

### Step 5: Consolidate
- If a feature was added then removed → don't mention it
- If something changed multiple times → only note the final state
- If multiple commits fix the same issue → merge into one bullet

### Step 6: Categorize & Format

Organize qualifying changes into buckets. **Only include sections that have content.** Omit empty sections entirely. Do not add a title heading.

If there are no qualifying product changes, use exactly one concise fallback block. Keep its structure consistent across releases while adapting the wording to the evidence:

- `**Maintenance**` for a maintenance release containing internal upkeep, CI, release automation, dependency/build work, refactors, or other operational changes
- `**Documentation**` for a documentation-update release whose meaningful outcome is public user documentation, even when no runtime behavior changed
- `**Internal**` for an internal release containing changes intentionally limited to maintainers, contributors, or internal tooling

Choose the most accurate fallback; do not list the underlying files or tasks. Follow the label with one short paragraph that says what was maintained or documented and whether core product functionality changed. Do not manufacture examples or links for either.

```markdown
## New Features
- Added dark mode toggle in settings
- New PDF export option

## Enhancements
- Improved search performance (now supports partial matches)
- Faster file opening for large documents

## Bug Fixes
- Fixed login failures on slow connections
- Resolved crash when uploading 10MB+ files

## Breaking Changes
- Database schema updated — run migration before upgrading
- CSV export removed; use Excel or PDF instead

## Examples
- Dark mode can be enabled in Settings → Appearance → Theme
- CSV export is no longer available; choose Excel or PDF from Export menu

## Documentation
- [Dark mode guide](https://docs.example.com/settings#dark-mode)
- [Migration notes](https://docs.example.com/upgrade#database)
```

---

## Workflow for Agent

1. **Parse input** — extract `from_tag`, `to_tag`, `repo_path`, and optional filters
2. **Discover public docs URL** — inspect `README.md`, `pyproject.toml`, `mkdocs.yml`, `docs/conf.py`, or `.readthedocs.yml` for the published documentation URL. Prefer ReadTheDocs, GitHub Pages, or the project's public docs site. If none is found, omit doc links.
3. **Fetch commits** — run `git log` with range, collect hashes and messages
4. **Read diffs per file** — use `git show <hash>` for each relevant commit and examine changed behavior, not just filenames
5. **Apply the user-impact gate** — discard CI, internal, process, and implementation-only changes unless the diff proves direct user impact
6. **Interpret impact** — state what users can do, observe, configure, rely on, or learn differently
7. **Detect breaking changes** — scan for BREAKING markers, public API removals, format changes, migrations, and changed defaults
8. **Group by category** — assign each qualifying change to **New Features**, **Enhancements**, **Bug Fixes**, **Breaking Changes**, **Examples**, or **Documentation**
9. **Build examples** — for each user-facing change, use README, public docs, tests, or CLI help as evidence and add a short example only when it clarifies the user outcome
10. **Consolidate** — merge related items, remove duplicates and flip-flops
11. **Use a fallback** — if no product change qualifies, emit exactly one of **Maintenance**, **Documentation**, or **Internal**
12. **Format markdown** — generate clean section headings and bullets with no title, preamble, footer, file summary, or commit summary
13. **Use public docs links** — every Documentation bullet and every feature/enhancement docs reference must use the public URL with a fragment identifier, not a repo-relative path

---

## Output Format

**Clean markdown** for a GitHub Release body:

```markdown
## New Features
- Added dark mode toggle in settings
- New PDF export option

## Enhancements
- Improved search performance (supports partial matches)
- Faster file opening for large documents

## Bug Fixes
- Fixed login failures on slow connections
- Resolved crash when uploading 10MB+ files

## Breaking Changes
- Database schema updated — run migration before upgrading

## Examples
- Enable dark mode from Settings → Appearance → Theme
- Export a report as PDF from the File → Export menu

## Documentation
- [Dark mode guide](https://docs.example.com/settings#dark-mode)
- [Upgrade instructions](https://docs.example.com/upgrade#database)
```

For a release with no runtime product impact, use this consistent shape:

```markdown
**Maintenance**

This release primarily includes updates to the knowledge base documentation and internal repository structure. No changes to the core product functionality or user-facing features.
```

**Key Rules:**
- One line per bullet point
- No sub-bullets or elaborate descriptions
- User impact only (not implementation details, changed-file summaries, CI, internal process, or contributor guidance)
- Do not include a title heading; the GitHub Release supplies the title
- Use public documentation URLs; never use repo-relative paths like `docs/...` or `README.md`
- Use fragment identifiers (`#section-name`) to point to specific docs sections
- Add an **Examples** section when the diff shows a CLI command, API call, config snippet, or before/after behavior
- Add a **Documentation** section only when public user documentation changed in a way users need or benefit from; never report internal guidelines or maintainer documentation
- Multiple links OK if they point to different topics
- Omit any section that has no bullets
- If no user-facing change qualifies, emit exactly one concise bold `Maintenance`, `Documentation`, or `Internal` block followed by one explanatory paragraph
- Never include file counts, changed-file lists, commit metadata, CI/workflow summaries, or a closing separator
- Do not add a "Notes", "Miscellaneous", or "Other" catch-all section

---

## Non-interactive automation mode

When this skill is invoked by a CI job with an explicit request for machine-readable output:

- Honor the requested tag range and repository path exactly.
- Do not modify, commit, or push repository files unless the caller explicitly requests it.
- Return only the final release-note Markdown, without an explanation, title heading, or code fence.
- If the caller uses Copilot CLI JSONL output, place the final Markdown in one `assistant.message` response; reasoning and tool events are metadata, not release content.
- Preserve the user-impact categories, examples, breaking-change detection, and public documentation links described above.

## How to Use This Skill in a Session

**User Query:**
```
Generate release notes from v2.1.0 to v2.2.0 for /path/to/my-app
```

**Agent Workflow:**
1. Navigate to repo: `cd /path/to/my-app`
2. Fetch commits: `git log v2.1.0..v2.2.0 --oneline --no-merges`
3. For each commit, examine changes: `git show <hash>`
4. Interpret: What's the user impact? (not the code details)
5. Categorize: Feature? Bug fix? Breaking change?
6. Consolidate: Merge similar items
7. Format: Clean markdown with categories
8. Output: Save to RELEASE_NOTES.md

---

## Best Practices

✅ **Do:**
- Read actual diffs to understand changes
- Use end-user language ("improved performance" not "optimized O(n) loop")
- Require evidence of a user-visible consequence before including a change
- Include breaking changes prominently
- Group related changes
- Add concrete examples drawn from README, docs, tests, or CLI help in the diff
- Link to the project's public documentation site (ReadTheDocs, GitHub Pages, etc.)
- Omit empty sections

❌ **Don't:**
- Copy commit messages verbatim
- Include function/variable names
- Mention internal refactors users won't notice
- Include dependency bumps or build changes unless they are user-visible
- Include secrets, passwords, or internal URLs
- Use repo-relative paths like `docs/source/how-to/...` or `README.md`
- Report CI, workflows, internal skills, contributor guidelines, maintainer process, file counts, or changed-file lists as release content
- Add a title heading to the generated body
- Make up changes not shown in diffs

---

## Common Patterns

**Performance improvements:**
> "Improved search speed when filtering 1000+ records"

**New integrations:**
> "Added support for OAuth login via GitHub"

**Data format changes:**
> "Settings file now uses JSON instead of YAML (auto-converted on first run)"

**Removed features:**
> "Removed IE 11 support to modernize codebase"

**API changes:**
> "Changed user profile endpoint response format (see migration guide)"

---

## Limitations

- Requires a git repository with proper tags
- Complex changes may need human interpretation
- Very large diffs should be reduced to their evidenced user impact; never summarize them by file count
- Works best with semantic versioning (v1.0.0 format)
- Needs meaningful commit messages for best results, but commit messages alone are never evidence of user impact
