"""Click CLI entry point for copilot-session-usage."""

from __future__ import annotations

import sys
from pathlib import Path

import click

from copilot_session_usage._internal import core, vscode

CONTEXT_SETTINGS = {"help_option_names": ["-h", "--help"]}


def _resolve_agent(agent: str) -> str:
    """Validate agent choice and return it."""
    if agent == "cli":
        raise click.ClickException(
            "Copilot-CLI session discovery is not yet implemented. "
            "Use --agent vscode (the default)."
        )
    return agent


@click.group(context_settings=CONTEXT_SETTINGS)
@click.option(
    "--workspace-storage",
    "workspace_storage",
    metavar="PATH",
    help=(
        "Override workspaceStorage directory (auto-detected by default). "
        "Required on WSL2 when VS Code runs on the Windows host."
    ),
)
@click.option(
    "--agent",
    "agent",
    type=click.Choice(("vscode", "cli")),
    default="vscode",
    show_default=True,
    help="Provider to use for session discovery. 'cli' is not yet implemented.",
)
@click.pass_context
def cli(
    ctx: click.Context,
    workspace_storage: str | None,
    agent: str,
) -> None:
    """Extract VS Code Copilot session cost KPIs from local debug logs.

    Reads JSONL debug logs written by the VS Code Copilot Chat extension to
    compute per-session token counts, estimated USD spend, model breakdowns,
    duration, and subagent attribution.

    Sessions are auto-discovered from the VS Code workspaceStorage directory
    (override with --workspace-storage). Use the subcommands below to analyze
    individual sessions, the latest session, or batches.

    Output is controlled by --detail (minimal / compact / full) and
    --format (table / json / detailed). Key capabilities include per-model
    pricing with cache-hit discounts, threshold-aware tier switching for
    long-context models, multi-model session handling, subagent cost
    attribution, and cross-platform support (macOS, Linux, Windows, WSL2).
    """
    ctx.ensure_object(dict)
    ctx.obj["workspace_storage"] = workspace_storage
    ctx.obj["agent"] = _resolve_agent(agent)


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


@cli.command()
@core.analysis_options
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

    if log_dir and name:
        raise click.ClickException("Provide either PATH or --name, not both.")
    if not log_dir and not name:
        raise click.ClickException("Provide a PATH or --name regex.")

    out_path = Path(output_path) if output_path else None
    pricing = core.load_pricing()

    if log_dir:
        session_dir = Path(log_dir)
        if not session_dir.exists():
            msg = f"log directory not found: {session_dir}"
            raise click.ClickException(msg)
        result = core.analyze_session(session_dir, pricing)
        if summary:
            shaped: object = core.compute_efficiency_summary(result)
        else:
            detail = core.resolve_detail(detail, format_)
            shaped = core.shape_session(result, detail)
        output = _apply_query(shaped, query)
        core.emit(output, core.normalize_format(format_), out_path)
        return

    ws_roots = vscode.resolve_ws_roots(ctx.obj.get("workspace_storage"))
    since_ms = core.parse_since_to_ms(since) if since else None
    sessions = vscode.list_recent_sessions(
        ws_roots, limit=1000, since_ms=since_ms, workspace_filter=workspace, require_logs=True
    )
    if until:
        until_ms = core.parse_since_to_ms(until)
        if until_ms is not None:
            sessions = [s for s in sessions if (s.get("created_ms") or 0) <= until_ms]
    if name:
        try:
            sessions = core.filter_sessions_by_name(sessions, name)
        except ValueError as exc:
            raise click.ClickException(str(exc)) from exc
    if not sessions:
        raise click.ClickException("no sessions matched the given filters.")

    results: list[dict] = []
    for session in sessions:
        session_dir = Path(session["debug_log_dir"])
        if not session_dir.exists():
            continue
        result = core.analyze_session(session_dir, pricing)
        result["title"] = session.get("title") or result.get("title")
        results.append(result)

    payload: object
    if aggregate:
        payload = core.aggregate_sessions(results)
    elif summary:
        payload = [core.compute_efficiency_summary(r) for r in results]
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
    ws_roots = vscode.resolve_ws_roots(ctx.obj.get("workspace_storage"))
    session_dir = vscode.find_latest_session_dir(ws_roots, workspace_filter=workspace)
    if not session_dir:
        msg = "no session debug logs found in workspace storage."
        raise click.ClickException(msg)
    pricing = core.load_pricing()
    result = core.analyze_session(session_dir, pricing)
    session_id = session_dir.name
    meta = vscode.find_session_metadata_by_id(session_id, ws_roots)
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
    ws_roots = vscode.resolve_ws_roots(ctx.obj.get("workspace_storage"))
    matches = vscode.find_sessions_by_title(title, ws_roots)
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
        msg = f"debug logs not present at: {session_dir}"
        raise click.ClickException(msg)
    pricing = core.load_pricing()
    result = core.analyze_session(session_dir, pricing)
    result["title"] = match.get("title") or result.get("title")
    detail = core.resolve_detail(detail, format_)
    out_path = Path(output_path) if output_path else None
    core.emit(
        core.shape_session(result, detail),
        core.normalize_format(format_),
        out_path,
    )


