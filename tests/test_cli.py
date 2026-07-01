"""Unit tests for cli.py — Click CLI entry point."""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest
from click.testing import CliRunner

from copilot_session_usage.cli import cli


@pytest.fixture
def runner():
    return CliRunner()


@pytest.fixture
def sample_session_dir(tmp_path):
    """Create a temporary session directory with one JSONL file."""
    session_dir = tmp_path / "sess-abc"
    session_dir.mkdir()
    events = [
        json.dumps(
            {
                "ts": 1_000_000,
                "type": "llm_request",
                "attrs": {
                    "model": "gpt-4o",
                    "inputTokens": 1000,
                    "outputTokens": 100,
                    "cachedTokens": 0,
                },
            }
        ),
    ]
    (session_dir / "main.jsonl").write_text("\n".join(events) + "\n", encoding="utf-8")
    return session_dir


# ─── Top-level group ──────────────────────────────────────────────────────────


def test_cli_help(runner):
    result = runner.invoke(cli, ["--help"])
    assert result.exit_code == 0
    assert "analyze" in result.output
    assert "latest" in result.output
    assert "find" in result.output
    assert "id" in result.output
    assert "list" in result.output
    assert "batch" in result.output


def test_cli_agent_cli_raises(runner):
    result = runner.invoke(cli, ["--agent", "cli", "list"])
    assert result.exit_code != 0
    assert "not yet implemented" in result.output


# ─── analyze command ──────────────────────────────────────────────────────────


def test_analyze_command(runner, sample_session_dir):
    result = runner.invoke(cli, ["analyze", str(sample_session_dir)])
    assert result.exit_code == 0
    assert "gpt-4o" in result.output or "JSON" in result.output


def test_analyze_command_not_found(runner):
    result = runner.invoke(cli, ["analyze", "/nonexistent/path"])
    assert result.exit_code != 0
    assert "not found" in result.output


def test_analyze_command_json_output(runner, sample_session_dir):
    result = runner.invoke(cli, ["analyze", str(sample_session_dir), "--format", "json"])
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert "total" in data


def test_analyze_command_output_file(runner, sample_session_dir, tmp_path):
    out_file = tmp_path / "report.json"
    result = runner.invoke(
        cli, ["analyze", str(sample_session_dir), "--format", "json", "--output", str(out_file)]
    )
    assert result.exit_code == 0
    assert out_file.exists()
    data = json.loads(out_file.read_text())
    assert "total" in data


# ─── latest command ───────────────────────────────────────────────────────────


def test_latest_command(runner, sample_session_dir):
    with patch("copilot_session_usage._internal.vscode.find_latest_session_dir") as mock_find:
        mock_find.return_value = sample_session_dir
        result = runner.invoke(cli, ["latest"])
        assert result.exit_code == 0


def test_latest_command_not_found(runner):
    with patch("copilot_session_usage._internal.vscode.find_latest_session_dir") as mock_find:
        mock_find.return_value = None
        result = runner.invoke(cli, ["latest"])
        assert result.exit_code != 0
        assert "no session debug logs found" in result.output


def test_latest_command_with_workspace_filter(runner, sample_session_dir):
    with patch("copilot_session_usage._internal.vscode.find_latest_session_dir") as mock_find:
        mock_find.return_value = sample_session_dir
        result = runner.invoke(cli, ["latest", "--workspace", "/some/project"])
        assert result.exit_code == 0


# ─── find command ─────────────────────────────────────────────────────────────


def test_find_command_single_match(runner, sample_session_dir):
    with patch("copilot_session_usage._internal.vscode.find_sessions_by_title") as mock_find:
        mock_find.return_value = [
            {
                "session_id": "s1",
                "title": "Hello",
                "debug_log_dir": str(sample_session_dir),
                "created_ms": 1_000_000,
            }
        ]
        result = runner.invoke(cli, ["find", "hello"])
        assert result.exit_code == 0


def test_find_command_multiple_matches(runner):
    with patch("copilot_session_usage._internal.vscode.find_sessions_by_title") as mock_find:
        mock_find.return_value = [
            {
                "session_id": "s1",
                "title": "Hello",
                "debug_log_dir": "/tmp/fake1",
                "created_ms": 1_000_000,
            },
            {
                "session_id": "s2",
                "title": "Hello",
                "debug_log_dir": "/tmp/fake2",
                "created_ms": 2_000_000,
            },
        ]
        result = runner.invoke(cli, ["find", "hello"])
        assert result.exit_code == 1
        assert "Multiple sessions match" in result.output


