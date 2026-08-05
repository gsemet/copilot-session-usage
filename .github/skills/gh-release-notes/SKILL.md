---
name: gh-release-notes
description: Generate end-user-friendly GitHub release notes from the actual diff between releases, including user impact, examples, breaking changes, and public documentation links.
argument-hint: "from_ref=... to_ref=... repo_path=..."
user-invocable: true
---

# Release Notes Generator (Git Diff Based)

Generate **end-user-friendly, user-impact-only** release notes by analyzing the actual changes between releases.
Interactive use requires no script; automated generation and validation use the bundled script described below.

The output is meant to be **copy-pasted into a GitHub Release**. It must contain release-note sections only: never add a document title, preamble, file summary, commit summary, or closing separator.

## Non-negotiable output contract

- Render every public documentation URL as an inline Markdown link with concise
	descriptive text: `See the [pricing reference for details](https://example.com/pricing)`.
- Never expose a documentation URL as plain text, after a colon, in parentheses,
	or on its own line. A bare `https://...` URL is invalid release-note output.
- Never include CI, release automation, Git evidence, generator internals,
	governance, contributor or agent guidance, tests, repository housekeeping, or
	maintainer process.
- Never include `## Maintenance` together with any user-facing section. When a
	user-facing change qualifies, omit Maintenance and discard all internal-only
	candidates.
- Before writing the file, inspect the final Markdown for these rules and remove
	any violating bullet or section.

## Bundled automation script

The skill includes `scripts/generate_release_notes.py`, a standalone Python script that:

- verifies the requested Git range and Copilot skill availability;
- precomputes the commit log and complete diff locally so generation also works
	when the Copilot CLI cannot inspect Git history inside its tool environment;
- invokes the Copilot CLI with `/gh-release-notes`;
- writes the requested output file; and
- verifies only that the requested output file is readable and non-empty. The
	script does not normalize Markdown or decide user impact, categorize changes,
	discover documentation, infer breaking changes, or require examples; those
	decisions belong to this skill.

Generate notes for an exact range from the repository root:

```bash
python .github/skills/gh-release-notes/scripts/generate_release_notes.py \
	--from-ref v1.0.0 \
	--to-ref v1.1.0 \
	--output release-notes.md
```

The range is Git's two-dot range, `from_ref..to_ref`: `from_ref` itself is excluded
and `to_ref` is included. Both refs may be tags, branches, or commit IDs.

Set `COPILOT_MODEL` or pass `--model` to make model selection explicit. The script also
supports `--validate FILE` when an existing release-note file should be checked for
readability and non-empty content without invoking Copilot.

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
2. **Applies a strict user-impact gate** — includes a change only when an end user can do, observe, configure, rely on, or learn something different
3. **Interprets for end-users** — no technical jargon, functions, variable names, file paths, or implementation summaries
4. **Categorizes intelligently** — Features, Enhancements, Bug Fixes, Breaking Changes, Examples, Documentation, and Maintenance
5. **Adds concrete examples** — shows what users see or can do after a qualifying change
6. **Links to relevant public docs** — links each user-facing change to the closest published documentation page with concise inline Markdown link text when one exists, even if that page was not changed in the release
7. **Consolidates related changes** — groups related diffs and eliminates back-and-forth noise
8. **Outputs clean markdown** — ready to paste into a GitHub Release note

---

## Input

Accept either:

- **Natural language**: "Show release notes from v1.2.0 to v1.3.0"
- **Range spec**: `from_ref=v1.2.0 to_ref=v1.3.0 repo_path=/path/to/repo`
- **Last release**: `since_tag=v1.2.0` (everything from tag to HEAD)

Required:
- Repository path (optional: defaults to current directory)
- Range: `from_ref` + `to_ref`, OR `since_tag`, OR `last_n_commits`

---

## Analysis Process

### Step 0: Apply the release-worthiness gate

Before writing any bullet, ask: **What can a user do, observe, configure, rely on, or learn differently after this change?** Require evidence from the diff, public CLI/API help, supported configuration, user-facing output, migration behavior, or published documentation.

Apply this audience test to every candidate: **Would a normal user of the
published package or application care about this change, or would only a
maintainer, contributor, release engineer, or agent care?** If only the latter,
discard it. Do not convert an internal change into a release note merely because
it improves reliability, process, maintainability, or documentation quality for
the project team.

