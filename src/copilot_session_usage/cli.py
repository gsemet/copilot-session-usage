"""Click CLI entry point for copilot-session-usage."""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

import click

from copilot_session_usage._internal import copilot_cli, core, git, vscode

CONTEXT_SETTINGS = {"help_option_names": ["-h", "--help"]}


@click.group(context_settings=CONTEXT_SETTINGS)
@click.option(
    "--workspace-storage",
    "workspace_storage",
    metavar="PATH",
    help=(
        "Override workspaceStorage directory (auto-detected by default). "
        "Required on WSL2 when VS Code runs on the Windows host. Used by --agent vscode/all."
    ),
)
@click.option(
    "--session-root",
    "session_root",
    metavar="PATH",
    help=(
        "Override the Copilot CLI/App session-state root (auto-detected by default; "
        "normally ~/.copilot/session-state). Used by --agent cli/all."
    ),
)
@click.option(
    "--agent",
    "agent",
    type=click.Choice(("vscode", "cli", "all")),
    default="vscode",
    show_default=True,
    help=(
        "Provider for session discovery: 'vscode' (VS Code Copilot Chat debug logs), "
        "'cli' (Copilot CLI/Copilot App local sessions), or the explicit opt-in combined "
        "mode 'all' (discovers and dedups sessions from each provider by UUID)."
    ),
)
@click.pass_context
def cli(
    ctx: click.Context,
    workspace_storage: str | None,
    session_root: str | None,
    agent: str,
) -> None:
    """Extract Copilot session cost KPIs from local VS Code and Copilot CLI/App logs.

    Reads JSONL logs written by the VS Code Copilot Chat extension
    (workspaceStorage debug logs) and/or by Copilot CLI / the Copilot App
    (``~/.copilot/session-state/<uuid>/events.jsonl``) to compute per-session
    token counts, estimated USD spend, model breakdowns, duration, and
    skill/tool attribution.

    Sessions are auto-discovered per --agent: from VS Code workspaceStorage
    (override with --workspace-storage), from the Copilot CLI/App
    session-state root (override with --session-root), or from both
    explicitly with --agent all. Use the subcommands below to analyze
    individual sessions, the latest session, or batches.

    Output is controlled by --detail (minimal / compact / full) and
    --format (table / json / detailed). Key capabilities include per-model
    pricing with cache-hit discounts, threshold-aware tier switching for
    long-context models, multi-model session handling, subagent/skill/tool
    cost attribution, and cross-platform support (macOS, Linux, Windows, WSL2).
    """
    ctx.ensure_object(dict)
    ctx.obj["workspace_storage"] = workspace_storage
    ctx.obj["session_root"] = session_root
    ctx.obj["agent"] = agent


def _provider_roots(ctx: click.Context) -> dict[str, list[Path]]:
    """Resolve discovery roots for the active agent(s) from CLI context."""
    agent = ctx.obj.get("agent", "vscode")
    roots: dict[str, list[Path]] = {}
    if agent == "all":
        workspace_storage = ctx.obj.get("workspace_storage")
        if workspace_storage:
            workspace_root = Path(workspace_storage)
            if workspace_root.is_dir():
                roots["vscode"] = [workspace_root]
        else:
            vscode_roots = vscode.default_workspace_storage_roots()
            if vscode_roots:
                roots["vscode"] = vscode_roots

        session_root = ctx.obj.get("session_root")
        if session_root:
            cli_root = Path(session_root)
            if cli_root.is_dir():
                roots["cli"] = [cli_root]
        else:
            cli_roots = copilot_cli.default_session_state_roots()
            if cli_roots:
                roots["cli"] = cli_roots
        return roots

    if agent == "vscode":
        roots["vscode"] = vscode.resolve_ws_roots(ctx.obj.get("workspace_storage"))
    else:
        roots["cli"] = copilot_cli.resolve_session_state_roots(ctx.obj.get("session_root"))
    return roots


def _discover_sessions(
    ctx: click.Context,
    *,
    limit: int,
    since_ms: int | None = None,
    workspace_filter: str | None = None,
    require_logs: bool = False,
) -> list[dict]:
    """Discover session metadata across the active provider(s), tagged and deduped."""
    roots = _provider_roots(ctx)
    lists: list[list[dict]] = []
    if "vscode" in roots:
        sessions = vscode.list_recent_sessions(
            roots["vscode"],
            limit=limit,
            since_ms=since_ms,
            workspace_filter=workspace_filter,
            require_logs=require_logs,
        )
        for s in sessions:
            s.setdefault("provider", "vscode")
        lists.append(sessions)
    if "cli" in roots:
        sessions = copilot_cli.list_recent_sessions(
            roots["cli"],
            limit=limit,
            since_ms=since_ms,
            workspace_filter=workspace_filter,
            require_logs=require_logs,
        )
        for s in sessions:
            s.setdefault("provider", "cli")
        lists.append(sessions)
    if len(lists) == 1:
        return lists[0][:limit]
    return core.merge_provider_sessions(lists)[:limit]


