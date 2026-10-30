"""Public Python API for copilot-session-usage.

All functions accept an optional ``agent`` parameter for provider routing.
Supported values are ``"vscode"`` (default), ``"cli"`` (Copilot CLI /
Copilot App local sessions), and ``"all"`` — an explicit, opt-in combined
mode that discovers and aggregates sessions from both providers without
duplicate identities or silent mixing. Combined mode is never the default:
callers must ask for it explicitly.
"""

from __future__ import annotations

import sys
from collections.abc import Iterator
from pathlib import Path

from copilot_session_usage._internal import copilot_cli, core, vscode

PricingRefreshResult = core.PricingRefreshResult

_AGENTS = ("vscode", "cli", "all")


def _check_agent(agent: str, *, allow_all: bool = True) -> None:
    """Validate an ``agent`` value, raising ``ValueError`` for unknown providers."""
    allowed = _AGENTS if allow_all else ("vscode", "cli")
    if agent not in allowed:
        msg = f"unknown agent {agent!r}; expected one of {allowed!r}"
        raise ValueError(msg)


def _default_roots(agent: str) -> list[Path]:
    """Return default discovery roots for a single provider (``vscode`` or ``cli``)."""
    if agent == "cli":
        return copilot_cli.default_session_state_roots()
    return vscode.default_workspace_storage_roots()


def _resolve_auto_refresh(agent: str, auto_refresh: bool | None) -> bool:  # noqa: ARG001
    """Resolve the effective ``auto_refresh`` value.

    Analysis is offline by default for every provider: pricing comes from the
    bundled table (plus any runtime cache already on disk). Only an explicit
    ``auto_refresh=True`` attempts the daily network refresh.
    """
    return bool(auto_refresh)


def _analyze_provider_session(
    session: dict,
    pricing: dict,
    since_ms: int | None = None,
    until_ms: int | None = None,
) -> dict | None:
    """Analyze a session-metadata record produced by either provider's discovery.

    When a call window is given, returns ``None`` for a session with no
    in-window calls (it is not part of that window's report).
    """
    session_dir = Path(session["debug_log_dir"])
    if session.get("provider") == "cli":
        result = copilot_cli.analyze_cli_session(
            session_dir, pricing, since_ms=since_ms, until_ms=until_ms
        )
    else:
        result = core.analyze_session(session_dir, pricing, since_ms=since_ms, until_ms=until_ms)
    if (since_ms is not None or until_ms is not None) and not (
        result.get("total", {}).get("llm_calls")
    ):
        return None
    result["title"] = session.get("title") or result.get("title")
    return result


def _list_recent(
    agent: str,
    roots: list[Path] | None,
    limit: int,
    since_ms: int | None,
    workspace_filter: str | None,
    require_logs: bool = False,
    active_since_ms: int | None = None,
) -> list[dict]:
    """Dispatch ``list_recent_sessions`` to one or both providers and merge results."""
    if agent == "all":
        if roots is not None:
            msg = (
                "workspace_roots override is not supported with agent='all'; "
                "call list_sessions separately per provider, or omit workspace_roots."
            )
            raise ValueError(msg)
        vscode_sessions = vscode.list_recent_sessions(
            vscode.default_workspace_storage_roots(),
            limit=limit,
            since_ms=since_ms,
            workspace_filter=workspace_filter,
            require_logs=require_logs,
            active_since_ms=active_since_ms,
        )
        for s in vscode_sessions:
            s.setdefault("provider", "vscode")
        cli_sessions = copilot_cli.list_recent_sessions(
            copilot_cli.default_session_state_roots(),
            limit=limit,
            since_ms=since_ms,
            workspace_filter=workspace_filter,
            require_logs=require_logs,
            active_since_ms=active_since_ms,
        )
        merged = core.merge_provider_sessions([vscode_sessions, cli_sessions])
        return merged[:limit]

    resolved_roots = roots if roots is not None else _default_roots(agent)
    if agent == "cli":
        sessions = copilot_cli.list_recent_sessions(
            resolved_roots,
            limit=limit,
            since_ms=since_ms,
            workspace_filter=workspace_filter,
            require_logs=require_logs,
            active_since_ms=active_since_ms,
        )
        for s in sessions:
            s.setdefault("provider", "cli")
        return sessions

    sessions = vscode.list_recent_sessions(
        resolved_roots,
        limit=limit,
        since_ms=since_ms,
        workspace_filter=workspace_filter,
        require_logs=require_logs,
        active_since_ms=active_since_ms,
    )
    for s in sessions:
        s.setdefault("provider", "vscode")
    return sessions


