---
name: gh-create-pull-request
description: 'Publish the current Git branch with gh, create or reuse a pull request, monitor GitHub Actions, and repair pipeline failures with one Conventional Commit per fix. Use when asked to push a branch, open a pull request, watch CI, or fix pipeline failures.'
argument-hint: 'Optional PR title, body, or target branch'
user-invocable: true
disable-model-invocation: true
---

# Create Pull Request and Repair CI

Use only for an explicit request to publish the current branch, open a GitHub
pull request, monitor its pipeline, or repair a failed pipeline with `gh`.

## Rules

- Find applicable convention or guidelines applicable for the project first.
  Follow those project conventions when creating commits.
- Confirm `gh auth status`, the repository, current branch, default branch, and
  a clean working tree. Stop for a detached/default branch, empty diff.
  Use `/gh-commit-changes` for uncommitted or staged changes.
- Push without rewriting history, create or reuse the branch's PR with `gh pr`,
  and do not merge it unless separately requested.
- Watch checks with `gh pr checks --watch`; inspect failures with `gh run list`
  and `gh run view`. Rerun only clearly transient failures.
- For a code failure, make the smallest safe fix, run the relevant project
  checks, stage only that fix, invoke `/gh-commit-changes` once, push, and watch
  the new run. One independent root cause means one new commit.
- Never weaken checks, expose secrets, force-push, amend, or rewrite history.
  Stop for administrative or unclear failures and report what is needed.

## Completion

Report the PR URL, final commit, fix commits, confirmed check results, and any
remaining external action. Do not claim success without evidence from `gh`.