def _load_pricing_for_agent(agent: str) -> dict:
    """Load pricing, keeping CLI/App and combined-mode analysis local-only by default.

    The ``vscode`` provider preserves its historical behavior (a throttled
    daily runtime pricing refresh attempt). The ``cli`` provider and the
    combined ``all`` mode default to no network access, matching the CLI/App
    integration's local-only design; use ``pricing refresh`` to opt into an
    explicit network refresh.
    """
    return core.load_pricing(auto_refresh=(agent == "vscode"))


def _analyze_session_record(session: dict, pricing: dict) -> dict:
    """Analyze a session-metadata record produced by either provider's discovery."""
    session_dir = Path(session["debug_log_dir"])
    if session.get("provider") == "cli":
        result = copilot_cli.analyze_cli_session(session_dir, pricing)
    else:
        result = core.analyze_session(session_dir, pricing)
    result["title"] = session.get("title") or result.get("title")
    result["provider"] = session.get("provider", result.get("provider", "vscode"))
    return result


def _analyze_path(agent: str, path: Path, pricing: dict) -> dict:
    """Analyze a single session by explicit PATH, honoring --agent (not 'all')."""
    if agent == "all":
        msg = "PATH-based analysis requires a single provider; pass --agent vscode or --agent cli."
        raise click.ClickException(msg)
    if agent == "cli":
        try:
            return copilot_cli.analyze_cli_session(path, pricing)
        except ValueError as exc:
            raise click.ClickException(str(exc)) from exc
    return core.analyze_session(path, pricing)


def _find_session_dir_by_id(ctx: click.Context, session_id: str) -> tuple[Path, str] | None:
    """Search the active provider(s) for a session directory by UUID."""
    roots = _provider_roots(ctx)
    if "vscode" in roots:
        session_dir = vscode.find_session_dir_by_id(session_id, roots["vscode"])
        if session_dir is not None:
            return session_dir, "vscode"
    if "cli" in roots:
        session_dir = copilot_cli.find_session_dir_by_id(session_id, roots["cli"])
        if session_dir is not None:
            return session_dir, "cli"
    return None


def _find_latest_session_dir(
    ctx: click.Context, workspace_filter: str | None
) -> tuple[Path, str] | None:
    """Find the most recently modified session directory across the active provider(s)."""
    roots = _provider_roots(ctx)
    candidates: list[tuple[float, Path, str]] = []
    if "vscode" in roots:
        found = vscode.find_latest_session_dir(roots["vscode"], workspace_filter=workspace_filter)
        if found is not None:
            candidates.append((found.stat().st_mtime, found, "vscode"))
    if "cli" in roots:
        found = copilot_cli.find_latest_session_dir(roots["cli"], workspace_filter=workspace_filter)
        if found is not None:
            candidates.append(((found / copilot_cli.EVENTS_FILENAME).stat().st_mtime, found, "cli"))
    if not candidates:
        return None
    candidates.sort(key=lambda c: c[0], reverse=True)
    _, path, provider = candidates[0]
    return path, provider


def _find_sessions_by_title(ctx: click.Context, title: str) -> list[dict]:
    """Search the active provider(s) for sessions whose title matches ``title``."""
    roots = _provider_roots(ctx)
    lists: list[list[dict]] = []
    if "vscode" in roots:
        matches = vscode.find_sessions_by_title(title, roots["vscode"])
        for m in matches:
            m.setdefault("provider", "vscode")
        lists.append(matches)
    if "cli" in roots:
        matches = copilot_cli.find_sessions_by_title(title, roots["cli"])
        for m in matches:
            m.setdefault("provider", "cli")
        lists.append(matches)
    if len(lists) == 1:
        return lists[0]
    return core.merge_provider_sessions(lists)


def _apply_query(payload: object, query: str | None) -> object:
    """Extract a field from a payload when --query is used."""
    if not query:
        return payload
    if isinstance(payload, list):
        return [
            core.query_json_path(item, query) if isinstance(item, dict) else None
            for item in payload
        ]
    if isinstance(payload, dict):
        return core.query_json_path(payload, query)
    return None


def _format_refresh_timestamp(value: datetime) -> str:
    """Format a refresh timestamp for concise human-readable CLI output."""
    timestamp = value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    return timestamp.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def _format_display_path(path: Path) -> str:
    """Replace the user's home directory with ``~`` when displaying a path."""
    try:
        return f"~/{path.relative_to(Path.home())}"
    except ValueError:
        return str(path)


