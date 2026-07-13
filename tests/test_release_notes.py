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


def read_notes(tmp_path: Path) -> str:
    """Read the file after the validator has normalized it."""
    return (tmp_path / "release-notes.md").read_text(encoding="utf-8")


def test_validate_fallback_release_notes(tmp_path: Path) -> None:
    result = run_validator(
        tmp_path,
        """**Maintenance**

This release contains internal maintenance only. No user-facing behavior changed.
""",
    )
    assert result.returncode == 0, result.stderr
    assert read_notes(tmp_path).startswith("**Maintenance**\n\n")


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


def test_normalizes_title_and_preamble(tmp_path: Path) -> None:
    result = run_validator(
        tmp_path,
        """Here are the release notes:

# Release v0.6.3

## Bug Fixes
- Fixed a user-facing issue.
""",
    )
    assert result.returncode == 0, result.stderr
    assert read_notes(tmp_path).startswith("## Bug Fixes\n")


def test_normalizes_polluted_fallback_to_canonical_text(tmp_path: Path) -> None:
    result = run_validator(
        tmp_path,
        """**Maintenance**

This release improves the CI workflow and release automation.
""",
    )
    assert result.returncode == 0, result.stderr
    assert "CI" not in read_notes(tmp_path)
    assert "release automation" not in read_notes(tmp_path).lower()


@pytest.mark.parametrize(
    "content",
    [
        "",
        "Release notes without a recognized section.",
        "**Maintenance**\n\nOne paragraph.\n\nUnexpected second paragraph.",
        "## Bug Fixes\n```text\ntrace\n```",
        "**Internal**\n\n<function_call>read</function_call>",
    ],
)
def test_validate_rejects_invalid_release_notes(content: str, tmp_path: Path) -> None:
    result = run_validator(tmp_path, content)
    assert result.returncode == 1
