"""Tests for release-note output validation."""

import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).parents[1] / "scripts" / "validate_release_notes.py"


def run_validator(tmp_path: Path, content: str) -> subprocess.CompletedProcess[str]:
    """Run the validator through the same entry point used by CI."""
    notes_path = tmp_path / "release-notes.md"
    notes_path.write_text(content, encoding="utf-8")
    return subprocess.run(
        [sys.executable, str(SCRIPT), str(notes_path)],
        capture_output=True,
        text=True,
        check=False,
    )


def test_validate_fallback_release_notes(tmp_path: Path) -> None:
    result = run_validator(
        tmp_path,
        """**Maintenance**

This release contains internal maintenance only. No user-facing behavior changed.
""",
    )
    assert result.returncode == 0, result.stderr


def test_validate_product_release_notes(tmp_path: Path) -> None:
    result = run_validator(
        tmp_path,
        """## Bug Fixes
- Fixed failures when loading a session with no model events.

## Documentation
- Added upgrade guidance for the new command.
""",
    )
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize(
    "content",
    [
        "",
        "Release notes for v0.6.3\n\n## Bug Fixes\n- Fixed a bug.",
        "# Release v0.6.3\n\n## Bug Fixes\n- Fixed a bug.",
        "**Maintenance**\n\nOne paragraph.\n\nUnexpected second paragraph.",
        "## Bug Fixes\n```text\ntrace\n```",
        "**Internal**\n\n<function_call>read</function_call>",
        "**Maintenance**\n\nThis workflow only changes CI automation.",
    ],
)
def test_validate_rejects_invalid_release_notes(content: str, tmp_path: Path) -> None:
    result = run_validator(tmp_path, content)
    assert result.returncode == 1
