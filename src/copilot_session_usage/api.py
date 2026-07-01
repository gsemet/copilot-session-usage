"""Public Python API for copilot-session-usage.

All functions accept an optional ``agent`` parameter for future routing
between VS Code and Copilot-CLI providers.
"""

from __future__ import annotations

from pathlib import Path

from copilot_session_usage._internal import core, vscode


def analyze_session(path: Path, detail: str = "compact", agent: str = "vscode") -> dict:
    """Analyze one session by its debug-log directory path.

    Args:
        path: Path to the session's debug-log directory.
        detail: ``minimal``, ``compact`` (default), or ``full``.
        agent: Provider to use (``vscode`` or ``cli``).

    Returns:
        Session analysis dict shaped to the requested detail level.

    Raises:
        NotImplementedError: If ``agent`` is ``"cli"``.
    """
    if agent == "cli":
        raise NotImplementedError("Copilot-CLI support is not yet implemented.")
    pricing = core.load_pricing()
    result = core.analyze_session(Path(path), pricing)
    return core.shape_session(result, detail)


def list_sessions(
    workspace_roots: list[Path] | None = None,
    limit: int = 20,
    since: str | None = None,
    workspace_filter: str | None = None,
    agent: str = "vscode",
) -> list[dict]:
    """List recent sessions (metadata only, no JSONL reads).

    Args:
        workspace_roots: Override workspaceStorage directories.
            Auto-detected if None.
        limit: Maximum sessions to return.
        since: Only sessions created after this date (YYYY-MM-DD or ISO 8601).
        workspace_filter: Only sessions from this workspace folder.
        agent: Provider to use (``vscode`` or ``cli``).

    Returns:
        List of session metadata dicts, most-recent first.
    """
    if agent == "cli":
        raise NotImplementedError("Copilot-CLI support is not yet implemented.")

    if workspace_roots is None:
        workspace_roots = vscode.default_workspace_storage_roots()

    since_ms = core.parse_since_to_ms(since) if since else None
    return vscode.list_recent_sessions(
        workspace_roots,
        limit=limit,
        since_ms=since_ms,
        workspace_filter=workspace_filter,
    )


def find_sessions_by_title(
    title: str,
    workspace_roots: list[Path] | None = None,
    agent: str = "vscode",
) -> list[dict]:
    """Fuzzy-match sessions by title substring.

    Args:
        title: Substring to search for (case-insensitive).
        workspace_roots: Override workspaceStorage directories.
        agent: Provider to use (``vscode`` or ``cli``).

    Returns:
        Matching session metadata dicts, most-recent first.
    """
    if agent == "cli":
        raise NotImplementedError("Copilot-CLI support is not yet implemented.")

    if workspace_roots is None:
        workspace_roots = vscode.default_workspace_storage_roots()

    return vscode.find_sessions_by_title(title, workspace_roots)


def find_session_by_id(
    session_id: str, workspace_roots: list[Path] | None = None, agent: str = "vscode"
) -> dict | None:
    """Analyze a session by its exact UUID.

    Args:
        session_id: The session UUID.
        workspace_roots: Override workspaceStorage directories.
        agent: Provider to use (``vscode`` or ``cli``).

    Returns:
        Session analysis dict, or None if not found.
    """
    if agent == "cli":
        raise NotImplementedError("Copilot-CLI support is not yet implemented.")

    if workspace_roots is None:
        workspace_roots = vscode.default_workspace_storage_roots()

    session_dir = vscode.find_session_dir_by_id(session_id, workspace_roots)
    if session_dir is None:
        return None
    pricing = core.load_pricing()
    return core.analyze_session(session_dir, pricing)


def analyze_latest(
    workspace_roots: list[Path] | None = None,
    detail: str = "compact",
    workspace_filter: str | None = None,
    agent: str = "vscode",
) -> dict:
    """Analyze the most recently modified session.

    Args:
        workspace_roots: Override workspaceStorage directories.
        detail: ``minimal``, ``compact`` (default), or ``full``.
        workspace_filter: Only sessions from this workspace folder.
        agent: Provider to use (``vscode`` or ``cli``).

    Returns:
        Session analysis dict shaped to the requested detail level.

    Raises:
        ValueError: If no sessions are found.
    """
    if agent == "cli":
        raise NotImplementedError("Copilot-CLI support is not yet implemented.")

    if workspace_roots is None:
        workspace_roots = vscode.default_workspace_storage_roots()

    session_dir = vscode.find_latest_session_dir(workspace_roots, workspace_filter=workspace_filter)
    if session_dir is None:
        raise ValueError("No session debug logs found in workspace storage.")
    pricing = core.load_pricing()
    result = core.analyze_session(session_dir, pricing)
    return core.shape_session(result, detail)


def batch_analyze(
    n: int,
    workspace_roots: list[Path] | None = None,
    detail: str = "compact",
    since: str | None = None,
    workspace_filter: str | None = None,
    agent: str = "vscode",
) -> dict:
    """Analyze the N most recent sessions.

    Args:
        n: Number of sessions to analyze.
        workspace_roots: Override workspaceStorage directories.
        detail: ``minimal``, ``compact`` (default), or ``full``.
        since: Only sessions created after this date.
        workspace_filter: Only sessions from this workspace folder.
        agent: Provider to use (``vscode`` or ``cli``).

    Returns:
        Dict with ``summary`` (aggregate) and ``sessions`` (per-session list).
    """
    if agent == "cli":
        raise NotImplementedError("Copilot-CLI support is not yet implemented.")

    if workspace_roots is None:
        workspace_roots = vscode.default_workspace_storage_roots()

    since_ms = core.parse_since_to_ms(since) if since else None
    sessions = vscode.list_recent_sessions(
        workspace_roots,
        limit=n,
        since_ms=since_ms,
        workspace_filter=workspace_filter,
        require_logs=True,
    )
    pricing = core.load_pricing()
    results: list[dict] = []
    for session in sessions:
        session_dir = Path(session["debug_log_dir"])
        if not session_dir.exists():
            continue
        result = core.analyze_session(session_dir, pricing)
        result["title"] = session.get("title") or result.get("title")
        results.append(result)
    return core.shape_batch(results, detail)


def load_pricing(ref_dir: Path | None = None) -> dict:
    """Load pricing data.

    Args:
        ref_dir: Directory containing pricing YAML files. If None, uses
            the bundled data directory shipped with the package.

    Returns:
        Pricing dict with model rates.
    """
    return core.load_pricing(ref_dir)