def _format_refresh_source(source: str) -> str:
    """Use a short name for the known upstream pricing source."""
    if source.startswith("https://raw.githubusercontent.com/github/docs/"):
        return "GitHub Copilot rate card"
    return _format_display_path(Path(source))


def _emit_refresh_result(result: core.PricingRefreshResult) -> None:
    """Print a human-readable refresh report and convert failures to Click errors."""
    status_labels = {
        "updated": "Updated",
        "unchanged": "Already current",
        "skipped": "Skipped (attempted within 24 hours)",
        "failed": "Failed",
    }

    click.echo("Pricing refresh")
    click.echo(f"Result           {status_labels.get(result.status, result.status)}")
    click.echo(f"Attempted        {_format_refresh_timestamp(result.attempted_at)}")
    if result.captured_at:
        click.echo(f"Latest refresh   {_format_refresh_timestamp(result.captured_at)}")
    if result.model_count is not None:
        click.echo(f"Models           {result.model_count}")
    click.echo(f"Source           {_format_refresh_source(result.source)}")
    if result.path:
        click.echo(f"Cache file       {_format_display_path(result.path)}")
    if result.lock_path:
        click.echo(f"Metadata file    {_format_display_path(result.lock_path)}")
    if result.checksum:
        click.echo(f"Checksum         {result.checksum}")
    if result.error:
        raise click.ClickException(result.error)


@cli.group(name="pricing")
def pricing_group() -> None:
    """Inspect and refresh the runtime GitHub Copilot pricing snapshot."""


@pricing_group.command(name="refresh")
@click.option("--force", is_flag=True, help="Refresh even if an attempt occurred within 24 hours.")
def refresh_pricing_command(force: bool) -> None:
    """Refresh the user pricing snapshot from GitHub."""
    _emit_refresh_result(core.refresh_pricing(force=force))


@pricing_group.command(name="status")
def pricing_status_command() -> None:
    """Show the runtime pricing cache location and refresh metadata."""
    status = core.pricing_status()
    for key, value in status.items():
        click.echo(f"{key}: {value}")


@cli.command(name="refresh-pricing")
@click.option("--force", is_flag=True, help="Refresh even if an attempt occurred within 24 hours.")
def refresh_pricing_alias(force: bool) -> None:
    """Compatibility alias for ``pricing refresh``."""
    _emit_refresh_result(core.refresh_pricing(force=force))


def _shape_analysis_result(
    result: dict,
    *,
    detail: str,
    format_: str,
    summary: bool,
    skill_breakdown: bool,
    tool_breakdown: bool,
    skill_name: str | None,
) -> object:
    """Shape a single-session analysis result based on CLI flags."""
    if summary:
        return core.compute_efficiency_summary(result)
    if skill_breakdown:
        return core.shape_session_skill_breakdown(result)
    if tool_breakdown:
        return core.shape_session_tool_breakdown(result)
    if skill_name:
        normalized = core._normalize_skill_name(skill_name)
        shaped = core.shape_session_minimal_skill(result, normalized)
        if shaped is None:
            raise click.ClickException(f"skill {skill_name!r} not found in session.")
        return shaped
    detail = core.resolve_detail(detail, format_)
    return core.shape_session(result, detail)


