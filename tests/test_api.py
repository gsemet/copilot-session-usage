"""Unit tests for api.py — public Python API."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from copilot_session_usage import api

# ─── Fixtures ─────────────────────────────────────────────────────────────────


@pytest.fixture
def mock_pricing():
    return {
        "models": {
            "gpt-4o": [
                {"input_per_m": 0.25, "output_per_m": 1.00, "cache_per_m": 0.025, "tier": "Default"}
            ],
            "default": [
                {"input_per_m": 0.30, "output_per_m": 1.50, "cache_per_m": 0.030, "tier": "Default"}
            ],
        }
    }


@pytest.fixture
def sample_session_dir(tmp_path, mock_pricing):
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


# ─── analyze_session ──────────────────────────────────────────────────────────


def test_analyze_session_returns_dict(sample_session_dir):
    result = api.analyze_session(sample_session_dir)
    assert isinstance(result, dict)
    assert "total" in result
    assert result["total"]["llm_calls"] == 1


def test_analyze_session_detail_levels(sample_session_dir):
    minimal = api.analyze_session(sample_session_dir, detail="minimal")
    compact = api.analyze_session(sample_session_dir, detail="compact")
    full = api.analyze_session(sample_session_dir, detail="full")
    assert "model_breakdown" not in minimal
    assert "model_breakdown" not in compact
    assert "model_breakdown" in full


def test_analyze_session_agent_cli_raises():
    with pytest.raises(NotImplementedError):
        api.analyze_session(Path("/tmp/fake"), agent="cli")


# ─── list_sessions ────────────────────────────────────────────────────────────


def test_list_sessions_returns_list():
    with patch(
        "copilot_session_usage._internal.vscode.default_workspace_storage_roots"
    ) as mock_roots:
        mock_roots.return_value = []
        result = api.list_sessions()
        assert result == []


def test_list_sessions_with_workspace_roots():
    with patch("copilot_session_usage._internal.vscode.list_recent_sessions") as mock_list:
        mock_list.return_value = [{"session_id": "s1", "title": "Test"}]
        result = api.list_sessions(workspace_roots=[Path("/fake")])
        assert len(result) == 1
        assert result[0]["session_id"] == "s1"


def test_list_sessions_agent_cli_raises():
    with pytest.raises(NotImplementedError):
        api.list_sessions(agent="cli")


def test_list_sessions_with_since():
    with patch("copilot_session_usage._internal.vscode.list_recent_sessions") as mock_list:
        mock_list.return_value = []
        result = api.list_sessions(since="2026-01-01")
        assert result == []


# ─── find_sessions_by_title ───────────────────────────────────────────────────


def test_find_sessions_by_title():
    with (
        patch(
            "copilot_session_usage._internal.vscode.default_workspace_storage_roots"
        ) as mock_roots,
        patch("copilot_session_usage._internal.vscode.find_sessions_by_title") as mock_find,
    ):
        mock_roots.return_value = [Path("/fake")]
        mock_find.return_value = [{"session_id": "s1", "title": "Hello"}]
        result = api.find_sessions_by_title("hello")
        assert len(result) == 1
        assert result[0]["title"] == "Hello"


def test_find_sessions_by_title_agent_cli_raises():
    with pytest.raises(NotImplementedError):
        api.find_sessions_by_title("test", agent="cli")


# ─── find_session_by_id ───────────────────────────────────────────────────────


def test_find_session_by_id_found(sample_session_dir):
    with (
        patch(
            "copilot_session_usage._internal.vscode.default_workspace_storage_roots"
        ) as mock_roots,
        patch("copilot_session_usage._internal.vscode.find_session_dir_by_id") as mock_find,
    ):
        mock_roots.return_value = [Path("/fake")]
        mock_find.return_value = sample_session_dir
        result = api.find_session_by_id("abc-123")
        assert result is not None
        assert result["total"]["llm_calls"] == 1


def test_find_session_by_id_not_found():
    with (
        patch(
            "copilot_session_usage._internal.vscode.default_workspace_storage_roots"
        ) as mock_roots,
        patch("copilot_session_usage._internal.vscode.find_session_dir_by_id") as mock_find,
    ):
        mock_roots.return_value = [Path("/fake")]
        mock_find.return_value = None
        result = api.find_session_by_id("missing")
        assert result is None


def test_find_session_by_id_agent_cli_raises():
    with pytest.raises(NotImplementedError):
        api.find_session_by_id("abc", agent="cli")


# ─── analyze_latest ───────────────────────────────────────────────────────────


def test_analyze_latest_found(sample_session_dir):
    with (
        patch(
            "copilot_session_usage._internal.vscode.default_workspace_storage_roots"
        ) as mock_roots,
        patch("copilot_session_usage._internal.vscode.find_latest_session_dir") as mock_find,
    ):
        mock_roots.return_value = [Path("/fake")]
        mock_find.return_value = sample_session_dir
        result = api.analyze_latest()
        assert result["total"]["llm_calls"] == 1


def test_analyze_latest_not_found():
    with (
        patch(
            "copilot_session_usage._internal.vscode.default_workspace_storage_roots"
        ) as mock_roots,
        patch("copilot_session_usage._internal.vscode.find_latest_session_dir") as mock_find,
    ):
        mock_roots.return_value = [Path("/fake")]
        mock_find.return_value = None
        with pytest.raises(ValueError, match="No session debug logs found"):
            api.analyze_latest()


def test_analyze_latest_agent_cli_raises():
    with pytest.raises(NotImplementedError):
        api.analyze_latest(agent="cli")


# ─── batch_analyze ────────────────────────────────────────────────────────────


def test_batch_analyze(sample_session_dir):
    with (
        patch(
            "copilot_session_usage._internal.vscode.default_workspace_storage_roots"
        ) as mock_roots,
        patch("copilot_session_usage._internal.vscode.list_recent_sessions") as mock_list,
    ):
        mock_roots.return_value = [Path("/fake")]
        mock_list.return_value = [
            {"session_id": "s1", "title": "Test", "debug_log_dir": str(sample_session_dir)}
        ]
        result = api.batch_analyze(1)
        assert "summary" in result
        assert "sessions" in result
        assert result["summary"]["session_count"] == 1


def test_batch_analyze_empty():
    with (
        patch(
            "copilot_session_usage._internal.vscode.default_workspace_storage_roots"
        ) as mock_roots,
        patch("copilot_session_usage._internal.vscode.list_recent_sessions") as mock_list,
    ):
        mock_roots.return_value = [Path("/fake")]
        mock_list.return_value = []
        result = api.batch_analyze(10)
        assert result["summary"]["session_count"] == 0
        assert result["sessions"] == []


def test_batch_analyze_agent_cli_raises():
    with pytest.raises(NotImplementedError):
        api.batch_analyze(5, agent="cli")


# ─── load_pricing ─────────────────────────────────────────────────────────────


def test_load_pricing_returns_dict():
    result = api.load_pricing()
    assert isinstance(result, dict)
    assert "models" in result
