---
applyTo: "knowledge/**/*.md"
description: "How coding agents maintain the OKF knowledge bundle in knowledge/."
---

# Knowledge Base Maintenance Guidelines

The `knowledge/` directory is an [OKF](https://github.com/gsemet/okf-schema) (Open Knowledge Format) bundle. It is **not** bundled in the wheel — it lives at repo root for agent and maintainer reference only.

## What Is OKF?

OKF is a lightweight convention for organizing markdown knowledge bases with validated YAML frontmatter. Each document has a `type` field that maps to a JSON Schema in `knowledge/_schema/`.

## Schema Files

| Schema | For Documents | Purpose |
|--------|--------------|---------|
| `_schema/Concept.schema.yml` | `concepts/*.md` | Core concepts and explanatory documents |
| `_schema/Playbook.schema.yml` | `guides/*.md` | Step-by-step guides and actionable workflows |
| `_schema/Reference.schema.yml` | `reference/*.md` | Structured data, schemas, or lookup tables |

## When to Add a New Document

| You want to... | Use type | Put in |
|----------------|----------|--------|
| Explain how something works | `Concept` | `knowledge/concepts/` |
| Provide a step-by-step procedure | `Playbook` | `knowledge/guides/` |
| Document a format, schema, or lookup table | `Reference` | `knowledge/reference/` |
| Brainstorm a future feature | `Concept` | `knowledge/ideas/` |

**Important rules**:

- document only what is not trivial for Coding Agents.
- do not paraphrase existing documentation or code, you can point if needed.
- focus on explaining how the external world works, like truthful facts, not opinions or speculation.
- each knowledge file should be focussed, concise, with important information at the top. Avoid long, rambling documents.
- prefere short, focussed documents with links and relationships.

## Required Frontmatter

Every `.md` file under `knowledge/` (except `index.md` and `log.md`) must have:

```yaml
---
type: Concept          # or Playbook, Reference
title: Human-Readable Title
description: Short summary of what this document covers.
tags: [keyword, another-tag]
timestamp: 2026-07-01T00:00:00Z
---
```

Rules:

- `type` must match the `const` in the corresponding schema file.
- `title` and `description` must be non-empty strings.
- `tags` is optional but strongly encouraged for searchability.
- `timestamp` must be ISO 8601 (`YYYY-MM-DDTHH:MM:SSZ`).

## After Adding or Editing a File

1. **Run validation:**
   ```bash
   just knowledge-validate
   ```
2. **Run lint (auto-fixes frontmatter formatting):**
   ```bash
   just knowledge-lint
   ```
3. **Verify with the check-only variant:**
   ```bash
   just knowledge-lint-check
   ```

All three commands must pass before committing.

## When to Update Existing Documents

| Trigger | Update |
|---------|--------|
| New VS Code Copilot version or new event types | `concepts/vscode-copilot-extension.md` |
| New JSONL fields in debug logs | `reference/debug-log-format.md` |
| New pricing tiers or model names | `reference/pricing-formats.md` + `models-and-pricing.yml` |
| Pricing data drift | Run `just refresh-pricing` |
| New cost-optimization pattern discovered | `concepts/cost-optimization.md` |

## Log Updates

Add a dated entry to `knowledge/log.md` for significant changes (refactors, bug fixes, discoveries). Use plain ISO-8601 date headings:

```markdown
## 2026-07-01

### brief-topic
- Bullet describing the change.
```

Avoid parenthetical annotations in headings — they trigger OKF validation warnings.

## Pre-Commit Checklist

- [ ] New or edited files have valid YAML frontmatter
- [ ] `just knowledge-validate` passes (0 errors, 0 warnings)
- [ ] `just knowledge-lint-check` passes
- [ ] `just preflight` passes (includes knowledge checks)
