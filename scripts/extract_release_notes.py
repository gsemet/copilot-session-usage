#!/usr/bin/env python3
"""Extract the final assistant message from Copilot CLI JSONL output."""

from __future__ import annotations

import json
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
RELEASE_HEADING = re.compile(
    r"(?m)^(?:## (?:New Features|Enhancements|Bug Fixes|Breaking Changes|"
    r"Examples|Documentation|Maintenance|Internal)|\*\*(?:Maintenance|"
    r"Documentation|Internal)\*\*)\s*$"
)
FALLBACK_HEADING = re.compile(r"^## (Maintenance|Documentation|Internal)$")


def _trace_positions(content: str) -> list[int]:
    """Return case-insensitive positions of known transcript markers."""
    lowered = content.lower()
    return [position for marker in TRACE_MARKERS for position in _find_all(lowered, marker.lower())]


def _find_all(content: str, needle: str) -> list[int]:
    """Return every position of a substring in content."""
    positions: list[int] = []
    start = 0
    while (position := content.find(needle, start)) != -1:
        positions.append(position)
        start = position + 1
    return positions


def _extract_release_block(content: str) -> str | None:
    """Extract a clean release block, ignoring an embedded transcript prefix."""
    headings = list(RELEASE_HEADING.finditer(content))
    if not headings:
        return None

    markers = _trace_positions(content)
    start_after = max(markers, default=-1)
    heading = next((match for match in headings if match.start() > start_after), None)
    if heading is None:
        return None

    release_notes = content[heading.start() :].strip()
    lowered = release_notes.lower()
    leaked_markers = [marker for marker in TRACE_MARKERS if marker.lower() in lowered]
    if leaked_markers or "```" in release_notes:
        return None

    first_line, separator, remainder = release_notes.partition("\n")
    fallback_heading = FALLBACK_HEADING.fullmatch(first_line)
    if fallback_heading:
        release_notes = f"**{fallback_heading.group(1)}**{separator}{remainder}"
    return release_notes


def extract_final_message(raw_output: str) -> str:
    """Return the last non-empty assistant message from a Copilot JSONL stream."""
    messages: list[str] = []

    for line_number, line in enumerate(raw_output.splitlines(), start=1):
        if not line.strip():
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError as error:
            raise ValueError(f"Invalid Copilot JSONL at line {line_number}: {error}") from error

        if event.get("type") != "assistant.message":
            continue
        content = event.get("data", {}).get("content")
        if isinstance(content, str) and content.strip():
            messages.append(content.strip())

    if not messages:
        raise ValueError("Copilot output did not contain an assistant message.")

    for message in reversed(messages):
        release_notes = _extract_release_block(message)
        if release_notes is not None:
            return release_notes + "\n"

    raise ValueError("Copilot output did not contain a clean release-note block.")


def main() -> int:
    if len(sys.argv) != 3:
        print(f"usage: {Path(sys.argv[0]).name} INPUT_JSONL OUTPUT_MARKDOWN", file=sys.stderr)
        return 2

    input_path = Path(sys.argv[1])
    output_path = Path(sys.argv[2])

    try:
        release_notes = extract_final_message(input_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        print(f"::error::{error}", file=sys.stderr)
        return 1

    output_path.write_text(release_notes, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