def analyze_session(
    path: Path,
    detail: str = "compact",
    agent: str = "vscode",
    *,
    auto_refresh: bool | None = None,
    since: str | None = None,
    until: str | None = None,
) -> dict:
    """Analyze one session by its session path.

    Args:
        path: Path to the session's log directory (VS Code debug-log
            directory, or a Copilot CLI/App session directory or exported
            ``events.jsonl``).
        detail: ``minimal``, ``compact`` (default), or ``full``.
        agent: Provider to use, ``vscode`` (default) or ``cli``. ``all`` is
            not applicable here since a path is inherently provider-specific.
        auto_refresh: Attempt the daily runtime pricing refresh before loading
            pricing. Off by default: analysis never touches the network.
        since: Only count calls at or after this instant (ISO 8601).
        until: Only count calls at or before this instant (ISO 8601).

    Returns:
        Session analysis dict shaped to the requested detail level.

    Raises:
        ValueError: If ``agent`` is ``"all"`` or otherwise unrecognized.
    """
    _check_agent(agent, allow_all=False)
    pricing = core.load_pricing(auto_refresh=_resolve_auto_refresh(agent, auto_refresh))
    since_ms = core.parse_since_to_ms(since) if since else None
    until_ms = core.parse_since_to_ms(until) if until else None
    if agent == "cli":
        result = copilot_cli.analyze_cli_session(
            Path(path), pricing, since_ms=since_ms, until_ms=until_ms
        )
    else:
        result = core.analyze_session(Path(path), pricing, since_ms=since_ms, until_ms=until_ms)
    return core.shape_session(result, detail)


def list_calls(
    path: Path | None = None,
    agent: str = "vscode",
    *,
    workspace_roots: list[Path] | None = None,
    since: str | None = None,
    until: str | None = None,
    name_pattern: str | None = None,
    workspace_filter: str | None = None,
    limit: int = 10_000,
    auto_refresh: bool | None = None,
) -> list[dict]:
    """Return every priced LLM call as a flat list of dicts (the ``calls`` command).

    Each dict has ``session_id``, ``provider``, ``ts``/``ts_ms``, ``model``,
    ``input_tokens`` (includes cache), ``cached_tokens``, ``cache_write_tokens``,
    ``uncached_input_tokens``, ``output_tokens``, ``llm_calls``, ``nano_aiu``,
    ``estimated_usd``, ``cost_source`` (``billed``/``estimated``), ``agent``,
    ``agent_id``, ``initiator``, ``kind`` (``request``/``compaction``) and
    ``skill``. Every aggregate this tool reports is a sum of these records.

    Args:
        path: One session path to export; when omitted, sessions are discovered.
        agent: ``vscode`` (default), ``cli`` or (discovery only) ``all``.
        workspace_roots: Override discovery roots (not with ``agent="all"``).
        since: Only calls at or after this instant (ISO 8601).
        until: Only calls at or before this instant (ISO 8601).
        name_pattern: Only sessions whose title or ID matches this regex.
        workspace_filter: Only sessions from this workspace folder.
        limit: Maximum sessions to read when discovering.
        auto_refresh: Opt in to the daily pricing refresh.

    Returns:
        Calls sorted by ``(ts_ms, session_id)``.
    """
    _check_agent(agent, allow_all=path is None)
    pricing = core.load_pricing(auto_refresh=_resolve_auto_refresh(agent, auto_refresh))
    since_ms = core.parse_since_to_ms(since) if since else None
    until_ms = core.parse_since_to_ms(until) if until else None

    if path is not None:
        sessions = [
            {
                "debug_log_dir": str(path),
                "provider": agent,
                "session_id": Path(path).name,
            }
        ]
    else:
        sessions = _list_recent(
            agent,
            workspace_roots,
            limit,
            None,
            workspace_filter,
            require_logs=True,
            active_since_ms=since_ms,
        )
        if until_ms is not None:
            sessions = [s for s in sessions if int(s.get("created_ms") or 0) <= until_ms]
        if name_pattern:
            sessions = core.filter_sessions_by_name(sessions, name_pattern)

    exported: list[dict] = []
    for session in sessions:
        session_dir = Path(session["debug_log_dir"])
        if not session_dir.exists():
            continue
        if session.get("provider") == "cli":
            canonical_id, calls = copilot_cli.collect_cli_calls_with_id(session_dir)
            session_id = canonical_id
        else:
            calls = core.collect_vscode_session_calls(
                session_dir, core.build_skill_timeline(session_dir)
            )["calls"]
            session_id = session.get("session_id") or session_dir.name
        calls = core.filter_calls_by_window(calls, since_ms, until_ms)
        exported.extend(
            core.session_calls_for_export(
                calls,
                pricing,
                session_id=session_id,
                provider=session.get("provider") or agent,
            )
        )
    exported.sort(key=lambda c: (c["ts_ms"] is None, c["ts_ms"] or 0, c["session_id"] or ""))
    return exported