@cli.command()
@core.analysis_options
@core.skill_breakdown_option
@core.tool_breakdown_option
@core.skill_filter_option
@core.title_filter_option
@core.latest_option
@click.option(
    "--name",
    metavar="REGEX",
    help="Analyze sessions whose title matches REGEX (case-insensitive).",
)
@click.option(
    "--since", metavar="DATE", help="Only sessions created after DATE (ISO 8601 with timezone)."
)
@click.option(
    "--until", metavar="DATE", help="Only sessions created before DATE (ISO 8601 with timezone)."
)
@click.option(
    "--workspace", metavar="PATH", help="Only consider sessions from this workspace folder."
)
@click.option(
    "--aggregate",
    is_flag=True,
    help="Aggregate all matching sessions into a single summary.",
)
@click.option(
    "--summary",
    is_flag=True,
    help="Output a cost-efficiency summary instead of the full session report.",
)
@click.option(
    "--query",
    metavar="PATH",
    help="Extract a single field using dot notation (e.g. .total.estimated_usd).",
)
@click.option(
    "--query-help",
    is_flag=True,
    help="Print a reference of queryable fields and exit.",
)
@click.argument("log_dir", required=False, metavar="PATH")
@click.pass_context
def analyze(
    ctx: click.Context,
    log_dir: str | None,
    detail: str,
    format_: str,
    output_path: str | None,
    skill_breakdown: bool,
    tool_breakdown: bool,
    skill_name: str | None,
    title_filter: str | None,
    latest: bool,
    name: str | None,
    since: str | None,
    until: str | None,
    workspace: str | None,
    aggregate: bool,
    summary: bool,
    query: str | None,
    query_help: bool,
) -> None:
    """Analyze a single session by PATH, or many sessions by --name regex.

    PATH is the fastest path: no discovery needed. When --name is given
    instead, sessions are discovered from workspace storage, filtered by
    the regex and optional date range, and analyzed in one pass. Use
    --aggregate to roll them up into a single efficiency summary.
    """
    if query_help:
        fields = core.get_queryable_fields()
        lines = ["Queryable fields for --query:", ""]
        for path, description in fields.items():
            lines.append(f"  {path:<40} {description}")
        click.echo("\n".join(lines))
        return

    if log_dir and (name or title_filter):
        raise click.ClickException("Provide either PATH or --name/--title, not both.")
    if not log_dir and not name and not title_filter:
        raise click.ClickException("Provide a PATH or --name regex or --title substring.")

    out_path = Path(output_path) if output_path else None
    pricing = _load_pricing_for_agent(ctx.obj.get("agent", "vscode"))

    if log_dir:
        session_dir = Path(log_dir)
        if not session_dir.exists():
            msg = f"log directory not found: {session_dir}"
            raise click.ClickException(msg)
        result = _analyze_path(ctx.obj.get("agent", "vscode"), session_dir, pricing)
        shaped = _shape_analysis_result(
            result,
            detail=detail,
            format_=format_,
            summary=summary,
            skill_breakdown=skill_breakdown,
            tool_breakdown=tool_breakdown,
            skill_name=skill_name,
        )
        output = _apply_query(shaped, query)
        core.emit(output, core.normalize_format(format_), out_path)
        return

    since_ms = core.parse_since_to_ms(since) if since else None
    sessions = _discover_sessions(
        ctx, limit=1000, since_ms=since_ms, workspace_filter=workspace, require_logs=True
    )
    if until:
        until_ms = core.parse_since_to_ms(until)
        if until_ms is not None:
            sessions = [s for s in sessions if (s.get("created_ms") or 0) <= until_ms]
    if title_filter:
        sessions = [s for s in sessions if title_filter.lower() in (s.get("title") or "").lower()]
    if name:
        try:
            sessions = core.filter_sessions_by_name(sessions, name)
        except ValueError as exc:
            raise click.ClickException(str(exc)) from exc
    if not sessions:
        raise click.ClickException("no sessions matched the given filters.")

    if latest:
        sessions = [sessions[0]]

    results: list[dict] = []
    for session in sessions:
        session_dir = Path(session["debug_log_dir"])
        if not session_dir.exists():
            continue
        results.append(_analyze_session_record(session, pricing))

    payload: object
    if aggregate:
        payload = core.aggregate_sessions(results)
    elif summary:
        payload = [core.compute_efficiency_summary(r) for r in results]
    elif skill_breakdown:
        payload = [core.shape_session_skill_breakdown(r) for r in results]
    elif tool_breakdown:
        payload = [core.shape_session_tool_breakdown(r) for r in results]
    elif skill_name:
        normalized = core._normalize_skill_name(skill_name)
        payload = [
            core.shape_session_minimal_skill(r, normalized)
            for r in results
            if core.shape_session_minimal_skill(r, normalized) is not None
        ]
        if not payload:
            raise click.ClickException(f"skill {skill_name!r} not found in any matching session.")
    else:
        detail = core.resolve_detail(detail, format_)
        payload = [core.shape_session(r, detail) for r in results]

    payload = _apply_query(payload, query)
    core.emit(payload, core.normalize_format(format_), out_path)


@cli.command()
@core.analysis_options
@click.option(
    "--workspace", metavar="PATH", help="Only consider sessions from this workspace folder."
)
@click.pass_context
def latest(
    ctx: click.Context,
    workspace: str | None,
    detail: str,
    format_: str,
    output_path: str | None,
) -> None:
    """Analyze the most recently modified session across all workspaces."""
    found = _find_latest_session_dir(ctx, workspace)
    if not found:
        msg = "no session logs found for the active provider(s)."
        raise click.ClickException(msg)
    session_dir, provider = found
    pricing = _load_pricing_for_agent(ctx.obj.get("agent", "vscode"))
    if provider == "cli":
        result = copilot_cli.analyze_cli_session(session_dir, pricing)
    else:
        result = core.analyze_session(session_dir, pricing)
        ws_roots = vscode.resolve_ws_roots(ctx.obj.get("workspace_storage"))
        meta = vscode.find_session_metadata_by_id(session_dir.name, ws_roots)
        result["title"] = meta.get("title") if meta else result.get("title")
    detail = core.resolve_detail(detail, format_)
    out_path = Path(output_path) if output_path else None
    core.emit(
        core.shape_session(result, detail),
        core.normalize_format(format_),
        out_path,
    )


