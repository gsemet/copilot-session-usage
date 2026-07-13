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


def main() -> int:
    """Validate one Markdown file from the command line."""
    if len(sys.argv) != 2:
        print(f"usage: {Path(sys.argv[0]).name} RELEASE_NOTES_MARKDOWN", file=sys.stderr)
        return 2

    try:
        output_path = Path(sys.argv[1])
        normalized = normalize_release_notes(output_path.read_text(encoding="utf-8"))
        validate_release_notes(normalized)
        output_path.write_text(normalized, encoding="utf-8")
    except (OSError, ValueError) as error:
        print(f"::error::{error}", file=sys.stderr)
        return 1

    print("Release-note Markdown validation passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