def test_find_command_no_match(runner):
    with patch("copilot_session_usage._internal.vscode.find_sessions_by_title") as mock_find:
        mock_find.return_value = []
        result = runner.invoke(cli, ["find", "nonexistent"])
        assert result.exit_code != 0
        assert "no sessions found" in result.output


def test_find_command_missing_logs(runner):
    with patch("copilot_session_usage._internal.vscode.find_sessions_by_title") as mock_find:
        mock_find.return_value = [
            {
                "session_id": "s1",
                "title": "Hello",
                "debug_log_dir": "/nonexistent",
                "created_ms": 1_000_000,
            }
        ]
        result = runner.invoke(cli, ["find", "hello"])
        assert result.exit_code != 0
        assert "debug logs not present" in result.output


# ─── id command ───────────────────────────────────────────────────────────────


def test_id_command(runner, sample_session_dir):
    with patch("copilot_session_usage._internal.vscode.find_session_dir_by_id") as mock_find:
        mock_find.return_value = sample_session_dir
        result = runner.invoke(cli, ["id", "abc-123"])
        assert result.exit_code == 0


def test_id_command_not_found(runner):
    with patch("copilot_session_usage._internal.vscode.find_session_dir_by_id") as mock_find:
        mock_find.return_value = None
        result = runner.invoke(cli, ["id", "missing"])
        assert result.exit_code != 0
        assert "no debug logs found" in result.output


# ─── list command ─────────────────────────────────────────────────────────────


def test_list_command(runner):
    with patch("copilot_session_usage._internal.vscode.list_recent_sessions") as mock_list:
        mock_list.return_value = [
            {"session_id": "s1", "title": "Test"},
        ]
        result = runner.invoke(cli, ["list"])
        assert result.exit_code == 0
        assert "s1" in result.output or "Test" in result.output


def test_list_command_json(runner):
    with patch("copilot_session_usage._internal.vscode.list_recent_sessions") as mock_list:
        mock_list.return_value = []
        result = runner.invoke(cli, ["list", "--format", "json"])
        assert result.exit_code == 0
        assert json.loads(result.output) == []


def test_list_command_with_options(runner):
    with patch("copilot_session_usage._internal.vscode.list_recent_sessions") as mock_list:
        mock_list.return_value = []
        result = runner.invoke(
            cli, ["list", "--limit", "5", "--since", "2026-01-01", "--workspace", "/project"]
        )
        assert result.exit_code == 0


# ─── batch command ────────────────────────────────────────────────────────────


def test_batch_command(runner, sample_session_dir):
    with patch("copilot_session_usage._internal.vscode.list_recent_sessions") as mock_list:
        mock_list.return_value = [
            {"session_id": "s1", "title": "Test", "debug_log_dir": str(sample_session_dir)}
        ]
        result = runner.invoke(cli, ["batch", "1"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert "summary" in data
        assert "sessions" in data


def test_batch_command_empty(runner):
    with patch("copilot_session_usage._internal.vscode.list_recent_sessions") as mock_list:
        mock_list.return_value = []
        result = runner.invoke(cli, ["batch", "10"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["summary"]["session_count"] == 0


def test_batch_command_with_options(runner, sample_session_dir):
    with patch("copilot_session_usage._internal.vscode.list_recent_sessions") as mock_list:
        mock_list.return_value = [
            {"session_id": "s1", "title": "Test", "debug_log_dir": str(sample_session_dir)}
        ]
        result = runner.invoke(
            cli, ["batch", "1", "--since", "2026-01-01", "--workspace", "/project"]
        )
        assert result.exit_code == 0


# ─── resolve_ws_roots error path ──────────────────────────────────────────────


def test_list_command_no_workspace_storage(runner):
    with patch(
        "copilot_session_usage._internal.vscode.default_workspace_storage_roots"
    ) as mock_roots:
        mock_roots.return_value = []
        result = runner.invoke(cli, ["list"])
        assert result.exit_code != 0
        assert "No workspaceStorage directory found" in result.output
