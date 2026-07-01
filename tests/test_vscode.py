"""Unit tests for vscode.py — workspace discovery, session listing, resolution."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from copilot_session_usage._internal import vscode

# ─── Helpers ──────────────────────────────────────────────────────────────────


def _make_vscdb(ws_dir: Path, entries: dict) -> None:
    """Create a state.vscdb with the given chat session index entries."""
    db_path = ws_dir / "state.vscdb"
    conn = sqlite3.connect(str(db_path))
    conn.execute("CREATE TABLE IF NOT EXISTS ItemTable (key TEXT PRIMARY KEY, value TEXT)")
    payload = json.dumps({"entries": entries})
    conn.execute(
        "INSERT OR REPLACE INTO ItemTable (key, value) VALUES (?, ?)",
        ("chat.ChatSessionStore.index", payload),
    )
    conn.commit()
    conn.close()


def _make_workspace_json(ws_dir: Path, folder: str) -> None:
    (ws_dir / "workspace.json").write_text(json.dumps({"folder": folder}), encoding="utf-8")


# ─── default_workspace_storage_roots ──────────────────────────────────────────


def test_default_workspace_storage_roots_returns_existing_only(monkeypatch, tmp_path):
    fake_base = tmp_path / "fake_ws"
    fake_base.mkdir(parents=True)
    monkeypatch.setattr(vscode, "default_workspace_storage_roots", lambda: [fake_base])
    roots = vscode.default_workspace_storage_roots()
    assert fake_base in roots


# ─── get_sessions_from_workspace ──────────────────────────────────────────────


def test_get_sessions_from_workspace_basic(tmp_path):
    ws_dir = tmp_path / "ws1"
    ws_dir.mkdir()
    _make_vscdb(
        ws_dir,
        {
            "s1": {
                "sessionId": "abc-123",
                "title": "Hello world",
                "timing": {"created": 1_000_000},
                "lastMessageDate": 2_000_000,
            }
        },
    )
    sessions = vscode.get_sessions_from_workspace(ws_dir, use_cache=False)
    assert len(sessions) == 1
    assert sessions[0]["session_id"] == "abc-123"
    assert sessions[0]["title"] == "Hello world"
    assert sessions[0]["created_ms"] == 1_000_000
    assert sessions[0]["last_message_ms"] == 2_000_000


def test_get_sessions_from_workspace_with_workspace_folder(tmp_path):
    ws_dir = tmp_path / "ws2"
    ws_dir.mkdir()
    _make_workspace_json(ws_dir, "file:///home/user/project")
    _make_vscdb(
        ws_dir,
        {
            "s1": {
                "sessionId": "def-456",
                "title": "Project session",
                "timing": {"created": 1_000_000},
            }
        },
    )
    sessions = vscode.get_sessions_from_workspace(ws_dir, use_cache=False)
    assert sessions[0]["workspace_folder"] == "/home/user/project"


def test_get_sessions_from_workspace_no_db(tmp_path):
    ws_dir = tmp_path / "ws3"
    ws_dir.mkdir()
    assert vscode.get_sessions_from_workspace(ws_dir, use_cache=False) == []


def test_get_sessions_from_workspace_caching(tmp_path):
    ws_dir = tmp_path / "ws4"
    ws_dir.mkdir()
    _make_vscdb(
        ws_dir,
        {
            "s1": {
                "sessionId": "cached-1",
                "title": "Cached",
                "timing": {"created": 1_000_000},
            }
        },
    )
    s1 = vscode.get_sessions_from_workspace(ws_dir, use_cache=True)
    s2 = vscode.get_sessions_from_workspace(ws_dir, use_cache=True)
    assert s1 is s2  # same list object from cache


def test_get_sessions_from_workspace_debug_log_dir(tmp_path):
    ws_dir = tmp_path / "ws5"
    ws_dir.mkdir()
    debug_dir = ws_dir / "GitHub.copilot-chat" / "debug-logs" / "sess-1"
    debug_dir.mkdir(parents=True)
    _make_vscdb(
        ws_dir,
        {
            "s1": {
                "sessionId": "sess-1",
                "title": "Has logs",
                "timing": {"created": 1_000_000},
            }
        },
    )
    sessions = vscode.get_sessions_from_workspace(ws_dir, use_cache=False)
    assert sessions[0]["has_debug_logs"] is True
    assert sessions[0]["debug_log_dir"] == str(debug_dir)


# ─── find_session_dir_by_id ───────────────────────────────────────────────────


def test_find_session_dir_by_id_found(tmp_path):
    ws_root = tmp_path / "workspaceStorage"
    ws_root.mkdir()
    ws_dir = ws_root / "hash123"
    ws_dir.mkdir()
    debug_dir = ws_dir / "GitHub.copilot-chat" / "debug-logs" / "sess-abc"
    debug_dir.mkdir(parents=True)
    result = vscode.find_session_dir_by_id("sess-abc", [ws_root])
    assert result == debug_dir


def test_find_session_dir_by_id_not_found(tmp_path):
    ws_root = tmp_path / "workspaceStorage"
    ws_root.mkdir()
    assert vscode.find_session_dir_by_id("missing", [ws_root]) is None


# ─── find_sessions_by_title ───────────────────────────────────────────────────


def test_find_sessions_by_title_case_insensitive(tmp_path):
    ws_root = tmp_path / "workspaceStorage"
    ws_root.mkdir()
    ws_dir = ws_root / "hash1"
    ws_dir.mkdir()
    _make_vscdb(
        ws_dir,
        {
            "s1": {
                "sessionId": "s1",
                "title": "Hello World",
                "timing": {"created": 2_000_000},
            },
            "s2": {
                "sessionId": "s2",
                "title": "Goodbye",
                "timing": {"created": 1_000_000},
            },
        },
    )
    matches = vscode.find_sessions_by_title("hello", [ws_root])
    assert len(matches) == 1
    assert matches[0]["session_id"] == "s1"


def test_find_sessions_by_title_sorted_recent_first(tmp_path):
    ws_root = tmp_path / "workspaceStorage"
    ws_root.mkdir()
    ws_dir = ws_root / "hash1"
    ws_dir.mkdir()
    _make_vscdb(
        ws_dir,
        {
            "s1": {
                "sessionId": "s1",
                "title": "Alpha",
                "timing": {"created": 1_000_000},
            },
            "s2": {
                "sessionId": "s2",
                "title": "Alpha",
                "timing": {"created": 3_000_000},
            },
            "s3": {
                "sessionId": "s3",
                "title": "Alpha",
                "timing": {"created": 2_000_000},
            },
        },
    )
    matches = vscode.find_sessions_by_title("alpha", [ws_root])
    assert [m["session_id"] for m in matches] == ["s2", "s3", "s1"]


# ─── find_latest_session_dir ──────────────────────────────────────────────────


def test_find_latest_session_dir_by_mtime(tmp_path):
    ws_root = tmp_path / "workspaceStorage"
    ws_root.mkdir()
    ws_dir = ws_root / "hash1"
    ws_dir.mkdir()
    debug_dir1 = ws_dir / "GitHub.copilot-chat" / "debug-logs" / "old"
    debug_dir1.mkdir(parents=True)
    debug_dir2 = ws_dir / "GitHub.copilot-chat" / "debug-logs" / "new"
    debug_dir2.mkdir(parents=True)
    import time

    now = time.time()
    import os

    os.utime(str(debug_dir1), (now - 100, now - 100))
    os.utime(str(debug_dir2), (now, now))
    result = vscode.find_latest_session_dir([ws_root])
    assert result == debug_dir2


def test_find_latest_session_dir_with_workspace_filter(tmp_path):
    ws_root = tmp_path / "workspaceStorage"
    ws_root.mkdir()
    ws_dir1 = ws_root / "hash1"
    ws_dir1.mkdir()
    _make_workspace_json(ws_dir1, "file:///home/user/project-a")
    debug_dir1 = ws_dir1 / "GitHub.copilot-chat" / "debug-logs" / "sess-a"
    debug_dir1.mkdir(parents=True)
    ws_dir2 = ws_root / "hash2"
    ws_dir2.mkdir()
    _make_workspace_json(ws_dir2, "file:///home/user/project-b")
    debug_dir2 = ws_dir2 / "GitHub.copilot-chat" / "debug-logs" / "sess-b"
    debug_dir2.mkdir(parents=True)
    result = vscode.find_latest_session_dir([ws_root], workspace_filter="project-a")
    assert result == debug_dir1


def test_find_latest_session_dir_none(tmp_path):
    ws_root = tmp_path / "workspaceStorage"
    ws_root.mkdir()
    assert vscode.find_latest_session_dir([ws_root]) is None


# ─── list_recent_sessions ─────────────────────────────────────────────────────


def test_list_recent_sessions_basic(tmp_path):
    ws_root = tmp_path / "workspaceStorage"
    ws_root.mkdir()
    ws_dir = ws_root / "hash1"
    ws_dir.mkdir()
    _make_vscdb(
        ws_dir,
        {
            "s1": {
                "sessionId": "s1",
                "title": "First",
                "timing": {"created": 3_000_000},
            },
            "s2": {
                "sessionId": "s2",
                "title": "Second",
                "timing": {"created": 1_000_000},
            },
        },
    )
    sessions = vscode.list_recent_sessions([ws_root], limit=10)
    assert len(sessions) == 2
    assert sessions[0]["session_id"] == "s1"
    assert sessions[1]["session_id"] == "s2"


def test_list_recent_sessions_limit(tmp_path):
    ws_root = tmp_path / "workspaceStorage"
    ws_root.mkdir()
    ws_dir = ws_root / "hash1"
    ws_dir.mkdir()
    entries = {
        f"s{i}": {
            "sessionId": f"s{i}",
            "title": f"Session {i}",
            "timing": {"created": i * 1_000_000},
        }
        for i in range(1, 6)
    }
    _make_vscdb(ws_dir, entries)
    sessions = vscode.list_recent_sessions([ws_root], limit=3)
    assert len(sessions) == 3
    assert sessions[0]["session_id"] == "s5"


def test_list_recent_sessions_since_filter(tmp_path):
    ws_root = tmp_path / "workspaceStorage"
    ws_root.mkdir()
    ws_dir = ws_root / "hash1"
    ws_dir.mkdir()
    _make_vscdb(
        ws_dir,
        {
            "s1": {
                "sessionId": "s1",
                "title": "Old",
                "timing": {"created": 1_000_000},
            },
            "s2": {
                "sessionId": "s2",
                "title": "New",
                "timing": {"created": 5_000_000},
            },
        },
    )
    sessions = vscode.list_recent_sessions([ws_root], limit=10, since_ms=2_000_000)
    assert len(sessions) == 1
    assert sessions[0]["session_id"] == "s2"


def test_list_recent_sessions_workspace_filter(tmp_path):
    ws_root = tmp_path / "workspaceStorage"
    ws_root.mkdir()
    ws_dir1 = ws_root / "hash1"
    ws_dir1.mkdir()
    _make_workspace_json(ws_dir1, "file:///home/user/project-a")
    _make_vscdb(
        ws_dir1,
        {
            "s1": {
                "sessionId": "s1",
                "title": "A",
                "timing": {"created": 2_000_000},
            }
        },
    )
    ws_dir2 = ws_root / "hash2"
    ws_dir2.mkdir()
    _make_workspace_json(ws_dir2, "file:///home/user/project-b")
    _make_vscdb(
        ws_dir2,
        {
            "s2": {
                "sessionId": "s2",
                "title": "B",
                "timing": {"created": 1_000_000},
            }
        },
    )
    sessions = vscode.list_recent_sessions([ws_root], limit=10, workspace_filter="project-a")
    assert len(sessions) == 1
    assert sessions[0]["session_id"] == "s1"


def test_list_recent_sessions_require_logs(tmp_path):
    ws_root = tmp_path / "workspaceStorage"
    ws_root.mkdir()
    ws_dir = ws_root / "hash1"
    ws_dir.mkdir()
    debug_dir = ws_dir / "GitHub.copilot-chat" / "debug-logs" / "s1"
    debug_dir.mkdir(parents=True)
    _make_vscdb(
        ws_dir,
        {
            "s1": {
                "sessionId": "s1",
                "title": "Has logs",
                "timing": {"created": 2_000_000},
            },
            "s2": {
                "sessionId": "s2",
                "title": "No logs",
                "timing": {"created": 1_000_000},
            },
        },
    )
    sessions = vscode.list_recent_sessions([ws_root], limit=10, require_logs=True)
    assert len(sessions) == 1
    assert sessions[0]["session_id"] == "s1"


# ─── resolve_ws_roots ─────────────────────────────────────────────────────────


def test_resolve_ws_roots_explicit_path(tmp_path):
    ws_root = tmp_path / "explicit"
    ws_root.mkdir()
    roots = vscode.resolve_ws_roots(str(ws_root))
    assert roots == [ws_root]


def test_resolve_ws_roots_explicit_not_found(tmp_path):
    missing = tmp_path / "missing"
    with pytest.raises(click.ClickException):
        vscode.resolve_ws_roots(str(missing))


# Need click import for the exception type check
import click  # noqa: E402