Include a change only if it has at least one of these effects:

- Adds, removes, fixes, or changes a user-facing feature, command, API, configuration option, output, error message, compatibility guarantee, or supported platform.
- Changes runtime behavior in a way users can observe, such as performance, reliability, pricing data, security behavior, or data handling.
- Changes public documentation that users actually consume to operate the product, including a new guide, changed instructions, or migration guidance.

Documentation relevance is separate from documentation impact. A code, data, API,
configuration, or runtime change can require a documentation link even when no
documentation file changed in the range. Use the nearest existing **end-user**
reference page as the explanation and destination for that link.

Public documentation means documentation that helps users install, configure,
operate, or understand the published product. A public URL is not enough by
itself. Exclude documentation whose audience is contributors or maintainers,
including `AGENTS.md`, `CONSTITUTION.md`, contributor guides, engineering
guidelines, internal runbooks, CI instructions, release procedures, and agent
skill instructions. Never place those documents in `## Documentation`.

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

Treat these as non-release content, and exclude them entirely unless the diff
also proves a direct change to the published user experience:

- CI/CD workflows, automation, release jobs, repository settings, and bot configuration
- Release-note generators, Git evidence collection, release automation, and validation scripts
- `AGENTS.md`, `CONSTITUTION.md`, contributor guidelines, engineering process, maintainer runbooks, and internal skills or agent prompts
- Tests, fixtures, formatting, linting, refactors, type annotations, and code organization
- Dependency, lockfile, build, packaging, or development-environment changes without a user-visible runtime consequence
- `.gitignore`, repository housekeeping, file moves, internal URLs, and documentation indexes for project maintainers
- File counts, changed-file lists, commit counts, authors, implementation details, and internal URLs

These exclusions can be overridden only when the diff proves a direct user
impact, such as a packaging change that changes the installable artifact or a
security fix that changes behavior for users. In that case, describe the user
outcome, not the internal mechanism or workflow that enabled it.

After identifying a qualifying change, inspect the repository's user-facing
documentation surfaces for the impacted concept, command, option, model, data
format, or workflow. Use whatever public documentation the repository exposes,
including linked sites, hosted reference pages, guides, examples, CLI/API
references, or documentation indexes. Do not assume a particular language,
documentation generator, directory layout, metadata file, or URL naming scheme.
Documentation does not need to appear in the Git range to be relevant.

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

For each qualifying change, select the closest documentation page that explains
the changed behavior. Prefer a focused reference or how-to page over the
documentation home page. When a relevant page exists, attach it as a concise
inline Markdown link in the corresponding release-note bullet or example. Put
the descriptive words in the link text and do not expose the full URL in prose:
write `See the [pricing reference for details](https://example.com/pricing)`,
not `See the pricing reference for details: https://example.com/pricing`.
Do not wait for the documentation page itself to be modified. For example, a
pricing or model-data change should link to the project's pricing/model reference
page if that page explains the affected behavior.

If no trustworthy public documentation URL can be established, omit the
Documentation section and documentation bullets rather than writing a text-only
documentation entry. Never emit `## Documentation` unless its body contains at
least one Markdown link with descriptive link text and an absolute HTTPS target.
For every public documentation URL that is included anywhere in the release
notes, the only valid rendering is `[descriptive link text](https://...)`.
Never render a public URL as plain text after a colon, inside prose, or on its
own line. Before writing the final file, check that every `https://` occurrence
is inside a Markdown link target and that the visible text is concise and
descriptive.

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

The only permitted headings are `## New Features`, `## Enhancements`, `## Bug
Fixes`, `## Breaking Changes`, `## Examples`, `## Documentation`, and
`## Maintenance`. Do not add headings such as `Internal`, `User impact`, `Upgrade
notes`, or `Summary`; fold useful user impact into the permitted sections instead.

Treat Documentation as a link-only section: include it only when at least one
trustworthy public documentation URL was found, and make every Documentation
bullet an inline Markdown link with descriptive link text and an absolute HTTPS
target. If no such URL was found, omit the entire Documentation section. Do not
replace the missing URL with a repository path, an unlinked description, or a
claim that documentation was updated.

