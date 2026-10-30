"""Unit tests for api.py — public Python API."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from copilot_session_usage import api

# ─── Fixtures ─────────────────────────────────────────────────────────────────


@pytest.fixture
def mock_pricing():
    return {
        "models": {
            "claude-sonnet-4.6": [
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
                    "model": "claude-sonnet-4.6",
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


def test_analyze_session_agent_cli(tmp_path, write_cli_session, mock_pricing):
    session_dir = write_cli_session(tmp_path, "11111111-1111-1111-1111-111111111111")
    result = api.analyze_session(session_dir, agent="cli", auto_refresh=False)
    assert result["provider"] == "cli"
    assert result["total"]["llm_calls"] == 1


def test_analyze_session_agent_all_raises():
    with pytest.raises(ValueError, match="unknown agent|all"):
        api.analyze_session(Path("/fake"), agent="all")


# ─── list_sessions ────────────────────────────────────────────────────────────


def test_list_sessions_returns_list(mocker):
    mocker.patch(
        "copilot_session_usage._internal.vscode.default_workspace_storage_roots",
        return_value=[],
    )
    result = api.list_sessions()
    assert result == []


def test_list_sessions_with_workspace_roots(mocker):
    mock_list = mocker.patch("copilot_session_usage._internal.vscode.list_recent_sessions")
    mock_list.return_value = [{"session_id": "s1", "title": "Test"}]
    result = api.list_sessions(workspace_roots=[Path("/fake")])
    assert len(result) == 1
    assert result[0]["session_id"] == "s1"


def test_list_sessions_agent_cli(write_cli_session, tmp_path, mocker):
    fake_root = tmp_path / "cli-root"
    fake_root.mkdir()
    write_cli_session(fake_root, "11111111-1111-1111-1111-111111111111")
    mocker.patch(
        "copilot_session_usage._internal.copilot_cli.default_session_state_roots",
        return_value=[fake_root],
    )
    result = api.list_sessions(agent="cli")
    assert len(result) == 1
    assert result[0]["provider"] == "cli"


def test_list_sessions_agent_all_merges_and_dedups(write_cli_session, tmp_path, mocker):
    vscode_root = tmp_path / "vscode-root"
    vscode_root.mkdir()
    cli_root = tmp_path / "cli-root"
    cli_root.mkdir()
    write_cli_session(cli_root, "11111111-1111-1111-1111-111111111111")
    mocker.patch(
        "copilot_session_usage._internal.vscode.default_workspace_storage_roots",
        return_value=[vscode_root],
    )
    mocker.patch(
        "copilot_session_usage._internal.copilot_cli.default_session_state_roots",
        return_value=[cli_root],
    )
    result = api.list_sessions(agent="all")
    assert len(result) == 1
    assert result[0]["provider"] == "cli"


def test_list_sessions_agent_all_ignores_missing_provider_roots(
    write_cli_session, tmp_path, mocker
):
    cli_root = tmp_path / "cli-root"
    cli_root.mkdir()
    write_cli_session(cli_root, "11111111-1111-1111-1111-111111111111")
    mocker.patch(
        "copilot_session_usage._internal.vscode.default_workspace_storage_roots",
        return_value=[],
    )
    mocker.patch(
        "copilot_session_usage._internal.copilot_cli.default_session_state_roots",
        return_value=[cli_root],
    )

    result = api.list_sessions(agent="all")

    assert len(result) == 1
    assert result[0]["provider"] == "cli"


def test_list_sessions_agent_all_ignores_all_missing_provider_roots(mocker):
    mocker.patch(
        "copilot_session_usage._internal.vscode.default_workspace_storage_roots",
        return_value=[],
    )
    mocker.patch(
        "copilot_session_usage._internal.copilot_cli.default_session_state_roots",
        return_value=[],
    )

    assert api.list_sessions(agent="all") == []


def test_list_sessions_agent_all_rejects_roots_override():
    with pytest.raises(ValueError, match="agent='all'"):
        api.list_sessions(workspace_roots=[Path("/fake")], agent="all")


def test_list_sessions_agent_unknown_raises():
    with pytest.raises(ValueError, match="unknown agent"):
        api.list_sessions(agent="bogus")


def test_list_sessions_agent_both_is_removed():
    with pytest.raises(ValueError, match="unknown agent"):
        api.list_sessions(agent="both")


def test_list_sessions_with_since(mocker):
    mock_list = mocker.patch("copilot_session_usage._internal.vscode.list_recent_sessions")
    mock_list.return_value = []
    result = api.list_sessions(since="2026-01-01")
    assert result == []


# ─── find_sessions_by_title ───────────────────────────────────────────────────


def test_find_sessions_by_title(mocker):
    mocker.patch(
        "copilot_session_usage._internal.vscode.default_workspace_storage_roots",
        return_value=[Path("/fake")],
    )
    mock_find = mocker.patch("copilot_session_usage._internal.vscode.find_sessions_by_title")
    mock_find.return_value = [{"session_id": "s1", "title": "Hello"}]
    result = api.find_sessions_by_title("hello")
    assert len(result) == 1
    assert result[0]["title"] == "Hello"


def test_find_sessions_by_title_agent_cli(write_cli_session, tmp_path, mocker):
    cli_root = tmp_path / "cli-root"
    cli_root.mkdir()
    write_cli_session(
        cli_root,
        "11111111-1111-1111-1111-111111111111",
        workspace={"name": "Fixing the login bug", "cwd": "/proj"},
    )
    mocker.patch(
        "copilot_session_usage._internal.copilot_cli.default_session_state_roots",
        return_value=[cli_root],
    )
    result = api.find_sessions_by_title("login", agent="cli")
    assert len(result) == 1
    assert result[0]["provider"] == "cli"


# ─── find_session_by_id ───────────────────────────────────────────────────────


def test_find_session_by_id_found(mocker, sample_session_dir):
    mocker.patch(
        "copilot_session_usage._internal.vscode.default_workspace_storage_roots",
        return_value=[Path("/fake")],
    )
    mock_find = mocker.patch("copilot_session_usage._internal.vscode.find_session_dir_by_id")
    mock_meta = mocker.patch("copilot_session_usage._internal.vscode.find_session_metadata_by_id")
    mock_find.return_value = sample_session_dir
    mock_meta.return_value = {"session_id": "abc-123", "title": "My Title"}
    result = api.find_session_by_id("abc-123")
    assert result is not None
    assert result["total"]["llm_calls"] == 1
    assert result["title"] == "My Title"


def test_find_session_by_id_not_found(mocker):
    mocker.patch(
        "copilot_session_usage._internal.vscode.default_workspace_storage_roots",
        return_value=[Path("/fake")],
    )
    mock_find = mocker.patch("copilot_session_usage._internal.vscode.find_session_dir_by_id")
    mock_find.return_value = None
    result = api.find_session_by_id("missing")
    assert result is None


def test_find_session_by_id_agent_cli(write_cli_session, tmp_path, mocker):
    cli_root = tmp_path / "cli-root"
    cli_root.mkdir()
    session_id = "11111111-1111-1111-1111-111111111111"
    write_cli_session(cli_root, session_id)
    mocker.patch(
        "copilot_session_usage._internal.copilot_cli.default_session_state_roots",
        return_value=[cli_root],
    )
    result = api.find_session_by_id(session_id, agent="cli")
    assert result is not None
    assert result["provider"] == "cli"


def test_find_session_by_id_agent_all_falls_back_to_cli(write_cli_session, tmp_path, mocker):
    vscode_root = tmp_path / "vscode-root"
    vscode_root.mkdir()
    cli_root = tmp_path / "cli-root"
    cli_root.mkdir()
    session_id = "11111111-1111-1111-1111-111111111111"
    write_cli_session(cli_root, session_id)
    mocker.patch(
        "copilot_session_usage._internal.vscode.default_workspace_storage_roots",
        return_value=[vscode_root],
    )
    mocker.patch(
        "copilot_session_usage._internal.copilot_cli.default_session_state_roots",
        return_value=[cli_root],
    )
    result = api.find_session_by_id(session_id, agent="all")
    assert result is not None
    assert result["provider"] == "cli"


# ─── analyze_latest ───────────────────────────────────────────────────────────


def test_analyze_latest_found(mocker, sample_session_dir):
    mocker.patch(
        "copilot_session_usage._internal.vscode.default_workspace_storage_roots",
        return_value=[Path("/fake")],
    )
    mock_find = mocker.patch("copilot_session_usage._internal.vscode.find_latest_session_dir")
    mock_meta = mocker.patch("copilot_session_usage._internal.vscode.find_session_metadata_by_id")
    mock_find.return_value = sample_session_dir
    mock_meta.return_value = {"session_id": "sess-abc", "title": "Latest Title"}
    result = api.analyze_latest()
    assert result["total"]["llm_calls"] == 1
    assert result["title"] == "Latest Title"


def test_analyze_latest_not_found(mocker):
    mocker.patch(
        "copilot_session_usage._internal.vscode.default_workspace_storage_roots",
        return_value=[Path("/fake")],
    )
    mock_find = mocker.patch("copilot_session_usage._internal.vscode.find_latest_session_dir")
    mock_find.return_value = None
    with pytest.raises(ValueError, match="No session debug logs found"):
        api.analyze_latest()


def test_analyze_latest_agent_cli(write_cli_session, tmp_path, mocker):
    cli_root = tmp_path / "cli-root"
    cli_root.mkdir()
    write_cli_session(cli_root, "11111111-1111-1111-1111-111111111111")
    mocker.patch(
        "copilot_session_usage._internal.copilot_cli.default_session_state_roots",
        return_value=[cli_root],
    )
    result = api.analyze_latest(agent="cli")
    assert result["provider"] == "cli"


def test_analyze_latest_agent_all_no_sessions_raises(mocker, tmp_path):
    mocker.patch(
        "copilot_session_usage._internal.vscode.default_workspace_storage_roots",
        return_value=[],
    )
    mocker.patch(
        "copilot_session_usage._internal.copilot_cli.default_session_state_roots",
        return_value=[],
    )
    with pytest.raises(ValueError, match="No session logs found"):
        api.analyze_latest(agent="all")


# ─── batch_analyze ────────────────────────────────────────────────────────────


def test_batch_analyze(mocker, sample_session_dir):
    mocker.patch(
        "copilot_session_usage._internal.vscode.default_workspace_storage_roots",
        return_value=[Path("/fake")],
    )
    mock_list = mocker.patch("copilot_session_usage._internal.vscode.list_recent_sessions")
    mock_list.return_value = [
        {"session_id": "s1", "title": "Test", "debug_log_dir": str(sample_session_dir)}
    ]
    result = api.batch_analyze(1)
    assert "summary" in result
    assert "sessions" in result
    assert result["summary"]["session_count"] == 1


def test_batch_analyze_empty(mocker):
    mocker.patch(
        "copilot_session_usage._internal.vscode.default_workspace_storage_roots",
        return_value=[Path("/fake")],
    )
    mock_list = mocker.patch("copilot_session_usage._internal.vscode.list_recent_sessions")
    mock_list.return_value = []
    result = api.batch_analyze(10)
    assert result["summary"]["session_count"] == 0
    assert result["sessions"] == []


def test_batch_analyze_agent_cli(write_cli_session, tmp_path, mocker):
    cli_root = tmp_path / "cli-root"
    cli_root.mkdir()
    write_cli_session(cli_root, "11111111-1111-1111-1111-111111111111")
    mocker.patch(
        "copilot_session_usage._internal.copilot_cli.default_session_state_roots",
        return_value=[cli_root],
    )
    result = api.batch_analyze(1, agent="cli")
    assert result["summary"]["session_count"] == 1
    assert result["sessions"][0]["provider"] == "cli"


# ─── load_pricing ─────────────────────────────────────────────────────────────


def test_load_pricing_returns_dict():
    result = api.load_pricing(auto_refresh=False)
    assert isinstance(result, dict)
    assert "models" in result


def test_refresh_pricing_delegates_to_core(mocker):
    expected = mocker.Mock()
    refresh = mocker.patch.object(api.core, "refresh_pricing", return_value=expected)

    result = api.refresh_pricing(force=True)

    assert result is expected
    refresh.assert_called_once_with(force=True)


def test_pricing_status_delegates_to_core(mocker):
    expected = {"cached": False}
    status = mocker.patch.object(api.core, "pricing_status", return_value=expected)

    result = api.pricing_status()

    assert result == expected
    status.assert_called_once_with()


# ─── combined ("all") provider coverage ───────────────────────────────────────


def test_find_sessions_by_title_agent_all_rejects_roots_override():
    with pytest.raises(ValueError, match="agent='all'"):
        api.find_sessions_by_title("x", workspace_roots=[Path("/fake")], agent="all")


def test_find_sessions_by_title_agent_all_merges(write_cli_session, tmp_path, mocker):
    vscode_root = tmp_path / "vscode-root"
    vscode_root.mkdir()
    cli_root = tmp_path / "cli-root"
    cli_root.mkdir()
    write_cli_session(
        cli_root,
        "11111111-1111-1111-1111-111111111111",
        workspace={"name": "Fixing the login bug", "cwd": "/proj"},
    )
    mocker.patch(
        "copilot_session_usage._internal.vscode.default_workspace_storage_roots",
        return_value=[vscode_root],
    )
    mocker.patch(
        "copilot_session_usage._internal.copilot_cli.default_session_state_roots",
        return_value=[cli_root],
    )
    result = api.find_sessions_by_title("login", agent="all")
    assert len(result) == 1
    assert result[0]["provider"] == "cli"


def test_find_session_by_id_agent_all_rejects_roots_override():
    with pytest.raises(ValueError, match="agent='all'"):
        api.find_session_by_id("x", workspace_roots=[Path("/fake")], agent="all")


def test_find_session_by_id_agent_all_finds_vscode_first(mocker, sample_session_dir):
    mocker.patch(
        "copilot_session_usage._internal.vscode.default_workspace_storage_roots",
        return_value=[Path("/fake")],
    )
    mock_find = mocker.patch("copilot_session_usage._internal.vscode.find_session_dir_by_id")
    mock_meta = mocker.patch("copilot_session_usage._internal.vscode.find_session_metadata_by_id")
    mock_find.return_value = sample_session_dir
    mock_meta.return_value = {"session_id": "abc-123", "title": "VS Code hit"}
    result = api.find_session_by_id("abc-123", agent="all")
    assert result is not None
    assert result["title"] == "VS Code hit"


def test_find_session_by_id_agent_all_not_found_anywhere(mocker):
    mocker.patch(
        "copilot_session_usage._internal.vscode.default_workspace_storage_roots",
        return_value=[Path("/fake")],
    )
    mocker.patch("copilot_session_usage._internal.vscode.find_session_dir_by_id", return_value=None)
    mocker.patch(
        "copilot_session_usage._internal.copilot_cli.default_session_state_roots", return_value=[]
    )
    result = api.find_session_by_id("nowhere", agent="all")
    assert result is None


def test_analyze_latest_agent_all_rejects_roots_override():
    with pytest.raises(ValueError, match="agent='all'"):
        api.analyze_latest(workspace_roots=[Path("/fake")], agent="all")


def test_analyze_latest_agent_all_picks_vscode_when_newer(mocker, sample_session_dir):
    mocker.patch(
        "copilot_session_usage._internal.vscode.default_workspace_storage_roots",
        return_value=[Path("/fake")],
    )
    mocker.patch(
        "copilot_session_usage._internal.copilot_cli.default_session_state_roots", return_value=[]
    )
    mock_find = mocker.patch("copilot_session_usage._internal.vscode.find_latest_session_dir")
    mock_meta = mocker.patch("copilot_session_usage._internal.vscode.find_session_metadata_by_id")
    mock_find.return_value = sample_session_dir
    mock_meta.return_value = {"session_id": "sess-abc", "title": "Latest VS Code"}
    result = api.analyze_latest(agent="all")
    assert result["title"] == "Latest VS Code"


def test_analyze_latest_agent_cli_not_found_raises(mocker):
    mocker.patch(
        "copilot_session_usage._internal.copilot_cli.default_session_state_roots", return_value=[]
    )
    with pytest.raises(ValueError, match="No Copilot CLI/App sessions found"):
        api.analyze_latest(agent="cli")


def test_batch_analyze_agent_all_rejects_roots_override():
    with pytest.raises(ValueError, match="agent='all'"):
        api.batch_analyze(5, workspace_roots=[Path("/fake")], agent="all")


def test_batch_analyze_agent_all_merges(write_cli_session, tmp_path, mocker):
    vscode_root = tmp_path / "vscode-root"
    vscode_root.mkdir()
    cli_root = tmp_path / "cli-root"
    cli_root.mkdir()
    write_cli_session(cli_root, "11111111-1111-1111-1111-111111111111")
    mocker.patch(
        "copilot_session_usage._internal.vscode.default_workspace_storage_roots",
        return_value=[vscode_root],
    )
    mocker.patch(
        "copilot_session_usage._internal.copilot_cli.default_session_state_roots",
        return_value=[cli_root],
    )
    result = api.batch_analyze(5, agent="all")
    assert result["summary"]["session_count"] == 1


def test_list_sessions_agent_unknown_in_find_sessions_by_title():
    with pytest.raises(ValueError, match="unknown agent"):
        api.find_sessions_by_title("x", agent="bogus")


def test_find_session_by_id_agent_unknown():
    with pytest.raises(ValueError, match="unknown agent"):
        api.find_session_by_id("x", agent="bogus")


def test_analyze_latest_agent_unknown():
    with pytest.raises(ValueError, match="unknown agent"):
        api.analyze_latest(agent="bogus")


def test_batch_analyze_agent_unknown():
    with pytest.raises(ValueError, match="unknown agent"):
        api.batch_analyze(5, agent="bogus")


# ─── auto_refresh defaults (local-only for cli/all) ───────────────────────────


def test_analyze_session_vscode_defaults_to_auto_refresh_false(sample_session_dir, mocker):
    load_pricing = mocker.patch.object(api.core, "load_pricing", return_value={"models": {}})
    api.analyze_session(sample_session_dir)
    load_pricing.assert_called_once_with(auto_refresh=False)


def test_analyze_session_cli_defaults_to_auto_refresh_false(tmp_path, write_cli_session, mocker):
    session_dir = write_cli_session(tmp_path, "11111111-1111-1111-1111-111111111111")
    load_pricing = mocker.patch.object(api.core, "load_pricing", return_value={"models": {}})
    api.analyze_session(session_dir, agent="cli")
    load_pricing.assert_called_once_with(auto_refresh=False)


def test_analyze_session_cli_explicit_auto_refresh_true_is_honored(
    tmp_path, write_cli_session, mocker
):
    session_dir = write_cli_session(tmp_path, "11111111-1111-1111-1111-111111111111")
    load_pricing = mocker.patch.object(api.core, "load_pricing", return_value={"models": {}})
    api.analyze_session(session_dir, agent="cli", auto_refresh=True)
    load_pricing.assert_called_once_with(auto_refresh=True)


def test_analyze_latest_all_defaults_to_auto_refresh_false(tmp_path, mocker):
    vscode_root = tmp_path / "vs"
    vscode_root.mkdir()
    cli_root = tmp_path / "cli"
    cli_root.mkdir()
    mocker.patch(
        "copilot_session_usage._internal.vscode.default_workspace_storage_roots",
        return_value=[vscode_root],
    )
    mocker.patch(
        "copilot_session_usage._internal.copilot_cli.default_session_state_roots",
        return_value=[cli_root],
    )
    load_pricing = mocker.patch.object(api.core, "load_pricing", return_value={"models": {}})
    with pytest.raises(ValueError, match="No session logs found"):
        api.analyze_latest(agent="all")
    load_pricing.assert_called_once_with(auto_refresh=False)


# ─── per-call pipeline: calls export, windows, schema, offline ────────────────

CLI_SID = "22222222-2222-2222-2222-222222222222"


def _cli_events(*stamps: str) -> list[dict]:
    events = [
        {
            "type": "session.start",
            "data": {"sessionId": CLI_SID, "version": 1, "startTime": "2026-01-01T00:00:00.000Z"},
            "id": "e0",
            "timestamp": "2026-01-01T00:00:00.000Z",
        }
    ]
    for i, ts in enumerate(stamps, start=1):
        events.append(
            {
                "type": "session.usage_record",
                "data": {
                    "usage": {
                        "model": "gpt-6-luna",
                        "inputTokens": 1000 * i,
                        "cacheReadTokens": 0,
                        "cacheWriteTokens": 0,
                        "outputTokens": 10 * i,
                        "initiator": "user",
                        "copilotUsage": {"totalNanoAiu": 100_000_000 * i},
                        "accounting": {"usageId": f"u{i}"},
                    }
                },
                "id": f"id{i}",
                "timestamp": ts,
            }
        )
    return events


def test_list_calls_vscode_path_fields(sample_session_dir):
    calls = api.list_calls(sample_session_dir)
    assert len(calls) == 1
    call = calls[0]
    assert call["provider"] == "vscode"
    assert call["model"] == "claude-sonnet-4.6"
    assert call["input_tokens"] == 1000
    assert call["output_tokens"] == 100
    assert call["uncached_input_tokens"] == 1000
    assert call["kind"] == "request"
    assert call["cost_source"] == "estimated"
    assert call["ts_ms"] == 1_000_000
    for key in (
        "session_id",
        "ts",
        "cached_tokens",
        "cache_write_tokens",
        "llm_calls",
        "nano_aiu",
        "estimated_usd",
        "agent",
        "agent_id",
        "initiator",
        "skill",
    ):
        assert key in call


def test_list_calls_cli_billed_and_sorted(write_cli_session, tmp_path):
    session_dir = write_cli_session(
        tmp_path,
        CLI_SID,
        events=_cli_events("2026-01-01T00:02:00.000Z", "2026-01-01T00:01:00.000Z"),
        workspace={},
    )
    calls = api.list_calls(session_dir, agent="cli")
    assert [c["ts_ms"] for c in calls] == sorted(c["ts_ms"] for c in calls)
    assert {c["cost_source"] for c in calls} == {"billed"}
    assert sum(c["estimated_usd"] for c in calls) == pytest.approx(0.003, abs=1e-9)
    assert all(c["provider"] == "cli" and c["nano_aiu"] for c in calls)


def test_list_calls_window_filters_by_timestamp(write_cli_session, tmp_path):
    session_dir = write_cli_session(
        tmp_path,
        CLI_SID,
        events=_cli_events("2026-01-01T00:01:00.000Z", "2026-01-01T00:05:00.000Z"),
        workspace={},
    )
    late = api.list_calls(session_dir, agent="cli", since="2026-01-01T00:03:00Z")
    early = api.list_calls(session_dir, agent="cli", until="2026-01-01T00:03:00Z")
    assert [c["input_tokens"] for c in late] == [2000]
    assert [c["input_tokens"] for c in early] == [1000]


def test_iter_calls_is_lazy_equivalent_of_list_calls(sample_session_dir):
    iterator = api.iter_calls(sample_session_dir)
    assert not isinstance(iterator, list)
    assert list(iterator) == api.list_calls(sample_session_dir)


def test_list_calls_discovery_multiple_sessions_sorted(mocker, tmp_path):
    dirs = []
    for name, ts in (("late", 2_000_000), ("early", 1_000_000)):
        d = tmp_path / name
        d.mkdir()
        (d / "main.jsonl").write_text(
            json.dumps(
                {
                    "ts": ts,
                    "type": "llm_request",
                    "attrs": {
                        "model": "claude-sonnet-4.6",
                        "inputTokens": 10,
                        "outputTokens": 1,
                    },
                }
            )
            + "\n",
            encoding="utf-8",
        )
        dirs.append({"session_id": name, "title": name, "debug_log_dir": str(d)})
    mocker.patch(
        "copilot_session_usage._internal.vscode.default_workspace_storage_roots",
        return_value=[Path("/fake")],
    )
    mocker.patch("copilot_session_usage._internal.vscode.list_recent_sessions", return_value=dirs)
    calls = api.list_calls()
    assert [c["session_id"] for c in calls] == ["early", "late"]


def test_batch_analyze_window_drops_session_without_in_window_calls(mocker, sample_session_dir):
    mocker.patch(
        "copilot_session_usage._internal.vscode.default_workspace_storage_roots",
        return_value=[Path("/fake")],
    )
    mocker.patch(
        "copilot_session_usage._internal.vscode.list_recent_sessions",
        return_value=[{"session_id": "s1", "title": "T", "debug_log_dir": str(sample_session_dir)}],
    )
    inside = api.batch_analyze(5, since="1970-01-01T00:00:00Z", until="1970-01-02T00:00:00Z")
    outside = api.batch_analyze(5, since="1970-01-01T01:00:00Z")
    assert inside["summary"]["session_count"] == 1
    assert outside["summary"]["session_count"] == 0
    assert outside["sessions"] == []


def test_analysis_outputs_carry_schema_version_2(mocker, sample_session_dir):
    assert api.analyze_session(sample_session_dir)["schema_version"] == 2
    mocker.patch(
        "copilot_session_usage._internal.vscode.default_workspace_storage_roots",
        return_value=[Path("/fake")],
    )
    mocker.patch(
        "copilot_session_usage._internal.vscode.list_recent_sessions",
        return_value=[{"session_id": "s1", "title": "T", "debug_log_dir": str(sample_session_dir)}],
    )
    assert api.batch_analyze(1)["schema_version"] == 2


def test_analyze_session_reconciliation_and_cost_source_estimated(sample_session_dir):
    result = api.analyze_session(sample_session_dir, detail="full")
    assert result["total"]["cost_source"] == "estimated"
    rec = result["reconciliation"]
    assert set(rec) >= {
        "billed_usd",
        "estimated_from_tokens_usd",
        "delta_pct",
        "calls_without_billing",
    }
    assert rec["billed_usd"] == 0.0
    assert rec["delta_pct"] is None
    assert rec["calls_without_billing"] == 1
    assert "snapshot_usd" not in rec
    assert sum(m["estimated_usd"] for m in result["model_breakdown"]) == pytest.approx(
        result["total"]["estimated_usd"], abs=1e-9
    )


def test_analyze_cli_session_billed_reconciliation_and_snapshot_only_without_window(
    write_cli_session, tmp_path
):
    session_dir = write_cli_session(
        tmp_path,
        CLI_SID,
        events=_cli_events("2026-01-01T00:01:00.000Z", "2026-01-01T00:02:00.000Z")
        + [
            {
                "type": "session.shutdown",
                "data": {"shutdownType": "routine", "totalNanoAiu": 300_000_000},
                "id": "sd",
                "timestamp": "2026-01-01T00:03:00.000Z",
            }
        ],
        workspace={},
    )
    full = api.analyze_session(session_dir, agent="cli")
    assert full["total"]["cost_source"] == "billed"
    assert full["reconciliation"]["billed_usd"] == pytest.approx(0.003, abs=1e-9)
    assert full["reconciliation"]["calls_without_billing"] == 0
    assert full["reconciliation"]["snapshot_usd"] == pytest.approx(0.003, abs=1e-9)
    assert full["reconciliation"]["snapshot_delta_usd"] == pytest.approx(0.0, abs=1e-9)
    windowed = api.analyze_session(session_dir, agent="cli", since="2026-01-01T00:00:00Z")
    assert windowed["reconciliation"]["snapshot_usd"] is None
    assert windowed["reconciliation"]["snapshot_delta_usd"] is None


def test_analysis_makes_no_network_calls(mocker, sample_session_dir, write_cli_session, tmp_path):
    urlopen = mocker.patch("urllib.request.urlopen")
    refresh = mocker.patch.object(api.core, "refresh_pricing")
    runtime_refresh = mocker.patch.object(api.core, "_refresh_runtime_pricing")
    spy = mocker.spy(api.core, "load_pricing")
    mocker.patch(
        "copilot_session_usage._internal.vscode.default_workspace_storage_roots",
        return_value=[Path("/fake")],
    )
    mocker.patch(
        "copilot_session_usage._internal.vscode.list_recent_sessions",
        return_value=[{"session_id": "s1", "title": "T", "debug_log_dir": str(sample_session_dir)}],
    )
    cli_dir = write_cli_session(
        tmp_path, CLI_SID, events=_cli_events("2026-01-01T00:01:00.000Z"), workspace={}
    )

    api.analyze_session(sample_session_dir)
    api.analyze_session(cli_dir, agent="cli")
    api.batch_analyze(1)
    api.list_calls(sample_session_dir)

    urlopen.assert_not_called()
    refresh.assert_not_called()
    runtime_refresh.assert_not_called()
    assert spy.call_count >= 4
    assert all(c.kwargs.get("auto_refresh") is False for c in spy.call_args_list)
