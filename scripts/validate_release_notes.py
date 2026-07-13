#!/usr/bin/env python3
"""Validate release notes written by the gh-release-notes skill."""

from __future__ import annotations

import re
import sys
from pathlib import Path

TRACE_MARKERS = (
    "<function_call",
    "<thinking>",
    "<system_notification>",
    "assistant.reasoning",
    "function_calls",
)
FIRST_LINE = re.compile(
    r"^(?:## (?:New Features|Enhancements|Bug Fixes|Breaking Changes|Examples|Documentation)"
    r"|\*\*(?:Maintenance|Documentation|Internal)\*\*)$"
)
INTERNAL_DETAIL = re.compile(
    r"\b(?:ci|ci/cd|workflow(?:s)?|release automation|internal guidelines?|tests?|"
    r"commits?|pull requests?|individual files?)\b",
    re.IGNORECASE,
)


def validate_release_notes(content: str) -> None:
    """Raise ``ValueError`` when release-note content violates the output contract."""
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

    first_line = notes.splitlines()[0].strip()
    if not FIRST_LINE.fullmatch(first_line):
        raise ValueError("Release notes must start with a release section or fallback label.")
    if re.search(r"(?m)^# (?!#)", notes):
        raise ValueError("Release notes must not contain a title heading.")

    if first_line.startswith("**"):
        paragraphs = [paragraph for paragraph in notes.split("\n\n") if paragraph.strip()]
        if len(paragraphs) != 2:
            raise ValueError("Fallback release notes must contain one label and one paragraph.")
        if "\n## " in notes:
            raise ValueError("Fallback release notes must not contain additional sections.")
        if INTERNAL_DETAIL.search(notes):
            raise ValueError(
                "Fallback release notes contain maintainer-only implementation details."
            )


def main() -> int:
    """Validate one Markdown file from the command line."""
    if len(sys.argv) != 2:
        print(f"usage: {Path(sys.argv[0]).name} RELEASE_NOTES_MARKDOWN", file=sys.stderr)
        return 2

    try:
        validate_release_notes(Path(sys.argv[1]).read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        print(f"::error::{error}", file=sys.stderr)
        return 1

    print("Release-note Markdown validation passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