@cli.command(name="find")
@core.analysis_options
@click.option(
    "--workspace",
    metavar="PATH",
    help="Only consider sessions from this workspace folder.",
)
@click.argument("title")
@click.pass_context
def find_by_title(
    ctx: click.Context,
    title: str,
    workspace: str | None,
    detail: str,
    format_: str,
    output_path: str | None,
) -> None:
    """Find and analyze a session by TITLE (case-insensitive substring match).

    If more than one session matches, candidates are printed and the command
    exits with an error — re-run with `id <SESSION_ID>` to pick one.
    """
    matches = _find_sessions_by_title(ctx, title)
    if workspace:
        matches = [m for m in matches if workspace in m.get("workspace_folder", "")]
    if not matches:
        msg = f"no sessions found matching title: {title!r}"
        raise click.ClickException(msg)
    if len(matches) > 1:
        click.echo(f"Multiple sessions match {title!r}:", err=True)
        for m in matches[:10]:
            ts = core.ts_to_iso(m.get("created_ms")) or "unknown"
            click.echo(f"  {ts}  {m['title']!r}  (id: {m['session_id']})", err=True)
        click.echo("Re-run with: copilot-session-usage id <SESSION_ID>", err=True)
        sys.exit(1)
    match = matches[0]
    session_dir = Path(match["debug_log_dir"])
    if not session_dir.exists():
        msg = f"session logs not present at: {session_dir}"
        raise click.ClickException(msg)
    pricing = _load_pricing_for_agent(ctx.obj.get("agent", "vscode"))
    result = _analyze_session_record(match, pricing)
    detail = core.resolve_detail(detail, format_)
    out_path = Path(output_path) if output_path else None
    core.emit(
        core.shape_session(result, detail),
        core.normalize_format(format_),
        out_path,
    )


@cli.command(name="id")
@core.analysis_options
@core.skill_breakdown_option
@core.tool_breakdown_option
@core.skill_filter_option
@click.argument("session_id")
@click.pass_context
def analyze_by_id(
    ctx: click.Context,
    session_id: str,
    detail: str,
    format_: str,
    output_path: str | None,
    skill_breakdown: bool,
    tool_breakdown: bool,
    skill_name: str | None,
) -> None:
    """Analyze a session by its exact SESSION_ID (UUID)."""
    found = _find_session_dir_by_id(ctx, session_id)
    if not found:
        msg = f"no session logs found for session ID: {session_id}"
        raise click.ClickException(msg)
    session_dir, provider = found
    pricing = _load_pricing_for_agent(ctx.obj.get("agent", "vscode"))
    if provider == "cli":
        result = copilot_cli.analyze_cli_session(session_dir, pricing)
    else:
        result = core.analyze_session(session_dir, pricing)
        ws_roots = vscode.resolve_ws_roots(ctx.obj.get("workspace_storage"))
        meta = vscode.find_session_metadata_by_id(session_id, ws_roots)
        result["title"] = meta.get("title") if meta else result.get("title")
    shaped = _shape_analysis_result(
        result,
        detail=detail,
        format_=format_,
        summary=False,
        skill_breakdown=skill_breakdown,
        tool_breakdown=tool_breakdown,
        skill_name=skill_name,
    )
    out_path = Path(output_path) if output_path else None
    core.emit(shaped, core.normalize_format(format_), out_path)


