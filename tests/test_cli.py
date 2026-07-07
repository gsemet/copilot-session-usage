"""Unit tests for cli.py — Click CLI entry point."""

from __future__ import annotations

import json

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
                "ts": 500,
                "type": "user_message",
                "attrs": {"content": "/my-skill"},
            }
        ),
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
        json.dumps(
            {
                "ts": 1_000_000,
                "type": "tool_call",
                "name": "read_file",
                "attrs": {},
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


def test_latest_command(runner, sample_session_dir, mocker):
    mock_find = mocker.patch("copilot_session_usage._internal.vscode.find_latest_session_dir")
    mock_meta = mocker.patch("copilot_session_usage._internal.vscode.find_session_metadata_by_id")
    mock_find.return_value = sample_session_dir
    mock_meta.return_value = {"session_id": "sess-abc", "title": "Latest Title"}
    result = runner.invoke(cli, ["latest"])
    assert result.exit_code == 0
    assert "Latest Title" in result.output


def test_latest_command_not_found(runner, mocker):
    mock_find = mocker.patch("copilot_session_usage._internal.vscode.find_latest_session_dir")
    mock_find.return_value = None
    result = runner.invoke(cli, ["latest"])
    assert result.exit_code != 0
    assert "no session debug logs found" in result.output


def test_latest_command_with_workspace_filter(runner, sample_session_dir, mocker):
    mock_find = mocker.patch("copilot_session_usage._internal.vscode.find_latest_session_dir")
    mock_meta = mocker.patch("copilot_session_usage._internal.vscode.find_session_metadata_by_id")
    mock_find.return_value = sample_session_dir
    mock_meta.return_value = {"session_id": "sess-abc", "title": "Filtered Title"}
    result = runner.invoke(cli, ["latest", "--workspace", "/some/project"])
    assert result.exit_code == 0
    assert "Filtered Title" in result.output


# ─── find command ─────────────────────────────────────────────────────────────


def test_find_command_single_match(runner, sample_session_dir, mocker):
    mock_find = mocker.patch("copilot_session_usage._internal.vscode.find_sessions_by_title")
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


def test_find_command_multiple_matches(runner, mocker):
    mock_find = mocker.patch("copilot_session_usage._internal.vscode.find_sessions_by_title")
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


def test_find_command_no_match(runner, mocker):
    mock_find = mocker.patch("copilot_session_usage._internal.vscode.find_sessions_by_title")
    mock_find.return_value = []
    result = runner.invoke(cli, ["find", "nonexistent"])
    assert result.exit_code != 0
    assert "no sessions found" in result.output


def test_find_command_missing_logs(runner, mocker):
    mock_find = mocker.patch("copilot_session_usage._internal.vscode.find_sessions_by_title")
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


def test_id_command(runner, sample_session_dir, mocker):
    mock_find = mocker.patch("copilot_session_usage._internal.vscode.find_session_dir_by_id")
    mock_meta = mocker.patch("copilot_session_usage._internal.vscode.find_session_metadata_by_id")
    mock_find.return_value = sample_session_dir
    mock_meta.return_value = {"session_id": "abc-123", "title": "My Title"}
    result = runner.invoke(cli, ["id", "abc-123"])
    assert result.exit_code == 0
    assert "My Title" in result.output


def test_id_command_not_found(runner, mocker):
    mock_find = mocker.patch("copilot_session_usage._internal.vscode.find_session_dir_by_id")
    mock_find.return_value = None
    result = runner.invoke(cli, ["id", "missing"])
    assert result.exit_code != 0
    assert "no debug logs found" in result.output


# ─── list command ─────────────────────────────────────────────────────────────


def test_list_command(runner, mocker):
    mock_list = mocker.patch("copilot_session_usage._internal.vscode.list_recent_sessions")
    mock_list.return_value = [
        {"session_id": "s1", "title": "Test"},
    ]
    result = runner.invoke(cli, ["list"])
    assert result.exit_code == 0
    assert "s1" in result.output or "Test" in result.output


def test_list_command_json(runner, mocker):
    mock_list = mocker.patch("copilot_session_usage._internal.vscode.list_recent_sessions")
    mock_list.return_value = []
    result = runner.invoke(cli, ["list", "--format", "json"])
    assert result.exit_code == 0
    assert json.loads(result.output) == []


def test_list_command_with_options(runner, mocker):
    mock_list = mocker.patch("copilot_session_usage._internal.vscode.list_recent_sessions")
    mock_list.return_value = []
    result = runner.invoke(
        cli, ["list", "--limit", "5", "--since", "2026-01-01", "--workspace", "/project"]
    )
    assert result.exit_code == 0


# ─── batch command ────────────────────────────────────────────────────────────


def test_batch_command(runner, sample_session_dir, mocker):
    mock_list = mocker.patch("copilot_session_usage._internal.vscode.list_recent_sessions")
    mock_list.return_value = [
        {"session_id": "s1", "title": "Test", "debug_log_dir": str(sample_session_dir)}
    ]
    result = runner.invoke(cli, ["batch", "1"])
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert "summary" in data
    assert "sessions" in data


def test_batch_command_empty(runner, mocker):
    mock_list = mocker.patch("copilot_session_usage._internal.vscode.list_recent_sessions")
    mock_list.return_value = []
    result = runner.invoke(cli, ["batch", "10"])
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["summary"]["session_count"] == 0


def test_batch_command_with_options(runner, sample_session_dir, mocker):
    mock_list = mocker.patch("copilot_session_usage._internal.vscode.list_recent_sessions")
    mock_list.return_value = [
        {"session_id": "s1", "title": "Test", "debug_log_dir": str(sample_session_dir)}
    ]
    result = runner.invoke(cli, ["batch", "1", "--since", "2026-01-01", "--workspace", "/project"])
    assert result.exit_code == 0


# ─── resolve_ws_roots error path ──────────────────────────────────────────────


def test_list_command_no_workspace_storage(runner, mocker):
    mock_roots = mocker.patch(
        "copilot_session_usage._internal.vscode.default_workspace_storage_roots"
    )
    mock_roots.return_value = []
    result = runner.invoke(cli, ["list"])
    assert result.exit_code != 0
    assert "No workspaceStorage directory found" in result.output


# ─── analyze command: new options ─────────────────────────────────────────────


def test_analyze_command_summary(runner, sample_session_dir):
    result = runner.invoke(
        cli, ["analyze", str(sample_session_dir), "--summary", "--format", "table"]
    )
    assert result.exit_code == 0
    assert "Cache ratio" in result.output
    assert "Cost per 1M tokens" in result.output


def test_analyze_command_query(runner, sample_session_dir):
    result = runner.invoke(
        cli, ["analyze", str(sample_session_dir), "--query", ".total.estimated_usd"]
    )
    assert result.exit_code == 0
    # The value is a small number; just ensure it printed a number.
    assert any(ch.isdigit() for ch in result.output)


def test_analyze_command_query_help(runner):
    result = runner.invoke(cli, ["analyze", "--query-help"])
    assert result.exit_code == 0
    assert "Queryable fields" in result.output
    assert "total.estimated_usd" in result.output


def test_analyze_command_name_filter_aggregate(runner, sample_session_dir, mocker):
    mock_list = mocker.patch("copilot_session_usage._internal.vscode.list_recent_sessions")
    mock_list.return_value = [
        {
            "session_id": "s1",
            "title": "PRD: /path/to/prd",
            "debug_log_dir": str(sample_session_dir),
            "created_ms": 1_000_000,
        }
    ]
    result = runner.invoke(
        cli,
        ["analyze", "--name", r"PRD:.*/path/to/prd", "--aggregate", "--format", "table"],
    )
    assert result.exit_code == 0
    assert "Aggregate across 1 sessions" in result.output


def test_analyze_command_name_filter_summary(runner, sample_session_dir, mocker):
    mock_list = mocker.patch("copilot_session_usage._internal.vscode.list_recent_sessions")
    mock_list.return_value = [
        {
            "session_id": "s1",
            "title": "PRD: /path/to/prd",
            "debug_log_dir": str(sample_session_dir),
            "created_ms": 1_000_000,
        }
    ]
    result = runner.invoke(cli, ["analyze", "--name", r"PRD", "--summary", "--format", "table"])
    assert result.exit_code == 0
    assert "Cache ratio" in result.output


def test_analyze_command_name_and_path_mutually_exclusive(runner, sample_session_dir):
    result = runner.invoke(cli, ["analyze", str(sample_session_dir), "--name", "PRD"])
    assert result.exit_code != 0
    assert "either PATH or --name" in result.output


def test_analyze_command_requires_path_or_name(runner):
    result = runner.invoke(cli, ["analyze"])
    assert result.exit_code != 0
    assert "PATH or --name" in result.output


def test_analyze_command_invalid_name_regex(runner, mocker):
    mock_list = mocker.patch("copilot_session_usage._internal.vscode.list_recent_sessions")
    mock_list.return_value = []
    result = runner.invoke(cli, ["analyze", "--name", "[invalid"])
    assert result.exit_code != 0
    assert "Invalid name regex" in result.output


def test_analyze_command_name_no_matches(runner, mocker):
    mock_list = mocker.patch("copilot_session_usage._internal.vscode.list_recent_sessions")
    mock_list.return_value = [
        {
            "session_id": "s1",
            "title": "Other",
            "debug_log_dir": "/tmp/fake",
            "created_ms": 1_000_000,
        }
    ]
    result = runner.invoke(cli, ["analyze", "--name", "PRD"])
    assert result.exit_code != 0
    assert "no sessions matched" in result.output


def test_analyze_command_since_until(runner, sample_session_dir, mocker):
    mock_list = mocker.patch("copilot_session_usage._internal.vscode.list_recent_sessions")
    mock_list.return_value = [
        {
            "session_id": "s1",
            "title": "PRD",
            "debug_log_dir": str(sample_session_dir),
            "created_ms": 1_782_864_000_000,
        }
    ]
    result = runner.invoke(
        cli,
        [
            "analyze",
            "--name",
            "PRD",
            "--since",
            "2026-06-01T00:00:00Z",
            "--until",
            "2026-08-01T00:00:00+00:00",
        ],
    )
    assert result.exit_code == 0


# ─── list command: new options ────────────────────────────────────────────────


def test_list_command_dir_with_costs(runner, sample_session_dir, tmp_path):
    debug_dir = tmp_path / "debug-logs"
    debug_dir.mkdir()
    session_dir = debug_dir / sample_session_dir.name
    session_dir.mkdir()
    (session_dir / "main.jsonl").write_text(
        (sample_session_dir / "main.jsonl").read_text(), encoding="utf-8"
    )
    result = runner.invoke(cli, ["list", "--dir", str(debug_dir), "--format", "table"])
    assert result.exit_code == 0
    assert sample_session_dir.name in result.output
    assert "Tokens" in result.output
    assert "Cost" in result.output


def test_list_command_dir_not_found(runner):
    result = runner.invoke(cli, ["list", "--dir", "/nonexistent/dir"])
    assert result.exit_code != 0
    assert "directory not found" in result.output


def test_list_command_costs_from_workspace(runner, sample_session_dir, mocker):
    mock_list = mocker.patch("copilot_session_usage._internal.vscode.list_recent_sessions")
    mock_list.return_value = [
        {"session_id": "s1", "title": "Test", "debug_log_dir": str(sample_session_dir)}
    ]
    result = runner.invoke(cli, ["list", "--costs", "--format", "table"])
    assert result.exit_code == 0
    assert "Tokens" in result.output
    assert "Cost" in result.output


def test_list_command_name_filter(runner, mocker):
    mock_list = mocker.patch("copilot_session_usage._internal.vscode.list_recent_sessions")
    mock_list.return_value = [
        {"session_id": "s1", "title": "PRD design", "debug_log_dir": "/tmp/fake"},
        {"session_id": "s2", "title": "Other", "debug_log_dir": "/tmp/fake2"},
    ]
    result = runner.invoke(cli, ["list", "--name", r"PRD"])
    assert result.exit_code == 0
    assert "PRD design" in result.output
    assert "Other" not in result.output


def test_list_command_until(runner, mocker):
    mock_list = mocker.patch("copilot_session_usage._internal.vscode.list_recent_sessions")
    mock_list.return_value = [
        {
            "session_id": "old",
            "title": "Old",
            "debug_log_dir": "/tmp/fake",
            "created_ms": 1_000_000,
        },
        {
            "session_id": "new",
            "title": "New",
            "debug_log_dir": "/tmp/fake2",
            "created_ms": 2_000_000_000_000,
        },
    ]
    result = runner.invoke(cli, ["list", "--until", "2026-07-01T00:00:00Z"])
    assert result.exit_code == 0
    assert "Old" in result.output
    assert "New" not in result.output


# ─── batch command: new options ───────────────────────────────────────────────


def test_batch_command_name_filter(runner, sample_session_dir, mocker):
    mock_list = mocker.patch("copilot_session_usage._internal.vscode.list_recent_sessions")
    mock_list.return_value = [
        {"session_id": "s1", "title": "PRD", "debug_log_dir": str(sample_session_dir)},
        {"session_id": "s2", "title": "Other", "debug_log_dir": str(sample_session_dir)},
    ]
    result = runner.invoke(cli, ["batch", "10", "--name", r"PRD"])
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["summary"]["session_count"] == 1


def test_batch_command_until(runner, sample_session_dir, mocker):
    mock_list = mocker.patch("copilot_session_usage._internal.vscode.list_recent_sessions")
    mock_list.return_value = [
        {
            "session_id": "s1",
            "title": "Old",
            "debug_log_dir": str(sample_session_dir),
            "created_ms": 1_000_000,
        },
        {
            "session_id": "s2",
            "title": "New",
            "debug_log_dir": str(sample_session_dir),
            "created_ms": 2_000_000_000_000,
        },
    ]
    result = runner.invoke(cli, ["batch", "10", "--until", "2026-07-01T00:00:00Z"])
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["summary"]["session_count"] == 1


# ─── Skill-aware options ──────────────────────────────────────────────────────


def test_id_command_skill_breakdown(runner, sample_session_dir, mocker):
    mock_find = mocker.patch("copilot_session_usage._internal.vscode.find_session_dir_by_id")
    mock_meta = mocker.patch("copilot_session_usage._internal.vscode.find_session_metadata_by_id")
    mock_find.return_value = sample_session_dir
    mock_meta.return_value = {"session_id": "abc-123", "title": "My Title"}
    result = runner.invoke(cli, ["id", "abc-123", "--skill-breakdown", "--format", "table"])
    assert result.exit_code == 0
    assert "Per-Skill Breakdown" in result.output


def test_id_command_tool_breakdown(runner, sample_session_dir, mocker):
    mock_find = mocker.patch("copilot_session_usage._internal.vscode.find_session_dir_by_id")
    mock_meta = mocker.patch("copilot_session_usage._internal.vscode.find_session_metadata_by_id")
    mock_find.return_value = sample_session_dir
    mock_meta.return_value = {"session_id": "abc-123", "title": "My Title"}
    result = runner.invoke(cli, ["id", "abc-123", "--tool-breakdown", "--format", "table"])
    assert result.exit_code == 0
    assert "Tool Breakdown" in result.output


def test_id_command_skill_filter(runner, sample_session_dir, mocker):
    mock_find = mocker.patch("copilot_session_usage._internal.vscode.find_session_dir_by_id")
    mock_meta = mocker.patch("copilot_session_usage._internal.vscode.find_session_metadata_by_id")
    mock_find.return_value = sample_session_dir
    mock_meta.return_value = {"session_id": "abc-123", "title": "My Title"}
    result = runner.invoke(
        cli, ["id", "abc-123", "--skill", "/my-skill", "--format", "json", "--detail", "minimal"]
    )
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["skill"] == "/my-skill"


def test_analyze_command_title_filter(runner, sample_session_dir, mocker):
    mock_list = mocker.patch("copilot_session_usage._internal.vscode.list_recent_sessions")
    mock_list.return_value = [
        {
            "session_id": "s1",
            "title": "get-session-costs review",
            "debug_log_dir": str(sample_session_dir),
            "created_ms": 1_000_000,
        }
    ]
    result = runner.invoke(
        cli, ["analyze", "--title", "get-session-costs", "--latest", "--format", "table"]
    )
    assert result.exit_code == 0
    assert "get-session-costs review" in result.output


def test_list_command_title_filter(runner, mocker):
    mock_list = mocker.patch("copilot_session_usage._internal.vscode.list_recent_sessions")
    mock_list.return_value = [
        {"session_id": "s1", "title": "get-session-costs review"},
        {"session_id": "s2", "title": "Other"},
    ]
    result = runner.invoke(cli, ["list", "--title", "get-session-costs"])
    assert result.exit_code == 0
    assert "get-session-costs review" in result.output
    assert "Other" not in result.output


def test_skills_command(runner, sample_session_dir, mocker):
    mock_list = mocker.patch("copilot_session_usage._internal.vscode.list_recent_sessions")
    mock_list.return_value = [
        {"session_id": "s1", "title": "Test", "debug_log_dir": str(sample_session_dir)}
    ]
    result = runner.invoke(cli, ["skills", "--format", "table"])
    assert result.exit_code == 0
    assert "Skills across" in result.output
