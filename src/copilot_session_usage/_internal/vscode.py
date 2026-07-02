"""VS Code Copilot session discovery logic.

Implements workspace storage layout parsing, state.vscdb queries, and
session directory resolution for the VS Code Copilot extension.
"""

from __future__ import annotations

import json
import os
import sqlite3
import sys
from pathlib import Path
from typing import Any

# ─── Workspace DB cache ─────────────────────────────────────────────────────

_WS_DB_CACHE: dict[str, list[dict]] = {}


# ─── Workspace storage path resolution (cross-platform) ─────────────────────


def default_workspace_storage_roots() -> list[Path]:
    r"""Return all existing workspaceStorage directories for the current platform.

    Checked locations:

    - macOS:   ~/Library/Application Support/Code{,-Insiders}/User/workspaceStorage
    - Windows: %APPDATA%\\Code{,-Insiders}\\User\\workspaceStorage
    - Linux:   $XDG_CONFIG_HOME/Code{,-Insiders}/User/workspaceStorage
               ~/.vscode-server{,-insiders}/data/User/workspaceStorage  (WSL2 / remote)

    Only directories that actually exist are returned.
    """
    home = Path.home()
    candidates: list[Path] = []

    if sys.platform == "darwin":
        base = home / "Library" / "Application Support"
        for variant in ("Code", "Code - Insiders"):
            candidates.append(base / variant / "User" / "workspaceStorage")

    elif sys.platform == "win32":
        appdata = Path(os.environ.get("APPDATA") or (home / "AppData" / "Roaming"))
        for variant in ("Code", "Code - Insiders"):
            candidates.append(appdata / variant / "User" / "workspaceStorage")

    else:
        xdg = Path(os.environ.get("XDG_CONFIG_HOME") or (home / ".config"))
        for variant in ("Code", "Code - Insiders"):
            candidates.append(xdg / variant / "User" / "workspaceStorage")
        for variant in (".vscode-server", ".vscode-server-insiders"):
            candidates.append(home / variant / "data" / "User" / "workspaceStorage")

    return [p for p in candidates if p.is_dir()]


def agent_traces_db_paths() -> list[Path]:
    r"""Return existing ``agent-traces.db`` paths for the current platform.

    VS Code stores this OTel SQLite database in ``globalStorage``::

        <Code>/User/globalStorage/github.copilot-chat/agent-traces.db

    The database is only created when
    ``github.copilot.chat.otel.dbSpanExporter.enabled`` is ``true``
    (VS Code 1.103+ required).  It is absent on WSL2 remote installs,
    CI environments, and older VS Code versions.

    Only paths that actually exist are returned.  Callers must handle an
    empty list gracefully — the OTel DB is never required for operation.
    """
    home = Path.home()
    candidates: list[Path] = []
    rel = Path("User", "globalStorage", "github.copilot-chat", "agent-traces.db")

    if sys.platform == "darwin":
        base = home / "Library" / "Application Support"
        for variant in ("Code", "Code - Insiders"):
            candidates.append(base / variant / rel)

    elif sys.platform == "win32":
        appdata = Path(os.environ.get("APPDATA") or (home / "AppData" / "Roaming"))
        for variant in ("Code", "Code - Insiders"):
            candidates.append(appdata / variant / rel)

    else:
        xdg = Path(os.environ.get("XDG_CONFIG_HOME") or (home / ".config"))
        for variant in ("Code", "Code - Insiders"):
            candidates.append(xdg / variant / rel)

    return [p for p in candidates if p.is_file()]


def _get_workspace_folder(ws_dir: Path) -> str:
    """Return the actual folder path for a workspace storage directory."""
    ws_json = ws_dir / "workspace.json"
    if ws_json.exists():
        try:
            data: dict[str, Any] = json.loads(ws_json.read_text(encoding="utf-8"))
            folder = data.get("folder") or data.get("workspace", "")
            if isinstance(folder, str):
                return folder.removeprefix("file://") if folder.startswith("file://") else folder
        except (json.JSONDecodeError, OSError):
            pass
    return ""


def get_sessions_from_workspace(ws_dir: Path, use_cache: bool = True) -> list[dict]:
    """Return session metadata from a workspace's state.vscdb.

    When ``use_cache`` is True (the default), results are cached per
    workspace directory so batch operations only read each DB once.
    """
    cache_key = str(ws_dir.resolve())
    if use_cache and cache_key in _WS_DB_CACHE:
        return _WS_DB_CACHE[cache_key]

    db_path = ws_dir / "state.vscdb"
    if not db_path.exists():
        return []
    try:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        cur = conn.execute("SELECT value FROM ItemTable WHERE key = 'chat.ChatSessionStore.index'")
        row = cur.fetchone()
        conn.close()
    except (sqlite3.OperationalError, sqlite3.DatabaseError):
        return []
    if not row:
        return []
    try:
        data = json.loads(row[0])
    except json.JSONDecodeError:
        return []

    workspace_folder = _get_workspace_folder(ws_dir)
    sessions = []
    for v in data.get("entries", {}).values():
        session_id = v.get("sessionId", "")
        if not session_id:
            continue
        debug_log_dir = ws_dir / "GitHub.copilot-chat/debug-logs" / session_id
        sessions.append(
            {
                "session_id": session_id,
                "title": v.get("title", ""),
                "workspace_folder": workspace_folder,
                "workspace_hash": ws_dir.name,
                "created_ms": v.get("timing", {}).get("created"),
                "last_message_ms": v.get("lastMessageDate"),
                "has_debug_logs": debug_log_dir.exists(),
                "debug_log_dir": str(debug_log_dir),
            }
        )

    if use_cache:
        _WS_DB_CACHE[cache_key] = sessions
    return sessions


