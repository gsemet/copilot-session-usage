---
name: gh-commit-changes
description: 'Commit all changes already staged in the Git index as one new Conventional Commit without staging, amending, or pushing anything. Use when asked to commit staged changes or create a commit from the index.'
argument-hint: 'Optional intent or user-impact context for the commit message'
user-invocable: true
disable-model-invocation: true
---

# Commit Staged Changes

Create exactly one new commit from the Git index. Do not stage or unstage files,
include unstaged changes, amend or rewrite history, or push.

## Rules

- Find applicable convention or guidelines applicable for the project first.
  Follow those project conventions when creating commits.
- Inspect `git diff --cached` and `git diff --cached --check`. Stop if the index
  is empty, contains secrets or machine-local artifacts, mixes unrelated work,
  or fails the check. The caller owns index contents.
- Derive the commit message from all staged changes.
  Ensure to strictly follow the project convention, then run `git commit` exactly once.
  Do not use `--all`, `--amend`, or `--no-verify`.
- Construct the complete message before invoking Git: subject, body, and trailers.
  Do not pass each wrapped body line as a separate `-m` argument. Each `-m`
  argument creates a separate paragraph and introduces an unintended blank line.
  Pass the complete body as one message or use a complete commit-message file.
- For AI-assisted commits, use exactly one verified `Assisted-by` trailer as
  required by the guideline. Never guess the model or use the IDE name.
- Verify the new commit and report any remaining staged or unstaged changes. Do
  not claim that anything was pushed or that CI passed.