If no qualifying user-facing change exists, emit exactly one concise `## Maintenance`
section. Explain generically that the release contains maintenance and internal
improvements without naming CI, workflows, release automation, internal guidelines,
tests, commits, pull requests, governance files, documentation files, or individual
files. Do not invent a feature, user benefit, example, or documentation link. Never
publish `Internal` or an empty maintenance section. If at least one user-facing
change exists, omit Maintenance entirely; do not use it as a bucket for leftover
internal changes.

`## Maintenance` and a user-facing section are mutually exclusive. If any
Enhancements, New Features, Bug Fixes, Breaking Changes, Examples, or qualifying
Documentation bullet remains, remove `## Maintenance` and all of its bullets.

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

## Maintenance
This release contains maintenance and internal improvements. No user-facing behavior
changed.
```

Omit `## Breaking Changes` completely when the actual range contains no breaking
change. Never add a section containing `None`, `No breaking changes`, or an
equivalent placeholder. Keep bullets concise: one line, one user outcome, and no
nested explanation. Do not describe internal mechanisms such as locks, checksums,
provenance, atomic writes, refactors, or implementation details unless the user can
directly observe a supported behavior that the mechanism enables.

---

## Workflow for Agent

1. **Parse input** — extract `from_ref`, `to_ref`, `repo_path`, and optional filters
2. **Discover public documentation** — inspect the repository's available user-facing documentation surfaces and any published links they expose. Do not assume a particular language, documentation generator, directory layout, metadata file, or URL naming scheme. Prefer the closest trustworthy public page for each qualifying change. Use absolute HTTPS URLs, and omit a documentation link when no public page can be established rather than inventing one.
3. **Fetch commits** — run `git log` with range, collect hashes and messages
4. **Read diffs per file** — use `git show <hash>` for each relevant commit and examine changed behavior, not just filenames
5. **Apply the user-impact gate** — discard CI, internal, process, and implementation-only changes unless the diff proves direct user impact
6. **Interpret impact** — state what users can do, observe, configure, rely on, or learn differently
7. **Detect breaking changes** — scan for BREAKING markers, public API removals, format changes, migrations, and changed defaults
8. **Group by category** — assign each qualifying change to **New Features**, **Enhancements**, **Bug Fixes**, **Breaking Changes**, **Examples**, **Documentation**, or **Maintenance**
9. **Build examples** — for each user-facing change, use README, public docs, tests, or CLI help as evidence; add a concrete example for every added or changed CLI command, public API call, configuration option, or before/after workflow
10. **Consolidate** — merge related items, remove duplicates and flip-flops
11. **Handle an empty range** — if no product change qualifies, generate exactly one concise `## Maintenance` section
12. **Format markdown** — generate clean section headings and bullets with no title, preamble, footer, file summary, or commit summary
13. **Use concise relevant public docs links** — every Documentation bullet must contain an inline Markdown link with descriptive link text and an absolute HTTPS target to the closest relevant published page. Every qualifying feature, enhancement, bug-fix, breaking-change, or example bullet should use the same concise Markdown-link style when a page exists, using a fragment identifier when the page has a matching section. Do not expose bare URLs in prose or use bare URLs as the only link form. Do not require the page to have changed in the range. If no trustworthy public URL exists, omit Documentation entirely.
14. **Run the final audience review** — inspect every bullet and remove anything about CI, workflows, release tooling, Git evidence, validation, governance, contributor or agent guidance, repository housekeeping, changed files, or maintainer process. Remove the entire section if that leaves it empty. Also remove Documentation bullets whose links target contributor, governance, engineering, or maintainer material.
15. **Run the final format review** — ensure every `https://` occurrence is inside `[visible text](https://target)`, with no bare URL in prose, and remove `## Maintenance` whenever another qualifying section exists.

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

