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

    release_notes = messages[-1]
    lowered = release_notes.lower()
    leaked_markers = [marker for marker in TRACE_MARKERS if marker.lower() in lowered]
    if leaked_markers:
        markers = ", ".join(sorted(leaked_markers))
        raise ValueError(f"Copilot assistant message contains trace markers: {markers}")

    if "```" in release_notes:
        raise ValueError("Copilot assistant message contains a code fence.")

    release_heading = (
        r"(?m)^(?:## |\*\*(?:New Features|Enhancements|Bug Fixes|"
        r"Breaking Changes|Examples|Documentation|Maintenance|Internal)\*\*)"
    )
    if not re.search(release_heading, release_notes):
        raise ValueError("Copilot assistant message does not look like release-note Markdown.")

    return release_notes + "\n"


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
