"""Git operations for injecting session cost trailers into commits."""

from __future__ import annotations

from pathlib import Path

import git as gitpython


def _repo(cwd: Path | None = None) -> gitpython.Repo:
    """Return a GitPython Repo for cwd or the current directory."""
    return gitpython.Repo(str(cwd) if cwd else None, search_parent_directories=True)


def is_git_repository(cwd: Path | None = None) -> bool:
    """Return True if cwd (or the current directory) is inside a git repository."""
    try:
        _repo(cwd=cwd)
    except (gitpython.InvalidGitRepositoryError, gitpython.NoSuchPathError):
        return False
    return True


def get_head_commit_message(cwd: Path | None = None) -> str:
    """Return the current HEAD commit message body."""
    return str(_repo(cwd=cwd).head.commit.message)


def _is_trailer_line(line: str) -> bool:
    """Return True for lines that look like Git trailers (Key: value)."""
    if ":" not in line:
        return False
    key = line.split(":", 1)[0]
    return key.strip() != "" and " " not in key.strip()


def _split_final_trailers(lines: list[str]) -> tuple[list[str], list[str]]:
    """Split lines into body and the final trailer block.

    The final trailer block is the consecutive sequence of trailer-looking
    lines at the end of the message. The blank line that immediately precedes
    the block is treated as the separator and removed from the body.
    """
    # Git normalizes commit messages with trailing blank lines; strip them
    # before locating the trailer block.
    while lines and lines[-1].strip() == "":
        lines.pop()

    # Collect consecutive trailer-looking lines from the end.
    trailer_block: list[str] = []
    for line in reversed(lines):
        if _is_trailer_line(line):
            trailer_block.insert(0, line)
        else:
            break

    if not trailer_block:
        return lines, []

    body_end = len(lines) - len(trailer_block)
    # Drop the single blank line that separates the body from the trailer block.
    if body_end > 0 and lines[body_end - 1].strip() == "":
        body_end -= 1

    return lines[:body_end], trailer_block


def amend_commit_with_trailers(trailers: list[str], cwd: Path | None = None) -> None:
    """Amend HEAD by appending trailer lines to the commit message.

    Existing trailers with the same keys (``Copilot-Session-Usage-Acc``,
    ``Copilot-Session-Usage-AIC``, or ``Copilot-Session-Usage-Session-ID``)
    are replaced; all other lines are preserved. ``Signed-off-by`` and other
    conventional Git trailers are kept at the very end of the message, after
    the injected cost trailers. The commit is amended in-place without
    changing the tree.
    """
    if not trailers:
        return

    repo = _repo(cwd=cwd)
    message = get_head_commit_message(cwd=cwd)
    lines = message.splitlines()

    # Remove any existing Copilot session-usage trailers so values are always
    # fresh (accumulated, not appended).
    copilot_keys = (
        "Copilot-Session-Usage-Acc:",
        "Copilot-Session-Usage-AIC:",
        "Copilot-Session-Usage-Session-ID:",
    )
    lines = [line for line in lines if not line.startswith(copilot_keys)]

    body, final_trailers = _split_final_trailers(lines)

    # Ensure a single trailing blank line after the body so the trailer block
    # is recognized as trailers by Git.
    while body and body[-1].strip() == "":
        body.pop()

    new_message_lines = list(body)
    new_message_lines.append("")
    new_message_lines.extend(trailers)
    new_message_lines.extend(final_trailers)

    new_message = "\n".join(new_message_lines)
    repo.git.commit("--amend", "-m", new_message)


def get_git_root(cwd: Path | None = None) -> Path:
    """Return the root path of the current git repository."""
    repo = _repo(cwd=cwd)
    working_tree = repo.working_tree_dir
    if working_tree is None:
        msg = "repository has no working tree"
        raise RuntimeError(msg)
    return Path(working_tree)


def resolve_repository_path(path: str | None = None) -> Path:
    """Return the git repository root for an optional path override."""
    cwd = Path(path) if path else None
    if cwd is not None and not cwd.exists():
        msg = f"path not found: {cwd}"
        raise FileNotFoundError(msg)
    return get_git_root(cwd=cwd)