def find_session_dir_by_id(session_id: str, ws_roots: list[Path]) -> Path | None:
    """Search ws_roots for a debug log directory matching session_id."""
    for ws_dir in ws_roots:
        if not ws_dir.is_dir():
            continue
        for candidate in ws_dir.iterdir():
            if not candidate.is_dir():
                continue
            log_dir = candidate / "GitHub.copilot-chat" / "debug-logs" / session_id
            if log_dir.exists():
                return log_dir
    return None


def find_session_metadata_by_id(session_id: str, ws_roots: list[Path]) -> dict | None:
    """Search ws_roots for session metadata (including title) by session_id.

    Returns the session dict from the workspace DB, or None if not found.
    """
    for ws_dir in ws_roots:
        if not ws_dir.is_dir():
            continue
        for candidate in ws_dir.iterdir():
            if not candidate.is_dir():
                continue
            for session in get_sessions_from_workspace(candidate, use_cache=True):
                if session.get("session_id") == session_id:
                    return session
    return None


def find_sessions_by_title(title: str, ws_roots: list[Path]) -> list[dict]:
    """Search ws_roots for sessions whose title contains the given string."""
    lower = title.lower()
    matches: list[dict] = []
    for ws_dir in ws_roots:
        if not ws_dir.is_dir():
            continue
        for ws_sub in ws_dir.iterdir():
            if not ws_sub.is_dir():
                continue
            for session in get_sessions_from_workspace(ws_sub, use_cache=True):
                if lower in session.get("title", "").lower():
                    matches.append(session)
    return sorted(matches, key=lambda s: s.get("created_ms") or 0, reverse=True)


def find_latest_session_dir(
    ws_roots: list[Path], workspace_filter: str | None = None
) -> Path | None:
    """Return the most recently modified debug log directory across ws_roots."""
    latest: Path | None = None
    latest_mtime = 0.0
    for ws_dir in ws_roots:
        if not ws_dir.is_dir():
            continue
        for ws_sub in ws_dir.iterdir():
            if not ws_sub.is_dir():
                continue
            if workspace_filter:
                folder = _get_workspace_folder(ws_sub)
                if workspace_filter not in folder:
                    continue
            debug_logs_base = ws_sub / "GitHub.copilot-chat" / "debug-logs"
            if not debug_logs_base.exists():
                continue
            for session_dir in debug_logs_base.iterdir():
                if not session_dir.is_dir():
                    continue
                mtime = session_dir.stat().st_mtime
                if mtime > latest_mtime:
                    latest_mtime = mtime
                    latest = session_dir
    return latest


def list_recent_sessions(
    ws_roots: list[Path],
    limit: int = 20,
    since_ms: int | None = None,
    workspace_filter: str | None = None,
    require_logs: bool = False,
) -> list[dict]:
    """List sessions from ws_roots, sorted most-recent first.

    When ``require_logs`` is True, only sessions with existing debug logs
    are returned (useful for batch analysis).
    """
    from copilot_session_usage._internal import core

    all_sessions: list[dict] = []
    for ws_dir in ws_roots:
        if not ws_dir.is_dir():
            continue
        for ws_sub in ws_dir.iterdir():
            if not ws_sub.is_dir():
                continue
            for session in get_sessions_from_workspace(ws_sub, use_cache=True):
                if since_ms and (session.get("created_ms") or 0) < since_ms:
                    continue
                if workspace_filter and workspace_filter not in session.get("workspace_folder", ""):
                    continue
                if require_logs and not session.get("has_debug_logs"):
                    continue
                session["created_at"] = core.ts_to_iso(session.get("created_ms"))
                session["last_activity_at"] = core.ts_to_iso(session.get("last_message_ms"))
                all_sessions.append(session)
    all_sessions.sort(key=lambda s: s.get("created_ms") or 0, reverse=True)
    return all_sessions[:limit]


def resolve_ws_roots(workspace_storage: str | None) -> list[Path]:
    """Resolve workspaceStorage roots from an explicit override or auto-detection."""
    if workspace_storage:
        root = Path(workspace_storage)
        if not root.is_dir():
            msg = f"--workspace-storage path not found: {root}"
            raise click.ClickException(msg)
        return [root]
    roots = default_workspace_storage_roots()
    if not roots:
        msg = (
            "No workspaceStorage directory found for this platform.\n"
            "Pass --workspace-storage PATH to specify the location manually.\n"
            "Common paths:\n"
            "  macOS:   ~/Library/Application Support/Code/User/workspaceStorage\n"
            "  Linux:   ~/.config/Code/User/workspaceStorage\n"
            "  Windows: %APPDATA%\\Code\\User\\workspaceStorage\n"
            "  WSL2:    /mnt/c/Users/<you>/AppData/Roaming/Code/User/workspaceStorage"
        )
        raise click.ClickException(msg)
    return roots


import click  # noqa: E402