@cli.command(name="list")
@core.format_option
@core.output_option
@click.option(
    "--limit",
    type=int,
    default=20,
    show_default=True,
    help="Max sessions to return.",
)
@click.option(
    "--since", metavar="DATE", help="Only sessions created after DATE (ISO 8601 with timezone)."
)
@click.option(
    "--until", metavar="DATE", help="Only sessions created before DATE (ISO 8601 with timezone)."
)
@click.option(
    "--workspace", metavar="PATH", help="Only consider sessions from this workspace folder."
)
@click.option("--name", metavar="REGEX", help="Only sessions whose title or ID matches REGEX.")
@click.option(
    "--title",
    "title_filter",
    metavar="SUBSTRING",
    help="Only sessions whose title contains SUBSTRING (case-insensitive).",
)
@click.option(
    "--dir",
    "dir_path",
    metavar="PATH",
    help="List sessions from this debug-logs directory instead of workspace storage.",
)
@click.option(
    "--costs",
    is_flag=True,
    help="Analyze each session and include cost columns (implied by --dir).",
)
@click.pass_context
def list_sessions(
    ctx: click.Context,
    limit: int,
    since: str | None,
    until: str | None,
    workspace: str | None,
    name: str | None,
    title_filter: str | None,
    dir_path: str | None,
    costs: bool,
    format_: str,
    output_path: str | None,
) -> None:
    """List recent sessions with optional cost analysis.

    Without --dir, sessions are discovered from the active --agent's default
    roots (VS Code workspace storage, the Copilot CLI/App session-state
    root, or all). With --dir, PATH is scanned for session directories in
    the active --agent's layout instead: VS Code debug-log session
    directories for --agent vscode (the default), or Copilot CLI/App
    ``<uuid>/events.jsonl`` session directories for --agent cli. --dir
    requires a single provider; it is not supported with --agent all.
    """
    out_path = Path(output_path) if output_path else None
    analyze_sessions = costs or bool(dir_path)
    pricing = _load_pricing_for_agent(ctx.obj.get("agent", "vscode"))

    if dir_path:
        debug_dir = Path(dir_path)
        if not debug_dir.exists():
            msg = f"directory not found: {debug_dir}"
            raise click.ClickException(msg)
        agent = ctx.obj.get("agent", "vscode")
        if agent == "all":
            msg = (
                "listing --dir sessions requires a single provider; pass --agent vscode or "
                "--agent cli."
            )
            raise click.ClickException(msg)
        if agent == "cli":
            since_ms = core.parse_since_to_ms(since) if since else None
            # Treat PATH as a Copilot CLI session-root override (a directory
            # of <uuid>/events.jsonl session directories), not the VS Code
            # debug-logs layout used below.
            sessions = copilot_cli.list_recent_sessions(
                [debug_dir], limit=limit, since_ms=since_ms, workspace_filter=workspace
            )
        else:
            sessions = core.list_session_dirs(debug_dir)
            for s in sessions:
                s.setdefault("provider", "vscode")
    else:
        since_ms = core.parse_since_to_ms(since) if since else None
        sessions = _discover_sessions(
            ctx, limit=limit, since_ms=since_ms, workspace_filter=workspace
        )

    if until:
        until_ms = core.parse_since_to_ms(until)
        if until_ms is not None:
            sessions = [s for s in sessions if (s.get("created_ms") or 0) <= until_ms]
    if title_filter:
        sessions = [s for s in sessions if title_filter.lower() in (s.get("title") or "").lower()]
    if name:
        try:
            sessions = core.filter_sessions_by_name(sessions, name)
        except ValueError as exc:
            raise click.ClickException(str(exc)) from exc

    if analyze_sessions:
        analyzed: list[dict] = []
        for session in sessions:
            session_dir = Path(session["debug_log_dir"])
            if not session_dir.exists():
                continue
            analyzed.append(_analyze_session_record(session, pricing))
        sessions = analyzed

    core.emit(sessions, core.normalize_format(format_), out_path, costed_list=analyze_sessions)


@cli.command()
@core.analysis_options
@core.title_filter_option
@click.option(
    "--since", metavar="DATE", help="Only sessions created after DATE (ISO 8601 with timezone)."
)
@click.option(
    "--until", metavar="DATE", help="Only sessions created before DATE (ISO 8601 with timezone)."
)
@click.option(
    "--workspace", metavar="PATH", help="Only consider sessions from this workspace folder."
)
@click.option("--name", metavar="REGEX", help="Only sessions whose title or ID matches REGEX.")
@click.argument("count", type=int, metavar="N")
@click.pass_context
def batch(
    ctx: click.Context,
    count: int,
    since: str | None,
    until: str | None,
    workspace: str | None,
    name: str | None,
    title_filter: str | None,
    detail: str,
    format_: str,
    output_path: str | None,
) -> None:
    """Analyze the N most recent sessions in one invocation.

    Always returns {"summary": {...}, "sessions": [...]}: a pre-computed
    aggregate across all N sessions plus a per-session array shaped by
    --detail. Much faster than N separate `id` invocations.
    """
    since_ms = core.parse_since_to_ms(since) if since else None
    sessions = _discover_sessions(
        ctx, limit=count, since_ms=since_ms, workspace_filter=workspace, require_logs=True
    )
    if until:
        until_ms = core.parse_since_to_ms(until)
        if until_ms is not None:
            sessions = [s for s in sessions if (s.get("created_ms") or 0) <= until_ms]
    if title_filter:
        sessions = [s for s in sessions if title_filter.lower() in (s.get("title") or "").lower()]
    if name:
        try:
            sessions = core.filter_sessions_by_name(sessions, name)
        except ValueError as exc:
            raise click.ClickException(str(exc)) from exc
    pricing = _load_pricing_for_agent(ctx.obj.get("agent", "vscode"))
    results: list[dict] = []
    for session in sessions:
        session_dir = Path(session["debug_log_dir"])
        if not session_dir.exists():
            continue
        results.append(_analyze_session_record(session, pricing))
    detail = core.resolve_detail(detail, format_)
    out_path = Path(output_path) if output_path else None
    core.emit(core.shape_batch(results, detail), core.normalize_format(format_), out_path)