**Key Rules:**
- One line per bullet point
- No sub-bullets or elaborate descriptions
- User impact only (not implementation details, changed-file summaries, CI, internal process, or contributor guidance)
- Every bullet must describe a benefit or changed capability for ordinary users of the published product
- Do not include release tooling, Git evidence, validation behavior, governance files, contributor guidance, agent instructions, CI, workflows, or repository housekeeping
- Do not include a title heading; the GitHub Release supplies the title
- Use public documentation URLs; never use repo-relative paths like `docs/...` or `README.md`
- For each user-facing bullet, search existing documentation for the closest page about the impacted behavior and link it inline with descriptive Markdown text when available, even when the documentation file was unchanged
- Use fragment identifiers (`#section-name`) to point to specific docs sections
- Add a concrete **Examples** section for every added or changed CLI command, public API call, configuration option, or user-visible before/after behavior. Derive syntax from the project's public help, API docs, README, or supported usage examples; do not invent it
- Add a **Documentation** section only when at least one trustworthy public documentation URL exists; every bullet in that section must contain an absolute HTTPS Markdown link with descriptive link text. If no public URL can be established, omit the section and do not emit a text-only documentation bullet
- Prefer concise inline Markdown links in every section, such as `See the [pricing reference for details](https://example.com/pricing)`, rather than exposing a full URL after a colon or in parentheses
- Multiple links OK if they point to different topics
- Omit any section that has no bullets
- If no user-facing change qualifies, emit exactly one concise `Maintenance` section
- Never add an `Internal` section to a product release
- Use only the seven permitted release-note headings; do not add `User impact`, `Upgrade notes`, `Summary`, or other catch-all headings
- Omit `## Breaking Changes` unless the range contains concrete evidence of a breaking change; never use `None` or another placeholder
- Keep every bullet to one concise line and remove implementation-only detail, even when the underlying change improved robustness or safety
- Never include file counts, changed-file lists, commit metadata, CI/workflow summaries, or a closing separator
- Do not add a "Notes", "Miscellaneous", or "Other" catch-all section

---

## Non-interactive automation mode

When this skill is invoked by a CI job with an explicit output-file request:

- Honor the requested tag range and repository path exactly.
- Treat the requested output file as mandatory. Writing it is the only successful completion condition.
- Use the `create` file tool when the requested file does not exist, or the `edit` file tool when it already exists.
- After writing, use the `read` file tool to verify that the requested file exists and contains the final release-note Markdown.
- Do not modify, commit, or push any other repository files.
- The output file must contain only the final release-note Markdown, without an explanation, title heading, or code fence.
- The first line must be exactly one of: `## New Features`, `## Enhancements`, `## Bug Fixes`, `## Breaking Changes`, `## Examples`, `## Documentation`, or `## Maintenance`.
- Do not write a preamble, title, code fence, or explanatory text before the first release-note section.
- Never use the Copilot response stream as output. The caller may discard it after the file is written.
- Do not report the release notes only in the response. If the file cannot be written or verified, the task has failed.
- Preserve the user-impact categories, concrete examples, evidence-based breaking-change detection, and repository-derived public documentation links described above.

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
8. Output: Save to the requested output file, such as `release-notes.md`; if no user-facing change qualifies, save the generic `## Maintenance` release note

---

## Best Practices

✅ **Do:**
- Read actual diffs to understand changes
- Use end-user language ("improved performance" not "optimized O(n) loop")
- Require evidence of a user-visible consequence before including a change
- Include breaking changes prominently
- Omit the entire Breaking Changes section when no breaking change is evidenced
- Group related changes
- Add a concrete example for every changed CLI command, public API, configuration option, or before/after workflow, drawing syntax from README, public docs, or CLI/API help
- Discover and link to the project's public documentation when a trustworthy page is available
- Link each qualifying user-facing change to the closest relevant public documentation page when one exists, whether or not that page changed in the release
- Omit empty sections
- If a candidate cannot pass the normal-user audience test, omit it rather than placing it under Maintenance or Documentation

❌ **Don't:**
- Copy commit messages verbatim
- Include function/variable names
- Mention internal refactors users won't notice
- Include dependency bumps or build changes unless they are user-visible
- Include secrets, passwords, or internal URLs
- Use repo-relative paths like `docs/source/how-to/...` or `README.md`
- Report CI, workflows, internal skills, contributor guidelines, maintainer process, file counts, or changed-file lists as release content
- Add an `Internal` section to a product release
- Add a Breaking Changes section merely to say `None` or `No breaking changes`
- Describe internal implementation mechanisms as enhancements without a direct user-visible outcome
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
