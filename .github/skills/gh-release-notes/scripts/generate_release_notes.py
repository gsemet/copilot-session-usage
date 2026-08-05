#!/usr/bin/env python3
"""Generate and validate release notes through the GitHub Copilot CLI."""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
import textwrap
from collections.abc import Sequence
from pathlib import Path

SKILL_NAME = "gh-release-notes"
DEFAULT_OUTPUT = Path("release-notes.md")
TRACE_MARKERS = (
    "<function_call",
    "<thinking>",
    "<system_notification>",
    "assistant.reasoning",
    "function_calls",
)
FIRST_LINE = re.compile(
    r"^(?:## (?:New Features|Enhancements|Bug Fixes|Breaking Changes|Examples|Documentation)"
    r"|\*\*(?:Maintenance|Documentation|Internal)\*\*|## (?:Maintenance|Internal))$"
)
INTERNAL_DETAIL = re.compile(
    r"\b(?:ci|ci/cd|workflow(?:s)?|release automation|internal guidelines?|tests?|"
    r"commits?|pull requests?|individual files?)\b",
    re.IGNORECASE,
)
FALLBACK_TEXT = (
    "This release primarily includes updates to the knowledge base documentation "
    "and internal repository structure. No changes to the core product functionality "
    "or user-facing features."
)


def build_parser() -> argparse.ArgumentParser:
    """Build the command-line argument parser."""
    parser = argparse.ArgumentParser(
        description="Generate or validate release notes for the gh-release-notes skill."
    )
    parser.add_argument(
        "--from-ref",
        help="Starting Git ref. It is excluded: the range is from_ref..to_ref.",
    )
    parser.add_argument(
        "--to-ref",
        help="Ending Git ref. It is included: the range is from_ref..to_ref.",
    )
    parser.add_argument(
        "--repo",
        type=Path,
        default=Path.cwd(),
        help="Repository to inspect (default: current directory).",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help="Release-note output path (default: release-notes.md).",
    )
    parser.add_argument(
        "--model",
        default=None,
        help="Copilot CLI model identifier; defaults to COPILOT_MODEL or the CLI default.",
    )
    parser.add_argument(
        "--validate",
        type=Path,
        metavar="FILE",
        help="Normalize and validate an existing release-note Markdown file.",
    )
    return parser


def build_prompt(from_ref: str, to_ref: str, repo: Path, output: Path) -> str:
    """Build the concise execution prompt sent to the release-note skill."""
    repo_text = repo.as_posix()
    output_text = output.as_posix()
    return textwrap.dedent(
        f"""
        Use the /{SKILL_NAME} skill.

        Generate release notes for the exact Git range {from_ref}..{to_ref} in {repo_text}.
        Exclude {from_ref} and include {to_ref}. Inspect the diff and relevant
        project documentation, then follow the skill's user-impact, categorization,
        documentation-linking, and output-format rules.

        Write only the final release-note Markdown to {output_text}. Follow the skill's
        required section or fallback format; do not add a title, preamble,
        explanation, code fence, or response-only summary.
        """
    ).strip()


def build_copilot_command(prompt: str, model: str | None) -> list[str]:
    """Build the non-interactive Copilot CLI command."""
    command = [
        "gh",
        "copilot",
        "--",
        "--prompt",
        prompt,
        "--silent",
        "--no-ask-user",
        "--no-auto-update",
        "--no-color",
        "--output-format",
        "text",
        "--disable-builtin-mcps",
        "--available-tools=read,create,edit,bash",
        "--allow-tool=read",
        "--allow-tool=write",
        "--allow-tool=shell(git:*)",
        "--allow-url=https://github.com",
        "--allow-url=https://copilot-session-usage.readthedocs.io",
    ]
    if model:
        command.extend(["--model", model])
    return command


def resolve_path(path: Path, repo: Path) -> Path:
    """Resolve a path relative to the repository when it is not absolute."""
    return path if path.is_absolute() else repo / path