@cli.command()
@core.format_option
@core.output_option
@core.title_filter_option
@click.option(
    "--last",
    "last_window",
    metavar="DURATION",
    help="Only sessions started within the last DURATION (e.g. 7d, 24h, 30m).",
)
@click.option(
    "--since", metavar="DATE", help="Only sessions created after DATE (ISO 8601 with timezone)."
)
@click.option(
    "--until", metavar="DATE", help="Only sessions created before DATE (ISO 8601 with timezone)."
)
@click.option(
    "--workspace", metavar="PATH", help="Only consider sessions from this workspace folder."
)
@click.option("--name", metavar="REGEX", help="Only sessions whose title or ID matches REGEX.")
@click.option(
    "--limit",
    type=click.IntRange(min=1),
    default=1000,
    show_default=True,
    help="Maximum number of sessions to inspect.",
)
@click.pass_context
def span(
    ctx: click.Context,
    last_window: str | None,
    since: str | None,
    until: str | None,
    workspace: str | None,
    name: str | None,
    title_filter: str | None,
    limit: int,
    format_: str,
    output_path: str | None,
) -> None:
    """Emit a compact total/model/session report for a date span.

    This is the preferred machine-readable report for multi-session analysis:
    it omits full skills, subagents, diagnostics, and pricing prose.
    """
    since_ms = core.parse_since_to_ms(since) if since else None
    if last_window:
        since_ms = core.parse_last_window_to_ms(last_window)
        if since_ms is None:
            raise click.ClickException(
                f"invalid --last value: {last_window!r}. Use e.g. 7d, 24h, 30m."
            )
    sessions = _discover_sessions(
        ctx, limit=limit, since_ms=since_ms, workspace_filter=workspace, require_logs=True
    )
    if until:
        until_ms = core.parse_since_to_ms(until)
        if until_ms is not None:
            sessions = [s for s in sessions if (s.get("created_ms") or 0) <= until_ms]
    if title_filter:
        sessions = [s for s in sessions if title_filter.lower() in (s.get("title") or "").lower()]
    if name:
        try:
            sessions = core.filter_sessions_by_name(sessions, name)
        except ValueError as exc:
            raise click.ClickException(str(exc)) from exc

    pricing = _load_pricing_for_agent(ctx.obj.get("agent", "vscode"))
    results: list[dict] = []
    for session in sessions:
        session_dir = Path(session["debug_log_dir"])
        if session_dir.exists():
            results.append(_analyze_session_record(session, pricing))
    payload = core.shape_span_report(
        results,
        since=since,
        until=until,
        last=last_window,
    )
    out_path = Path(output_path) if output_path else None
    core.emit(payload, core.normalize_format(format_), out_path)


