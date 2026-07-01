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
def cli(ctx: click.Context, workspace_storage: str | None, agent: str) -> None:
    r"""Extract VS Code Copilot session cost KPIs from local debug logs.

    \b
      analyze PATH   Analyze one session by its debug-log directory.
      latest         Analyze the most recently modified session.
      find TITLE     Find and analyze a session by title (fuzzy match).
      id SESSION_ID  Analyze a session by exact UUID.
      list           List recent sessions (metadata only, no cost).
      batch N        Analyze the N most recent sessions in one pass.
    """
    ctx.ensure_object(dict)
    ctx.obj["workspace_storage"] = workspace_storage
    ctx.obj["agent"] = _resolve_agent(agent)


@cli.command()
@core.analysis_options
@click.argument("log_dir", metavar="PATH")
def analyze(log_dir: str, detail: str, format_: str, output_path: str | None) -> None:
    """Analyze a single session by its debug-log directory PATH.

    PATH is typically the VS Code Copilot session debug log directory —
    this is the fastest path, no discovery needed.
    """
    session_dir = Path(log_dir)
    if not session_dir.exists():
        msg = f"log directory not found: {session_dir}"
        raise click.ClickException(msg)
    pricing = core.load_pricing()
    result = core.analyze_session(session_dir, pricing)
    detail = core.resolve_detail(detail, format_)
    out_path = Path(output_path) if output_path else None
    core.emit(core.shape_session(result, detail), core.normalize_format(format_), out_path)


@cli.command()
@core.analysis_options
@click.option(
    "--workspace", metavar="PATH", help="Only consider sessions from this workspace folder."
)
@click.pass_context
def latest(
    ctx: click.Context, workspace: str | None, detail: str, format_: str, output_path: str | None
) -> None:
    """Analyze the most recently modified session across all workspaces."""
    ws_roots = vscode.resolve_ws_roots(ctx.obj.get("workspace_storage"))
    session_dir = vscode.find_latest_session_dir(ws_roots, workspace_filter=workspace)
    if not session_dir:
        msg = "no session debug logs found in workspace storage."
        raise click.ClickException(msg)
    pricing = core.load_pricing()
    result = core.analyze_session(session_dir, pricing)
    detail = core.resolve_detail(detail, format_)
    out_path = Path(output_path) if output_path else None
    core.emit(core.shape_session(result, detail), core.normalize_format(format_), out_path)


@cli.command(name="find")
@core.analysis_options
@click.option(
    "--workspace", metavar="PATH", help="Only consider sessions from this workspace folder."
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
        click.echo("Re-run with: id <SESSION_ID>", err=True)
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
    core.emit(core.shape_session(result, detail), core.normalize_format(format_), out_path)


@cli.command(name="id")
@core.analysis_options
@click.argument("session_id")
@click.pass_context
def analyze_by_id(
    ctx: click.Context, session_id: str, detail: str, format_: str, output_path: str | None
) -> None:
    """Analyze a session by its exact SESSION_ID (UUID)."""
    ws_roots = vscode.resolve_ws_roots(ctx.obj.get("workspace_storage"))
    session_dir = vscode.find_session_dir_by_id(session_id, ws_roots)
    if not session_dir:
        msg = f"no debug logs found for session ID: {session_id}"
        raise click.ClickException(msg)
    pricing = core.load_pricing()
    result = core.analyze_session(session_dir, pricing)
    detail = core.resolve_detail(detail, format_)
    out_path = Path(output_path) if output_path else None
    core.emit(core.shape_session(result, detail), core.normalize_format(format_), out_path)


@cli.command(name="list")
@core.format_option
@core.output_option
@click.option("--limit", type=int, default=20, show_default=True, help="Max sessions to return.")
@click.option(
    "--since", metavar="DATE", help="Only sessions created after DATE (YYYY-MM-DD or ISO 8601)."
)
@click.option(
    "--workspace", metavar="PATH", help="Only consider sessions from this workspace folder."
)
@click.pass_context
def list_sessions(
    ctx: click.Context,
    limit: int,
    since: str | None,
    workspace: str | None,
    format_: str,
    output_path: str | None,
) -> None:
    """List recent sessions (metadata only — no cost analysis)."""
    ws_roots = vscode.resolve_ws_roots(ctx.obj.get("workspace_storage"))
    since_ms = core.parse_since_to_ms(since) if since else None
    sessions = vscode.list_recent_sessions(
        ws_roots, limit=limit, since_ms=since_ms, workspace_filter=workspace
    )
    out_path = Path(output_path) if output_path else None
    core.emit(sessions, core.normalize_format(format_), out_path)


@cli.command()
@core.analysis_options
@click.option(
    "--since", metavar="DATE", help="Only sessions created after DATE (YYYY-MM-DD or ISO 8601)."
)
@click.option(
    "--workspace", metavar="PATH", help="Only consider sessions from this workspace folder."
)
@click.argument("count", type=int, metavar="N")
@click.pass_context
def batch(
    ctx: click.Context,
    count: int,
    since: str | None,
    workspace: str | None,
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
        ws_roots, limit=count, since_ms=since_ms, workspace_filter=workspace, require_logs=True
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
    detail = core.resolve_detail(detail, format_)
    out_path = Path(output_path) if output_path else None
    core.emit(core.shape_batch(results, detail), core.normalize_format(format_), out_path)