def run_git(repo: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
    """Run a Git command in the target repository."""
    return subprocess.run(
        ["git", *arguments],
        cwd=repo,
        check=False,
        capture_output=True,
        text=True,
    )


def validate_range(repo: Path, from_ref: str, to_ref: str) -> None:
    """Verify that the requested refs exist and form an ancestor range."""
    if from_ref == to_ref:
        raise ValueError("--from-ref and --to-ref must be different refs.")

    for ref in (from_ref, to_ref):
        result = run_git(repo, "rev-parse", "--verify", f"{ref}^{{commit}}")
        if result.returncode != 0:
            detail = result.stderr.strip() or "unknown Git error"
            raise ValueError(f"Git ref {ref!r} is not available: {detail}")

    result = run_git(repo, "merge-base", "--is-ancestor", from_ref, to_ref)
    if result.returncode != 0:
        raise ValueError(f"Git ref {from_ref!r} is not an ancestor of {to_ref!r}.")


def run_skill_check(repo: Path) -> None:
    """Ensure the release-note skill is installed in the Copilot CLI."""
    result = subprocess.run(
        ["gh", "copilot", "--", "skill", "list"],
        cwd=repo,
        check=False,
        capture_output=True,
        text=True,
    )
    output = f"{result.stdout}\n{result.stderr}"
    if result.returncode != 0:
        raise RuntimeError(f"Unable to list Copilot skills:\n{output.strip()}")
    if SKILL_NAME not in output:
        raise RuntimeError(f"Copilot skill {SKILL_NAME!r} is not installed.")


def require_copilot_token() -> None:
    """Fail early when neither supported GitHub token environment variable exists."""
    if not (os.environ.get("COPILOT_GITHUB_TOKEN") or os.environ.get("GH_TOKEN")):
        raise RuntimeError("Set COPILOT_GITHUB_TOKEN or GH_TOKEN before running Copilot CLI.")


def run_copilot(repo: Path, prompt: str, model: str | None) -> None:
    """Run Copilot CLI and fail with its captured diagnostics when needed."""
    result = subprocess.run(
        build_copilot_command(prompt, model),
        cwd=repo,
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        output = f"{result.stdout}\n{result.stderr}".strip()
        raise RuntimeError(f"Copilot CLI failed with exit code {result.returncode}:\n{output}")


def _release_start(notes: str) -> int | None:
    """Find the first valid release section after optional model preamble text."""
    heading_pattern = r"(?m)^(?:## .+|\*\*(?:Maintenance|Documentation|Internal)\*\*)\s*$"
    for match in re.finditer(heading_pattern, notes):
        if FIRST_LINE.fullmatch(match.group(0).strip()):
            return match.start()
    return None


def normalize_release_notes(content: str) -> str:
    """Normalize harmless model formatting drift into the release-note contract."""
    notes = content.strip()
    if not notes:
        raise ValueError("Release notes are empty.")

    lowered = notes.lower()
    leaked_markers = [marker for marker in TRACE_MARKERS if marker.lower() in lowered]
    if leaked_markers:
        markers = ", ".join(leaked_markers)
        raise ValueError(f"Release notes contain Copilot trace markers: {markers}")
    if "```" in notes:
        raise ValueError("Release notes must not contain a code fence.")

    start = _release_start(notes)
    if start is None:
        raise ValueError("Release notes do not contain a recognized release section.")
    notes = notes[start:].strip()
    first_line, separator, remainder = notes.partition("\n")

    if first_line.startswith("## ") and first_line[3:] in {"Maintenance", "Internal"}:
        first_line = f"**{first_line[3:]}**"
        notes = f"{first_line}{separator}{remainder}".strip()

    if notes.startswith("**"):
        if INTERNAL_DETAIL.search(notes) or "\n## " in notes:
            return f"**Maintenance**\n\n{FALLBACK_TEXT}\n"
        paragraphs = [paragraph for paragraph in notes.split("\n\n") if paragraph.strip()]
        if len(paragraphs) != 2:
            raise ValueError("Fallback release notes must contain one label and one paragraph.")

    return f"{notes}\n"


def validate_release_notes(content: str) -> None:
    """Raise ``ValueError`` when release-note content violates the output contract."""
    normalize_release_notes(content)


def validate_output(output: Path) -> None:
    """Normalize and validate release-note Markdown in place."""
    try:
        content = output.read_text(encoding="utf-8")
        normalized = normalize_release_notes(content)
        validate_release_notes(normalized)
        output.write_text(normalized, encoding="utf-8")
    except (OSError, ValueError) as error:
        preview = ""
        if "content" in locals():
            first_lines = "\n".join(content.strip().splitlines()[:5])[:500]
            preview = f" First lines (up to 500 characters): {first_lines!r}."
        message = str(error).rstrip(".")
        raise RuntimeError(f"Release-note validation failed: {message}.{preview}") from error
    print("Release-note Markdown validation passed.")


def generate_release_notes(
    repo: Path,
    from_ref: str,
    to_ref: str,
    output: Path,
    model: str | None,
) -> None:
    """Generate release notes, then validate the resulting Markdown file."""
    repo = repo.resolve()
    output = resolve_path(output, repo).resolve()
    validate_range(repo, from_ref, to_ref)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.unlink(missing_ok=True)

    print(f"Generating release notes from {from_ref} (exclusive) to {to_ref} (inclusive).")
    print(f"Copilot model: {model or 'CLI default'}")
    require_copilot_token()
    run_skill_check(repo)
    run_copilot(repo, build_prompt(from_ref, to_ref, repo, output), model)

    if not output.is_file() or not output.read_text(encoding="utf-8").strip():
        raise RuntimeError(f"Copilot did not create a non-empty release-note file: {output}")
    validate_output(output)
    print(f"Release notes written to {output}")


def main(argv: Sequence[str] | None = None) -> int:
    """Parse arguments, generate or validate notes, and return an exit code."""
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.validate is not None:
        if args.from_ref is not None or args.to_ref is not None:
            parser.error("--validate cannot be combined with --from-ref or --to-ref")
        try:
            validate_output(args.validate)
        except (OSError, RuntimeError, ValueError) as error:
            print(f"error: {error}", file=sys.stderr)
            return 1
        return 0

    if args.from_ref is None or args.to_ref is None:
        parser.error("--from-ref and --to-ref are required unless --validate is used")

    try:
        generate_release_notes(
            repo=args.repo,
            from_ref=args.from_ref,
            to_ref=args.to_ref,
            output=args.output,
            model=args.model or os.environ.get("COPILOT_MODEL"),
        )
    except (OSError, RuntimeError, ValueError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