def iter_calls(*args: object, **kwargs: object) -> Iterator[dict]:
    """Iterate over :func:`list_calls` results (same arguments)."""
    yield from list_calls(*args, **kwargs)  # type: ignore[arg-type]


def list_sessions(
    workspace_roots: list[Path] | None = None,
    limit: int = 20,
    since: str | None = None,
    until: str | None = None,
    name_pattern: str | None = None,
    workspace_filter: str | None = None,
    agent: str = "vscode",
) -> list[dict]:
    """List recent sessions (metadata only, no event-log reads).

    Args:
        workspace_roots: Override discovery roots (workspaceStorage
            directories for ``vscode``, session-state directories for
            ``cli``). Auto-detected if None. Not supported with
            ``agent="all"`` — omit it or call per provider instead.
        limit: Maximum sessions to return.
        since: Only sessions with a call at or after this instant (ISO 8601 with timezone).
        until: Only sessions with a call at or before this instant (ISO 8601 with timezone).
        name_pattern: Only sessions whose title or ID matches this regex.
        workspace_filter: Only sessions from this workspace folder.
        agent: Provider to use: ``vscode`` (default), ``cli``, or the
            explicit opt-in combined mode ``all``.

    Returns:
        List of session metadata dicts, most-recent first.
    """
    _check_agent(agent)
    since_ms = core.parse_since_to_ms(since) if since else None
    until_ms = core.parse_since_to_ms(until) if until else None
    windowed = since_ms is not None or until_ms is not None
    sessions = _list_recent(
        agent,
        workspace_roots,
        sys.maxsize if windowed else limit,
        None,
        workspace_filter,
        active_since_ms=since_ms,
    )
    if until_ms is not None:
        sessions = [s for s in sessions if int(s.get("created_ms") or 0) <= until_ms]
    if name_pattern:
        sessions = core.filter_sessions_by_name(sessions, name_pattern)
    if windowed:
        matched: list[dict] = []
        for session in sessions:
            if len(matched) >= limit:
                break
            if core.session_has_calls_in_window(session, since_ms, until_ms):
                matched.append(session)
        sessions = matched
    return sessions[:limit]


def find_sessions_by_title(
    title: str,
    workspace_roots: list[Path] | None = None,
    agent: str = "vscode",
) -> list[dict]:
    """Fuzzy-match sessions by title substring.

    Args:
        title: Substring to search for (case-insensitive).
        workspace_roots: Override discovery roots. Not supported with
            ``agent="all"``.
        agent: Provider to use: ``vscode`` (default), ``cli``, or ``all``.

    Returns:
        Matching session metadata dicts, most-recent first.
    """
    _check_agent(agent)
    if agent == "all":
        if workspace_roots is not None:
            msg = "workspace_roots override is not supported with agent='all'."
            raise ValueError(msg)
        vscode_matches = vscode.find_sessions_by_title(
            title, vscode.default_workspace_storage_roots()
        )
        for s in vscode_matches:
            s.setdefault("provider", "vscode")
        cli_matches = copilot_cli.find_sessions_by_title(
            title, copilot_cli.default_session_state_roots()
        )
        return core.merge_provider_sessions([vscode_matches, cli_matches])

    roots = workspace_roots if workspace_roots is not None else _default_roots(agent)
    if agent == "cli":
        matches = copilot_cli.find_sessions_by_title(title, roots)
        for s in matches:
            s.setdefault("provider", "cli")
        return matches
    matches = vscode.find_sessions_by_title(title, roots)
    for s in matches:
        s.setdefault("provider", "vscode")
    return matches


