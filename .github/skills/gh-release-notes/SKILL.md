# Release Notes Generator (Git Diff Based)

Generate **end-user friendly** release notes by analyzing actual code changes between releases.
No scripts required — uses git commands to understand what changed and why it matters.

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
2. **Interprets for end-users** — no technical jargon, functions, or variable names
3. **Categorizes intelligently** — Features, Enhancements, Bug Fixes, Breaking Changes
4. **Consolidates related changes** — groups related diffs, eliminates back-and-forth noise
5. **Outputs clean markdown** — Slack-ready format suitable for announcements

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

### Step 1: Collect Commits
```bash
git log v1.0.0..v1.1.0 --oneline --no-merges
```
Gather all commits in the specified range with their messages.

### Step 2: Examine Diffs
```bash
git diff v1.0.0..v1.1.0 -- src/
```
Read actual code changes line-by-line to understand what changed.

### Step 3: Interpret Changes

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

Organize changes into buckets:

```markdown
# Release Notes - v1.1.0

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

---
**Notes:**
- Dark mode requires display driver update on Windows 7
- Migration tool available at: docs/migrate-db.md
```

---

## Workflow for Agent

1. **Parse input** — extract `from_tag`, `to_tag`, `repo_path`, and optional filters
2. **Fetch commits** — run `git log` with range, collect hashes & messages
3. **Read diffs per file** — `git show <hash>` for each commit, examine changed files
4. **Interpret impact** — what does each change mean to users?
5. **Detect breaking changes** — scan for BREAKING markers, API removals, schema changes
6. **Group by category** — assign each change to Features/Enhancements/Bug Fixes/Breaking/Other
7. **Consolidate** — merge related items, remove duplicates and flip-flops
8. **Format markdown** — generate clean bullet points with proper headings
9. **Add footnotes** — include migration notes, setup requirements, important links

---

## Output Format

**Ultra-concise markdown** (aim for 100-200 words total):

```markdown
# Release Notes - v1.1.0

## New Features
- Dark mode toggle in settings
- PDF export option

## Enhancements
- Improved search performance (supports partial matches)
- Faster file opening for large documents

## Bug Fixes
- Fixed login failures on slow connections
- Resolved crash when uploading 10MB+ files

## Breaking Changes
- Database schema updated — run migration before upgrading

**Learn more:**
- [Dark Mode Guide](https://docs.example.com/settings#dark-mode)
- [Upgrade Instructions](https://docs.example.com/upgrade#database)
```

**Key Rules:**
- One line per bullet point
- No sub-bullets or elaborate descriptions
- Total length: <200 words
- User impact only (not implementation details)
- Use fragment identifiers (`#section-name`) to point to specific docs sections
- Multiple links OK if they point to different topics (Skill Analysis, Aggregation, etc.)
- Link from feature description → to exact readthedocs section where users will find details

---

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
- Include breaking changes prominently
- Group related changes
- Add notes about migrations or setup

❌ **Don't:**
- Copy commit messages verbatim
- Include function/variable names
- Mention internal refactors users won't notice
- Include secrets, passwords, or internal URLs
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

- Requires git repository with proper tags
- Complex changes may need human interpretation
- Very large diffs (1000+ files) summarized by file count
- Works best with semantic versioning (v1.0.0 format)
- Needs meaningful commit messages for best results
