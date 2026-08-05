"""Tests for the mechanical release-note output check."""

import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = (
    Path(__file__).parents[1]
    / ".github"
    / "skills"
    / "gh-release-notes"
    / "scripts"
    / "generate_release_notes.py"
)


def run_validator(tmp_path: Path, content: str) -> subprocess.CompletedProcess[str]:
    """Run the output check through the same entry point used by CI."""
    notes_path = tmp_path / "release-notes.md"
    notes_path.write_text(content, encoding="utf-8")
    return subprocess.run(
        [sys.executable, str(SCRIPT), "--validate", str(notes_path)],
        capture_output=True,
        text=True,
        check=False,
    )


def test_validate_accepts_skill_authored_markdown(tmp_path: Path) -> None:
    result = run_validator(
        tmp_path,
        """## Maintenance
This release contains maintenance and internal improvements. No user-facing behavior changed.
""",
    )

    assert result.returncode == 0, result.stderr


def test_validate_accepts_arbitrary_non_empty_markdown(tmp_path: Path) -> None:
    result = run_validator(tmp_path, "A skill-authored release note without a heading.")

    assert result.returncode == 0, result.stderr


def test_validate_does_not_rewrite_markdown(tmp_path: Path) -> None:
    content = "preamble\n\n## Whatever the skill chose\n\n- User-facing result.\n"
    result = run_validator(tmp_path, content)

    assert result.returncode == 0, result.stderr
    assert (tmp_path / "release-notes.md").read_text(encoding="utf-8") == content


def test_validate_rejects_empty_markdown(tmp_path: Path) -> None:
    result = run_validator(tmp_path, "\n")

    assert result.returncode == 1
    assert "empty" in result.stderr.lower()


def test_validate_rejects_missing_file(tmp_path: Path) -> None:
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--validate", str(tmp_path / "missing.md")],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 1
    assert "unable to read" in result.stderr.lower()


@pytest.mark.parametrize("content", ["", "\n", "   "])
def test_validate_rejects_whitespace_only_output(tmp_path: Path, content: str) -> None:
    result = run_validator(tmp_path, content)

    assert result.returncode == 1
