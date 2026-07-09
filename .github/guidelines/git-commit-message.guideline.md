---
name: Git Commit Message Guideline 1.0
description: Guidelines for writing conventional commits that communicate intent and user impact
metadata:
  owner: Gaetan Semet <gaetan.semet@ampere.cars>
  keywords: [git, commit, conventional, message, changelog]
  guideline-id: 45c42e46-0781-4954-a410-1f380f5553f3
---

# Git Commit Message Guideline

Write clear, focused commit messages following Conventional Commits format. Commit messages communicate *why* changes were made—enabling automated changelog generation, bug investigation, and decision-making during upgrades. Focus on user impact, not implementation details.

## Core Rules

### Rule 1: Use Conventional Commit Format

**Apply:** Format every title as `type(scope): description`

**Why:** Enables automated changelog generation and consistent pattern parsing.

**Types:** `feat`, `fix`, `docs`, `style`, `refactor`, `perf`, `test`, `ci`, `chore`, `build`, `revert`

**Examples:**
```
feat(auth): add two-factor authentication support
fix(api): resolve request timeout in user endpoint
docs(readme): update installation instructions
perf(cache): optimize query performance by 40%
test(validators): add email format validation tests
```

---

### Rule 2: Keep Title Under 50 Characters, Body Under 72 Per Line

**Apply:** Enforce character limits for scannability and terminal compatibility.

**Why:** Short titles force clarity; wrapped body text maintains readability in terminals and email clients.

**Example:**
```
feat(cache): implement LRU eviction policy

Reduces memory usage in long-running processes by
automatically removing least-recently-used items.

Changes:
- Cache drops oldest accessed items upon limit
- Configurable cache size (default 1000)
- < 2% performance overhead on reads

Users can set CACHE_SIZE environment variable.
```

---

### Rule 3: Focus Body on User Impact, Not Implementation Details

**Apply:** Describe what users gain and must know; exclude refactoring details, internal functions, and test additions.

**Why:** Users deciding whether to upgrade, developers integrating changes, and bug investigators need user-level context—not code structure details.

**Example:**
```
fix(api): allow null values in optional response fields

Optional fields now omitted from JSON when empty,
reducing response payload by ~15% for sparse data.

Migration:
- Check `field in response` instead of `field != null`
- Response schema updated in API reference
```

---

### Rule 4: Include Breaking Changes with Migration Guidance

**Apply:** Use `!` in title and `BREAKING CHANGE:` section. Provide explicit migration steps.

**Why:** Breaking changes require user action; clear guidance reduces upgrade confusion.

**Example:**
```
feat(api)!: change pagination to cursor-based tokens

Cursors improve performance with large datasets.

BREAKING CHANGE: Replaced `pagination_offset` and
`pagination_limit` with `pagination.cursor`.

Migration:
Old: GET /users?limit=10&offset=20
New: GET /users?limit=10&cursor=xyz123

Update code to use `response.pagination.cursor`
in next request instead of offset/limit.
```