def find_session_by_id(
    session_id: str,
    workspace_roots: list[Path] | None = None,
    agent: str = "vscode",
    *,
    auto_refresh: bool | None = None,
) -> dict | None:
    """Analyze a session by its exact UUID.

    Args:
        session_id: The session UUID.
        workspace_roots: Override discovery roots. Not supported with
            ``agent="all"``.
        agent: Provider to use: ``vscode`` (default), ``cli``, or ``all``
            (searches ``vscode`` first, then ``cli``).
        auto_refresh: Attempt the daily runtime pricing refresh before loading
            pricing. Off by default: analysis never touches the network.

    Returns:
        Session analysis dict, or None if not found.
    """
    _check_agent(agent)
    pricing = core.load_pricing(auto_refresh=_resolve_auto_refresh(agent, auto_refresh))

    if agent == "all":
        if workspace_roots is not None:
            msg = "workspace_roots override is not supported with agent='all'."
            raise ValueError(msg)
        vscode_roots = vscode.default_workspace_storage_roots()
        session_dir = vscode.find_session_dir_by_id(session_id, vscode_roots)
        if session_dir is not None:
            result = core.analyze_session(session_dir, pricing)
            meta = vscode.find_session_metadata_by_id(session_id, vscode_roots)
            result["title"] = meta.get("title") if meta else result.get("title")
            return result
        cli_dir = copilot_cli.find_session_dir_by_id(
            session_id, copilot_cli.default_session_state_roots()
        )
        if cli_dir is None:
            return None
        return copilot_cli.analyze_cli_session(cli_dir, pricing)

    roots = workspace_roots if workspace_roots is not None else _default_roots(agent)
    if agent == "cli":
        session_dir = copilot_cli.find_session_dir_by_id(session_id, roots)
        if session_dir is None:
            return None
        return copilot_cli.analyze_cli_session(session_dir, pricing)

    session_dir = vscode.find_session_dir_by_id(session_id, roots)
    if session_dir is None:
        return None
    result = core.analyze_session(session_dir, pricing)
    meta = vscode.find_session_metadata_by_id(session_id, roots)
    result["title"] = meta.get("title") if meta else result.get("title")
    return result


def analyze_latest(
    workspace_roots: list[Path] | None = None,
    detail: str = "compact",
    workspace_filter: str | None = None,
    agent: str = "vscode",
    *,
    auto_refresh: bool | None = None,
) -> dict:
    """Analyze the most recently modified session.

    Args:
        workspace_roots: Override discovery roots. Not supported with
            ``agent="all"``.
        detail: ``minimal``, ``compact`` (default), or ``full``.
        workspace_filter: Only sessions from this workspace folder.
        agent: Provider to use: ``vscode`` (default), ``cli``, or ``all``
            (picks whichever provider's latest session is most recent).
        auto_refresh: Attempt the daily runtime pricing refresh before loading
            pricing. Off by default: analysis never touches the network.

    Returns:
        Session analysis dict shaped to the requested detail level.

    Raises:
        ValueError: If no sessions are found, or an unsupported combination
            of ``agent``/``workspace_roots`` is requested.
    """
    _check_agent(agent)
    pricing = core.load_pricing(auto_refresh=_resolve_auto_refresh(agent, auto_refresh))

    if agent == "all":
        if workspace_roots is not None:
            msg = "workspace_roots override is not supported with agent='all'."
            raise ValueError(msg)
        vscode_roots = vscode.default_workspace_storage_roots()
        cli_roots = copilot_cli.default_session_state_roots()
        vscode_dir = vscode.find_latest_session_dir(vscode_roots, workspace_filter=workspace_filter)
        cli_dir = copilot_cli.find_latest_session_dir(cli_roots, workspace_filter=workspace_filter)
        vscode_mtime = vscode_dir.stat().st_mtime if vscode_dir else -1.0
        cli_mtime = (cli_dir / copilot_cli.EVENTS_FILENAME).stat().st_mtime if cli_dir else -1.0
        if vscode_dir is None and cli_dir is None:
            raise ValueError("No session logs found for either provider.")
        if cli_mtime > vscode_mtime:
            result = copilot_cli.analyze_cli_session(cli_dir, pricing)  # type: ignore[arg-type]
        else:
            result = core.analyze_session(vscode_dir, pricing)  # type: ignore[arg-type]
            meta = vscode.find_session_metadata_by_id(vscode_dir.name, vscode_roots)  # type: ignore[union-attr]
            result["title"] = meta.get("title") if meta else result.get("title")
        return core.shape_session(result, detail)

    roots = workspace_roots if workspace_roots is not None else _default_roots(agent)
    if agent == "cli":
        session_dir = copilot_cli.find_latest_session_dir(roots, workspace_filter=workspace_filter)
        if session_dir is None:
            raise ValueError("No Copilot CLI/App sessions found in session-state root(s).")
        result = copilot_cli.analyze_cli_session(session_dir, pricing)
        return core.shape_session(result, detail)

    session_dir = vscode.find_latest_session_dir(roots, workspace_filter=workspace_filter)
    if session_dir is None:
        raise ValueError("No session debug logs found in workspace storage.")
    result = core.analyze_session(session_dir, pricing)
    session_id = session_dir.name
    meta = vscode.find_session_metadata_by_id(session_id, roots)
    result["title"] = meta.get("title") if meta else result.get("title")
    return core.shape_session(result, detail)