@cli.command(name="id")
@core.analysis_options
@click.argument("session_id")
@click.pass_context
def analyze_by_id(
    ctx: click.Context,
    session_id: str,
    detail: str,
    format_: str,
    output_path: str | None,
) -> None:
    """Analyze a session by its exact SESSION_ID (UUID)."""
    ws_roots = vscode.resolve_ws_roots(ctx.obj.get("workspace_storage"))
    session_dir = vscode.find_session_dir_by_id(session_id, ws_roots)
    if not session_dir:
        msg = f"no debug logs found for session ID: {session_id}"
        raise click.ClickException(msg)
    pricing = core.load_pricing()
    result = core.analyze_session(session_dir, pricing)
    meta = vscode.find_session_metadata_by_id(session_id, ws_roots)
    result["title"] = meta.get("title") if meta else result.get("title")
    detail = core.resolve_detail(detail, format_)
    out_path = Path(output_path) if output_path else None
    core.emit(core.shape_session(result, detail), core.normalize_format(format_), out_path)


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
    dir_path: str | None,
    costs: bool,
    format_: str,
    output_path: str | None,
) -> None:
    """List recent sessions with optional cost analysis.

    Without --dir, sessions are discovered from workspace storage metadata.
    With --dir, session directories under PATH are scanned and analyzed.
    """
    out_path = Path(output_path) if output_path else None
    analyze_sessions = costs or bool(dir_path)
    pricing = core.load_pricing()

    if dir_path:
        debug_dir = Path(dir_path)
        if not debug_dir.exists():
            msg = f"directory not found: {debug_dir}"
            raise click.ClickException(msg)
        sessions = core.list_session_dirs(debug_dir)
    else:
        ws_roots = vscode.resolve_ws_roots(ctx.obj.get("workspace_storage"))
        since_ms = core.parse_since_to_ms(since) if since else None
        sessions = vscode.list_recent_sessions(
            ws_roots, limit=limit, since_ms=since_ms, workspace_filter=workspace
        )

    if until:
        until_ms = core.parse_since_to_ms(until)
        if until_ms is not None:
            sessions = [s for s in sessions if (s.get("created_ms") or 0) <= until_ms]
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
            result = core.analyze_session(session_dir, pricing)
            result["title"] = session.get("title") or result.get("title")
            analyzed.append(result)
        sessions = analyzed

    core.emit(sessions, core.normalize_format(format_), out_path, costed_list=analyze_sessions)


@cli.command()
@core.analysis_options
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
    detail: str,
    format_: str,
    output_path: str | None,
) -> None:
    """Analyze the N most recent sessions in one invocation.

    Always returns {"summary": {...}, "sessions": [...]}: a pre-computed
    aggregate across all N sessions plus a per-session array shaped by
    --detail. Much faster than N separate `id` invocations.
    """
    ws_roots = vscode.resolve_ws_roots(ctx.obj.get("workspace_storage"))
    since_ms = core.parse_since_to_ms(since) if since else None
    sessions = vscode.list_recent_sessions(
        ws_roots,
        limit=count,
        since_ms=since_ms,
        workspace_filter=workspace,
        require_logs=True,
    )
    if until:
        until_ms = core.parse_since_to_ms(until)
        if until_ms is not None:
            sessions = [s for s in sessions if (s.get("created_ms") or 0) <= until_ms]
    if name:
        try:
            sessions = core.filter_sessions_by_name(sessions, name)
        except ValueError as exc:
            raise click.ClickException(str(exc)) from exc
    pricing = core.load_pricing()
    results: list[dict] = []
    for session in sessions:
        session_dir = Path(session["debug_log_dir"])
        if not session_dir.exists():
            continue
        result = core.analyze_session(session_dir, pricing)
        result["title"] = session.get("title") or result.get("title")
        results.append(result)
    detail = core.resolve_detail(detail, format_)
    out_path = Path(output_path) if output_path else None
    core.emit(core.shape_batch(results, detail), core.normalize_format(format_), out_path)