@cli.command(name="amend-commit")
@click.option(
    "--session-id",
    "session_ids",
    multiple=True,
    metavar="UUID",
    help="Session UUID to inject cost trailers for. May be given multiple times.",
)
@click.option(
    "--with-session-id",
    "with_session_id",
    is_flag=True,
    help="Also inject a Copilot-Session-Usage-Session-ID trailer per session ID.",
)
@click.option(
    "--repo",
    "repo_path",
    metavar="PATH",
    help="Path to the git repository (default: current directory).",
)
@click.option(
    "--dry-run",
    is_flag=True,
    help="Print the trailers that would be injected without amending the commit.",
)
@click.pass_context
def amend_commit(
    ctx: click.Context,
    session_ids: tuple[str, ...],
    with_session_id: bool,
    repo_path: str | None,
    dry_run: bool,
) -> None:
    """Amend HEAD to inject accumulated session cost trailers.

    Reads the VS Code Copilot debug logs for the given session IDs, computes
    the accumulated per-model token counts, and amends the HEAD commit with
    one ``Copilot-Session-Usage-Acc`` trailer per model plus a
    ``Copilot-Session-Usage-AIC`` trailer with the total estimated cost.

    When several ``--session-id`` values are provided, their costs and token
    counts are merged before the trailers are built. This is useful when a
    single coding change spanned multiple VS Code Copilot sessions.

    Pass ``--with-session-id`` to also burn one
    ``Copilot-Session-Usage-Session-ID`` trailer per session ID. This makes
    it easier to rewrite commit history with commit-accurate costs later.

    The current session ID is available to Copilot agents through the
    ``VSCODE_TARGET_SESSION_LOG`` template variable in the editor context
    (it is *not* an environment variable). Extract the UUID from that path
    and pass it with ``--session-id``.

    Use ``--dry-run`` to preview the trailers without touching the commit.
    """
    if not session_ids:
        raise click.ClickException(
            "No session ID provided. Pass --session-id or use the "
            "VSCODE_TARGET_SESSION_LOG value from the Copilot context."
        )

    if repo_path:
        repo = Path(repo_path)
        if not repo.exists():
            raise click.ClickException(f"path not found: {repo}")
        if not git.is_git_repository(cwd=repo):
            raise click.ClickException(f"not a git repository: {repo}")
    else:
        if not git.is_git_repository():
            raise click.ClickException("not inside a git repository.")
        repo = None

    ws_roots = vscode.resolve_ws_roots(ctx.obj.get("workspace_storage"))
    session_dirs: list[Path] = []
    for sid in session_ids:
        session_dir = vscode.find_session_dir_by_id(sid, ws_roots)
        if not session_dir:
            msg = f"no debug logs found for session ID: {sid}"
            raise click.ClickException(msg)
        session_dirs.append(session_dir)

    pricing = core.load_pricing()
    results = [core.analyze_session(session_dir, pricing) for session_dir in session_dirs]
    merged = core.merge_session_results(results)
    merged = core.shape_session(merged, "full")
    acc_trailers = core.build_session_usage_acc_trailers(merged, pricing)
    if not acc_trailers:
        click.echo("No LLM usage found; nothing to inject.")
        return

    aic_trailer = core.build_session_usage_aic_trailer(merged)
    trailers: list[str] = []
    if with_session_id:
        trailers.extend(f"Copilot-Session-Usage-Session-ID: {sid}" for sid in session_ids)
    trailers.extend(acc_trailers)
    trailers.append(aic_trailer)

    if dry_run:
        click.echo("Trailers that would be injected:")
        for line in trailers:
            click.echo(line)
        return

    git.amend_commit_with_trailers(trailers, cwd=repo)
    click.echo("Amended HEAD with session cost trailers.")
    for line in trailers:
        click.echo(line)


@cli.command(name="skills")
@core.format_option
@core.output_option
@click.option(
    "--last",
    "last_window",
    metavar="DURATION",
    help="Only sessions started within the last DURATION (e.g. 7d, 24h, 30m).",
)
@click.option(
    "--since", metavar="DATE", help="Only sessions created after DATE (ISO 8601 with timezone)."
)
@click.option(
    "--until", metavar="DATE", help="Only sessions created before DATE (ISO 8601 with timezone)."
)
@click.option(
    "--workspace", metavar="PATH", help="Only consider sessions from this workspace folder."
)
@click.pass_context
def skills_command(
    ctx: click.Context,
    format_: str,
    output_path: str | None,
    last_window: str | None,
    since: str | None,
    until: str | None,
    workspace: str | None,
) -> None:
    """List skills used across sessions with aggregated cost.

    Discovers sessions from workspace storage, analyzes each one, and rolls
    up per-skill token counts and estimated cost.
    """
    since_ms = core.parse_since_to_ms(since) if since else None
    if last_window:
        since_ms = core.parse_last_window_to_ms(last_window)
        if since_ms is None:
            raise click.ClickException(
                f"invalid --last value: {last_window!r}. Use e.g. 7d, 24h, 30m."
            )
    sessions = _discover_sessions(
        ctx, limit=1000, since_ms=since_ms, workspace_filter=workspace, require_logs=True
    )
    if until:
        until_ms = core.parse_since_to_ms(until)
        if until_ms is not None:
            sessions = [s for s in sessions if (s.get("created_ms") or 0) <= until_ms]
    if not sessions:
        raise click.ClickException("no sessions matched the given filters.")

    pricing = _load_pricing_for_agent(ctx.obj.get("agent", "vscode"))
    results: list[dict] = []
    for session in sessions:
        session_dir = Path(session["debug_log_dir"])
        if not session_dir.exists():
            continue
        results.append(_analyze_session_record(session, pricing))

    payload = core.aggregate_skills(results)
    out_path = Path(output_path) if output_path else None
    core.emit(payload, core.normalize_format(format_), out_path)
