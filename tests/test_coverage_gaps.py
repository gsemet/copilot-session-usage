"""Tests for specific coverage gaps — CLI exception paths, api ref_dir, batch skip."""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest
from click.testing import CliRunner

from copilot_session_usage import api
from copilot_session_usage.cli import cli


@pytest.fixture
def runner():
    return CliRunner()


# ─── api.py load_pricing with ref_dir ─────────────────────────────────────────


def test_api_load_pricing_with_ref_dir(tmp_path):
    ref_dir = tmp_path / "refs"
    ref_dir.mkdir()
    std_yaml = ref_dir / "models-and-pricing.yml"
    std_yaml.write_text(
        "- model: 'GPT-5'\n  input: $1.00\n  output: $2.00\n  cached_input: $0.10\n",
        encoding="utf-8",
    )
    pricing = api.load_pricing(ref_dir)
    assert "gpt-5" in pricing.get("models", {})


# ─── cli.py batch command skip missing debug logs ─────────────────────────────


def test_batch_command_skips_missing_debug_logs(runner, tmp_path):
    """Batch should skip sessions whose debug_log_dir no longer exists."""
    session_dir = tmp_path / "sess-real"
    session_dir.mkdir()
    events = [
        json.dumps(
            {
                "ts": 1_000_000,
                "type": "llm_request",
                "attrs": {
                    "model": "gpt-4o",
                    "inputTokens": 100,
                    "outputTokens": 10,
                    "cachedTokens": 0,
                },
            }
        ),
    ]
    (session_dir / "main.jsonl").write_text("\n".join(events) + "\n", encoding="utf-8")

    with patch("copilot_session_usage._internal.vscode.list_recent_sessions") as mock_list:
        mock_list.return_value = [
            {"session_id": "s1", "title": "Real", "debug_log_dir": str(session_dir)},
            {"session_id": "s2", "title": "Missing", "debug_log_dir": "/nonexistent/path"},
        ]
        result = runner.invoke(cli, ["batch", "2"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["summary"]["session_count"] == 1
        assert len(data["sessions"]) == 1
        assert data["sessions"][0]["title"] == "Real"


# ─── cli.py find command sys.exit(1) via runner mix_stderr=False ──────────────


def test_find_command_multiple_matches_sys_exit(runner):
    """Force the sys.exit(1) branch in find_by_title to be traced."""
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
        # ClickRunner merges stderr into output by default
        assert "Multiple sessions match" in result.output
