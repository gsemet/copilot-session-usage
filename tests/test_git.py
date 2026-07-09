"""Unit tests for git.py — commit trailer injection."""

from __future__ import annotations

import subprocess

import pytest

from copilot_session_usage._internal import git


def _run_git(*args: str, cwd: str) -> str:
    proc = subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True)
    return proc.stdout


@pytest.fixture
def empty_repo(tmp_path):
    """Create a temporary git repository with one commit."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _run_git("init", cwd=str(repo))
    _run_git("config", "user.email", "test@example.com", cwd=str(repo))
    _run_git("config", "user.name", "Test User", cwd=str(repo))
    (repo / "file.txt").write_text("hello", encoding="utf-8")
    _run_git("add", "file.txt", cwd=str(repo))
    _run_git("commit", "-m", "initial commit", cwd=str(repo))
    return repo


def test_is_git_repository(empty_repo):
    assert git.is_git_repository(cwd=empty_repo) is True
    assert git.is_git_repository(cwd=empty_repo.parent) is False


def test_get_git_root(empty_repo):
    assert git.get_git_root(cwd=empty_repo) == empty_repo.resolve()


def test_get_head_commit_message(empty_repo):
    msg = git.get_head_commit_message(cwd=empty_repo)
    assert "initial commit" in msg


def test_amend_commit_with_trailers(empty_repo):
    trailers = [
        "Copilot-Session-Usage-Acc: moonshot_ai:Kimi K2.7 Code,in:4.123,out:1.213,cache:3.9",
    ]
    git.amend_commit_with_trailers(trailers, cwd=empty_repo)
    msg = git.get_head_commit_message(cwd=empty_repo)
    assert "initial commit" in msg
    assert (
        "Copilot-Session-Usage-Acc: moonshot_ai:Kimi K2.7 Code,in:4.123,out:1.213,cache:3.9" in msg
    )


def test_amend_commit_replaces_existing_trailers(empty_repo):
    git.amend_commit_with_trailers(
        ["Copilot-Session-Usage-Acc: old:model,in:1,out:1,cache:1,aic:0.1"],
        cwd=empty_repo,
    )
    git.amend_commit_with_trailers(
        ["Copilot-Session-Usage-Acc: new:model,in:2,out:2,cache:2,aic:0.2"],
        cwd=empty_repo,
    )
    msg = git.get_head_commit_message(cwd=empty_repo)
    assert "old:model" not in msg
    assert "new:model,in:2,out:2,cache:2,aic:0.2" in msg


def test_amend_commit_replaces_aic_trailer(empty_repo):
    git.amend_commit_with_trailers(
        [
            "Copilot-Session-Usage-Acc: a:b,in:1,out:1,cache:1,aic:0.1",
            "Copilot-Session-Usage-AIC: 1.23",
        ],
        cwd=empty_repo,
    )
    git.amend_commit_with_trailers(
        [
            "Copilot-Session-Usage-Acc: a:b,in:2,out:2,cache:2,aic:0.2",
            "Copilot-Session-Usage-AIC: 2.34",
        ],
        cwd=empty_repo,
    )
    msg = git.get_head_commit_message(cwd=empty_repo)
    assert "Copilot-Session-Usage-AIC: 2.34" in msg
    assert "Copilot-Session-Usage-AIC: 1.23" not in msg


def test_amend_commit_preserves_other_lines(empty_repo):
    _run_git(
        "commit", "--amend", "-m", "title\n\nbody line\nSigned-off-by: me", cwd=str(empty_repo)
    )
    git.amend_commit_with_trailers(
        ["Copilot-Session-Usage-Acc: a:b,in:1,out:1,cache:1"],
        cwd=empty_repo,
    )
    msg = git.get_head_commit_message(cwd=empty_repo)
    assert "title" in msg
    assert "body line" in msg
    assert "Signed-off-by: me" in msg
    assert "Copilot-Session-Usage-Acc: a:b,in:1,out:1,cache:1" in msg


def test_amend_commit_keeps_signed_off_by_last(empty_repo):
    _run_git(
        "commit",
        "--amend",
        "-m",
        "title\n\nbody\nSigned-off-by: Alice <a@example.com>",
        cwd=str(empty_repo),
    )
    git.amend_commit_with_trailers(
        [
            "Copilot-Session-Usage-Acc: openai:gpt-4o,in:1,out:1,cache:1",
            "Copilot-Session-Usage-Acc: anthropic:claude,in:2,out:2,cache:2",
        ],
        cwd=empty_repo,
    )
    msg = git.get_head_commit_message(cwd=empty_repo)
    lines = msg.rstrip().splitlines()
    assert lines[-1] == "Signed-off-by: Alice <a@example.com>"
    assert "Copilot-Session-Usage-Acc: openai:gpt-4o,in:1,out:1,cache:1" in lines
    assert "Copilot-Session-Usage-Acc: anthropic:claude,in:2,out:2,cache:2" in lines


def test_amend_commit_replaces_copilot_trailers_keeps_sob(empty_repo):
    _run_git(
        "commit",
        "--amend",
        "-m",
        (
            "title\n\nCopilot-Session-Usage-Acc: old:a,in:1,out:1,cache:1\n"
            "Signed-off-by: Bob <b@example.com>"
        ),
        cwd=str(empty_repo),
    )
    git.amend_commit_with_trailers(
        ["Copilot-Session-Usage-Acc: new:a,in:9,out:9,cache:9"],
        cwd=empty_repo,
    )
    msg = git.get_head_commit_message(cwd=empty_repo)
    assert "old:a" not in msg
    assert "Copilot-Session-Usage-Acc: new:a,in:9,out:9,cache:9" in msg
    assert msg.rstrip().splitlines()[-1] == "Signed-off-by: Bob <b@example.com>"


def test_amend_commit_replaces_session_id_trailer(empty_repo):
    git.amend_commit_with_trailers(
        [
            "Copilot-Session-Usage-Session-ID: old-id",
            "Copilot-Session-Usage-Acc: a:b,in:1,out:1,cache:1,aic:0.1",
            "Copilot-Session-Usage-AIC: 1.23",
        ],
        cwd=empty_repo,
    )
    git.amend_commit_with_trailers(
        [
            "Copilot-Session-Usage-Session-ID: new-id",
            "Copilot-Session-Usage-Acc: a:b,in:2,out:2,cache:2,aic:0.2",
            "Copilot-Session-Usage-AIC: 2.34",
        ],
        cwd=empty_repo,
    )
    msg = git.get_head_commit_message(cwd=empty_repo)
    assert "Copilot-Session-Usage-Session-ID: new-id" in msg
    assert "Copilot-Session-Usage-Session-ID: old-id" not in msg
    assert "Copilot-Session-Usage-AIC: 2.34" in msg
    assert "Copilot-Session-Usage-AIC: 1.23" not in msg


def test_amend_commit_with_no_trailers_does_nothing(empty_repo):
    original = git.get_head_commit_message(cwd=empty_repo)
    git.amend_commit_with_trailers([], cwd=empty_repo)
    assert git.get_head_commit_message(cwd=empty_repo) == original