def batch_analyze(
    n: int,
    workspace_roots: list[Path] | None = None,
    detail: str = "compact",
    since: str | None = None,
    workspace_filter: str | None = None,
    agent: str = "vscode",
    *,
    auto_refresh: bool | None = None,
    until: str | None = None,
) -> dict:
    """Analyze the N most recent sessions.

    Args:
        n: Number of sessions to analyze.
        workspace_roots: Override discovery roots. Not supported with
            ``agent="all"``.
        detail: ``minimal``, ``compact`` (default), or ``full``.
        since: Only count calls at or after this instant (ISO 8601). Sessions
            with no call in the window are omitted.
        workspace_filter: Only sessions from this workspace folder.
        agent: Provider to use: ``vscode`` (default), ``cli``, or the
            explicit opt-in combined mode ``all``.
        auto_refresh: Attempt the daily runtime pricing refresh before loading
            pricing. Off by default: analysis never touches the network.
        until: Only count calls at or before this instant (ISO 8601).

    Returns:
        Dict with ``schema_version``, ``summary`` (aggregate) and ``sessions``
        (per-session list).
    """
    _check_agent(agent)
    since_ms = core.parse_since_to_ms(since) if since else None
    until_ms = core.parse_since_to_ms(until) if until else None
    sessions = _list_recent(
        agent,
        workspace_roots,
        n,
        None,
        workspace_filter,
        require_logs=True,
        active_since_ms=since_ms,
    )
    if until_ms is not None:
        sessions = [s for s in sessions if (s.get("created_ms") or 0) <= until_ms]
    pricing = core.load_pricing(auto_refresh=_resolve_auto_refresh(agent, auto_refresh))
    results: list[dict] = []
    for session in sessions:
        session_dir = Path(session["debug_log_dir"])
        if not session_dir.exists():
            continue
        result = _analyze_provider_session(session, pricing, since_ms, until_ms)
        if result is not None:
            results.append(result)
    return core.shape_batch(results, detail)


def aggregate_sessions(results: list[dict]) -> dict:
    """Aggregate multiple session analyses into a single flat summary.

    Args:
        results: Full session analysis dicts (e.g. from ``analyze_session``).
            Providers may be mixed here since aggregation is purely numeric
            and the caller has already made an explicit choice to combine
            them (e.g. via ``agent="all"``).

    Returns:
        Dict with ``session_count``; token fields (``input_tokens`` includes
        cache reads and writes, ``cached_tokens``, ``cache_write_tokens``,
        ``uncached_input_tokens``, ``output_tokens``); ``llm_calls``;
        ``estimated_usd`` and ``cost_source``; a weighted ``cache_ratio``;
        ``compaction``; ``reconciliation``; and ``model_split`` whose USD
        always sums to ``estimated_usd``.
    """
    return core.aggregate_sessions(results)


def load_pricing(ref_dir: Path | None = None, *, auto_refresh: bool = False) -> dict:
    """Load pricing data.

    Args:
        ref_dir: Directory containing pricing YAML files. If None, uses
            the newest valid user snapshot or the bundled data directory
            shipped with the package.
        auto_refresh: Attempt the daily runtime pricing refresh when ``ref_dir``
            is None. Set to false for offline or tightly controlled callers.

    Returns:
        Pricing dict with model rates.
    """
    return core.load_pricing(ref_dir, auto_refresh=auto_refresh)


def refresh_pricing(force: bool = False) -> PricingRefreshResult:
    """Refresh the user pricing snapshot from GitHub.

    Args:
        force: Bypass the normal rolling 24-hour refresh limit.

    Returns:
        A typed result describing whether pricing was updated, unchanged,
        skipped, or unavailable.
    """
    return core.refresh_pricing(force=force)


def pricing_status() -> dict:
    """Return the runtime pricing cache location and refresh metadata."""
    return core.pricing_status()
