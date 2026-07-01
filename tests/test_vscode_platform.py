"""Unit tests for vscode.py platform-specific branches."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from copilot_session_usage._internal import vscode

# ─── default_workspace_storage_roots platform branches ───────────────────────


def test_default_workspace_storage_roots_darwin(monkeypatch, tmp_path):
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    base = fake_home / "Library" / "Application Support"
    code_ws = base / "Code" / "User" / "workspaceStorage"
    code_ws.mkdir(parents=True)

    monkeypatch.setattr(Path, "home", lambda: fake_home)
    monkeypatch.setattr(sys, "platform", "darwin")
    roots = vscode.default_workspace_storage_roots()
    assert code_ws in roots


def test_default_workspace_storage_roots_win32(monkeypatch, tmp_path):
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    appdata = fake_home / "AppData" / "Roaming"
    code_ws = appdata / "Code" / "User" / "workspaceStorage"
    code_ws.mkdir(parents=True)

    monkeypatch.setattr(Path, "home", lambda: fake_home)
    monkeypatch.setenv("APPDATA", str(appdata))
    monkeypatch.setattr(sys, "platform", "win32")
    roots = vscode.default_workspace_storage_roots()
    assert code_ws in roots


def test_default_workspace_storage_roots_linux(monkeypatch, tmp_path):
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    xdg = fake_home / ".config"
    code_ws = xdg / "Code" / "User" / "workspaceStorage"
    code_ws.mkdir(parents=True)
    server_ws = fake_home / ".vscode-server" / "data" / "User" / "workspaceStorage"
    server_ws.mkdir(parents=True)

    monkeypatch.setattr(Path, "home", lambda: fake_home)
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    monkeypatch.setattr(sys, "platform", "linux")
    roots = vscode.default_workspace_storage_roots()
    assert code_ws in roots
    assert server_ws in roots


def test_default_workspace_storage_roots_linux_xdg(monkeypatch, tmp_path):
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    xdg = tmp_path / "xdg"
    xdg.mkdir()
    code_ws = xdg / "Code" / "User" / "workspaceStorage"
    code_ws.mkdir(parents=True)

    monkeypatch.setattr(Path, "home", lambda: fake_home)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(xdg))
    monkeypatch.setattr(sys, "platform", "linux")
    roots = vscode.default_workspace_storage_roots()
    assert code_ws in roots


# ─── _get_workspace_folder edge cases ─────────────────────────────────────────


def test_get_workspace_folder_no_json(tmp_path):
    ws_dir = tmp_path / "ws"
    ws_dir.mkdir()
    assert vscode._get_workspace_folder(ws_dir) == ""


def test_get_workspace_folder_bad_json(tmp_path):
    ws_dir = tmp_path / "ws"
    ws_dir.mkdir()
    (ws_dir / "workspace.json").write_text("not json", encoding="utf-8")
    assert vscode._get_workspace_folder(ws_dir) == ""


def test_get_workspace_folder_workspace_key(tmp_path):
    ws_dir = tmp_path / "ws"
    ws_dir.mkdir()
    import json

    (ws_dir / "workspace.json").write_text(
        json.dumps({"workspace": "file:///home/user/project"}), encoding="utf-8"
    )
    assert vscode._get_workspace_folder(ws_dir) == "/home/user/project"


# ─── get_sessions_from_workspace edge cases ───────────────────────────────────


def test_get_sessions_from_workspace_bad_json_in_db(tmp_path):
    ws_dir = tmp_path / "ws"
    ws_dir.mkdir()
    import sqlite3

    db_path = ws_dir / "state.vscdb"
    conn = sqlite3.connect(str(db_path))
    conn.execute("CREATE TABLE IF NOT EXISTS ItemTable (key TEXT PRIMARY KEY, value TEXT)")
    conn.execute(
        "INSERT OR REPLACE INTO ItemTable (key, value) VALUES (?, ?)",
        ("chat.ChatSessionStore.index", "not json"),
    )
    conn.commit()
    conn.close()
    assert vscode.get_sessions_from_workspace(ws_dir, use_cache=False) == []


def test_get_sessions_from_workspace_db_error(tmp_path):
    ws_dir = tmp_path / "ws"
    ws_dir.mkdir()
    # Create an empty file that sqlite will reject as not a database
    (ws_dir / "state.vscdb").write_text("not a db", encoding="utf-8")
    # sqlite3 raises DatabaseError (subclass of Error) for corrupt files
    assert vscode.get_sessions_from_workspace(ws_dir, use_cache=False) == []


def test_get_sessions_from_workspace_missing_session_id_skipped(tmp_path):
    ws_dir = tmp_path / "ws"
    ws_dir.mkdir()
    import json
    import sqlite3

    db_path = ws_dir / "state.vscdb"
    conn = sqlite3.connect(str(db_path))
    conn.execute("CREATE TABLE IF NOT EXISTS ItemTable (key TEXT PRIMARY KEY, value TEXT)")
    payload = json.dumps({"entries": {"s1": {"title": "No ID", "timing": {"created": 1_000_000}}}})
    conn.execute(
        "INSERT OR REPLACE INTO ItemTable (key, value) VALUES (?, ?)",
        ("chat.ChatSessionStore.index", payload),
    )
    conn.commit()
    conn.close()
    sessions = vscode.get_sessions_from_workspace(ws_dir, use_cache=False)
    assert sessions == []


def test_get_sessions_from_workspace_clear_cache(monkeypatch, tmp_path):
    ws_dir = tmp_path / "ws"
    ws_dir.mkdir()
    import json
    import sqlite3

    db_path = ws_dir / "state.vscdb"
    conn = sqlite3.connect(str(db_path))
    conn.execute("CREATE TABLE IF NOT EXISTS ItemTable (key TEXT PRIMARY KEY, value TEXT)")
    payload = json.dumps(
        {"entries": {"s1": {"sessionId": "s1", "title": "Test", "timing": {"created": 1_000_000}}}}
    )
    conn.execute(
        "INSERT OR REPLACE INTO ItemTable (key, value) VALUES (?, ?)",
        ("chat.ChatSessionStore.index", payload),
    )
    conn.commit()
    conn.close()

    # First call populates cache
    s1 = vscode.get_sessions_from_workspace(ws_dir, use_cache=True)
    # Clear cache manually and call again
    monkeypatch.setattr(vscode, "_WS_DB_CACHE", {})
    s2 = vscode.get_sessions_from_workspace(ws_dir, use_cache=True)
    assert s1 == s2
    assert s1 is not s2  # Different list objects since cache was cleared


# ─── find_session_dir_by_id edge cases ────────────────────────────────────────


def test_find_session_dir_by_id_nondir_entry_skipped(tmp_path):
    ws_root = tmp_path / "workspaceStorage"
    ws_root.mkdir()
    (ws_root / "file.txt").write_text("", encoding="utf-8")
    assert vscode.find_session_dir_by_id("s1", [ws_root]) is None


# ─── find_sessions_by_title edge cases ────────────────────────────────────────


def test_find_sessions_by_title_nondir_skipped(tmp_path):
    ws_root = tmp_path / "workspaceStorage"
    ws_root.mkdir()
    (ws_root / "file.txt").write_text("", encoding="utf-8")
    assert vscode.find_sessions_by_title("test", [ws_root]) == []


# ─── find_latest_session_dir edge cases ───────────────────────────────────────


def test_find_latest_session_dir_nondir_skipped(tmp_path):
    ws_root = tmp_path / "workspaceStorage"
    ws_root.mkdir()
    (ws_root / "file.txt").write_text("", encoding="utf-8")
    assert vscode.find_latest_session_dir([ws_root]) is None


def test_find_latest_session_dir_no_debug_logs(tmp_path):
    ws_root = tmp_path / "workspaceStorage"
    ws_root.mkdir()
    ws_dir = ws_root / "hash1"
    ws_dir.mkdir()
    assert vscode.find_latest_session_dir([ws_root]) is None


# ─── list_recent_sessions edge cases ──────────────────────────────────────────


def test_list_recent_sessions_nondir_skipped(tmp_path):
    ws_root = tmp_path / "workspaceStorage"
    ws_root.mkdir()
    (ws_root / "file.txt").write_text("", encoding="utf-8")
    sessions = vscode.list_recent_sessions([ws_root])
    assert sessions == []


def test_list_recent_sessions_require_logs_filter(tmp_path):
    ws_root = tmp_path / "workspaceStorage"
    ws_root.mkdir()
    ws_dir = ws_root / "hash1"
    ws_dir.mkdir()
    import json
    import sqlite3

    db_path = ws_dir / "state.vscdb"
    conn = sqlite3.connect(str(db_path))
    conn.execute("CREATE TABLE IF NOT EXISTS ItemTable (key TEXT PRIMARY KEY, value TEXT)")
    payload = json.dumps(
        {
            "entries": {
                "s1": {"sessionId": "s1", "title": "Has logs", "timing": {"created": 2_000_000}},
                "s2": {"sessionId": "s2", "title": "No logs", "timing": {"created": 1_000_000}},
            }
        }
    )
    conn.execute(
        "INSERT OR REPLACE INTO ItemTable (key, value) VALUES (?, ?)",
        ("chat.ChatSessionStore.index", payload),
    )
    conn.commit()
    conn.close()
    # Create debug logs only for s1
    debug_dir = ws_dir / "GitHub.copilot-chat" / "debug-logs" / "s1"
    debug_dir.mkdir(parents=True)

    sessions = vscode.list_recent_sessions([ws_root], require_logs=True)
    assert len(sessions) == 1
    assert sessions[0]["session_id"] == "s1"


# ─── resolve_ws_roots ─────────────────────────────────────────────────────────


def test_resolve_ws_roots_explicit_path(tmp_path):
    ws_root = tmp_path / "workspaceStorage"
    ws_root.mkdir()
    roots = vscode.resolve_ws_roots(str(ws_root))
    assert roots == [ws_root]


def test_resolve_ws_roots_explicit_not_found(tmp_path):
    from click.exceptions import ClickException

    nonexistent = tmp_path / "nonexistent"
    with pytest.raises(ClickException, match="not found"):
        vscode.resolve_ws_roots(str(nonexistent))


def test_resolve_ws_roots_auto_detect(monkeypatch, tmp_path):
    fake_root = tmp_path / "fake_ws"
    fake_root.mkdir()
    monkeypatch.setattr(vscode, "default_workspace_storage_roots", lambda: [fake_root])
    roots = vscode.resolve_ws_roots(None)
    assert fake_root in roots
