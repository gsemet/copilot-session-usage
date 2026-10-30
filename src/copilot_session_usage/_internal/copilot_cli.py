"""Copilot CLI / Copilot App session discovery, parsing, and analysis.

The macOS Copilot App and the standalone Copilot CLI share the same local
session-state layout::

    ~/.copilot/session-state/<session-id>/events.jsonl
    ~/.copilot/session-state/<session-id>/workspace.yaml

``events.jsonl`` is the primary evidence source: a structured event log with
one JSON object per line. ``workspace.yaml`` is an optional sidecar with
metadata (title, working directory, git branch, timestamps) that is not
duplicated inside the event log.

This module only discovers paths and extracts evidence from these local
files. It never calls a network API and never requires credentials. Shared
model/pricing calculations, output shaping, and rendering stay in
:mod:`copilot_session_usage._internal.core`.

The event schema observed on the active installation is ``version: 1``,
produced by ``copilot-agent``. Parsing tolerates unknown/newer schema
versions and unrecognized event types by skipping what it cannot interpret
and recording an explicit diagnostic, rather than failing outright.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from copilot_session_usage._internal import core

EVENTS_FILENAME = "events.jsonl"
WORKSPACE_METADATA_FILENAME = "workspace.yaml"

#: Event schema versions this parser has been validated against. Other
#: versions are still parsed best-effort (forward compatibility) but produce
#: a diagnostic note.
SUPPORTED_SCHEMA_VERSIONS: tuple[int, ...] = (1,)

SESSION_ID_RE = re.compile(
    r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
)


# ─── Defensive evidence extraction helpers ──────────────────────────────────
#
# The Copilot CLI event schema is versioned but not contractually validated
# here (see module docstring): a line can be well-formed JSON yet carry a
# value of the wrong shape for a given field (e.g. ``data`` as a list,
# ``modelMetrics`` as a string, a per-model entry as ``null``). These helpers
# coerce such evidence to a safe, inspectable shape instead of raising, so a
# single malformed field degrades to "missing" rather than crashing the
# entire parse. They never fabricate a non-zero/non-empty value.


def _clean_str(value: Any) -> str | None:
    """Return ``value`` when it is a non-empty string, else ``None``.

    Guards every place a field is expected to be a string label (model name,
    tool name, skill name, ...): a wrong-shaped value (e.g. a number, list,
    or dict) is treated as absent evidence rather than coerced or fabricated.
    """
    return value if isinstance(value, str) and value else None


def _as_mapping(value: Any) -> dict[str, Any]:
    """Return ``value`` when it is a dict, else an empty dict."""
    return value if isinstance(value, dict) else {}


def _as_list(value: Any) -> list[Any]:
    """Return ``value`` when it is a list, else an empty list."""
    return value if isinstance(value, list) else []


def _as_int(value: Any) -> int | None:
    """Coerce a numeric evidence field to ``int``, preserving absence as ``None``.

    A missing/``null`` field, or one of the wrong type (string, list, dict,
    bool), returns ``None`` — never a fabricated ``0``. A genuinely reported
    ``0`` (``isinstance(value, (int, float))``) is preserved as ``0``.
    """
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return int(value)
    return None


def _as_number(value: Any) -> int | float | None:
    """Coerce a numeric evidence field to ``int``/``float``, preserving absence as ``None``."""
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return value
    return None


def _compaction_model(data: dict[str, Any]) -> str:
    """Resolve the model a compaction call ran on (behavior model, then fallbacks)."""
    tokens = _as_mapping(data.get("compactionTokensUsed"))
    return (
        _clean_str(data.get("behaviorModelId"))
        or _clean_str(_as_mapping(data.get("responsesReasoning")).get("model"))
        or _clean_str(tokens.get("model"))
        or _clean_str(_as_mapping(tokens.get("copilotUsage")).get("model"))
        or "unknown"
    )


# ─── Session-state root discovery ───────────────────────────────────────────


def default_session_state_roots() -> list[Path]:
    """Return the standard Copilot CLI/App session-state root, if present.

    The layout is ``~/.copilot/session-state/`` on every supported platform
    (it is a dotfile-style directory, not an OS-specific application-data
    path). Only returns the directory when it actually exists.
    """
    root = Path.home() / ".copilot" / "session-state"
    return [root] if root.is_dir() else []


def resolve_session_state_roots(session_root: str | None) -> list[Path]:
    """Resolve session-state roots from an explicit override or auto-detection."""
    import click

    if session_root:
        root = Path(session_root)
        if not root.is_dir():
            msg = f"--session-root path not found: {root}"
            raise click.ClickException(msg)
        return [root]
    roots = default_session_state_roots()
    if not roots:
        msg = (
            "No Copilot CLI session-state directory found.\n"
            "Pass --session-root PATH to specify the location manually.\n"
            "Default location: ~/.copilot/session-state"
        )
        raise click.ClickException(msg)
    return roots


def is_valid_session_dir(path: Path) -> bool:
    """Return whether ``path`` is a discoverable Copilot CLI session directory.

    A valid session directory is named with the session UUID and contains
    ``events.jsonl``. Directories missing either condition are not
    auto-discovered, but can still be analyzed via an explicit path (see
    :func:`resolve_events_source`), where the diagnostic is reported instead
    of silently fabricating a session.
    """
    return (
        path.is_dir()
        and bool(SESSION_ID_RE.fullmatch(path.name))
        and (path / EVENTS_FILENAME).is_file()
    )


def list_session_dirs(root: Path) -> list[Path]:
    """Return valid session directories directly under ``root``, unsorted order aside."""
    if not root.is_dir():
        return []
    return sorted(p for p in root.iterdir() if is_valid_session_dir(p))


# ─── workspace.yaml sidecar metadata ─────────────────────────────────────────


def _yaml_to_iso(value: Any) -> str | None:
    """Normalize a ruamel.yaml-parsed timestamp (datetime or string) to ISO 8601 UTC."""
    if value is None:
        return None
    if isinstance(value, str):
        return value
    # ruamel.yaml's safe loader parses YAML timestamps into datetime objects.
    if isinstance(value, datetime):
        dt = value if value.tzinfo else value.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    return str(value)


def _yaml_to_ms(value: Any) -> int | None:
    """Convert a ruamel.yaml-parsed timestamp (datetime or string) to epoch milliseconds."""
    if value is None:
        return None
    if isinstance(value, str):
        return core.parse_since_to_ms(value)
    if isinstance(value, datetime):
        return int(value.timestamp() * 1000)
    return None


def read_workspace_metadata(session_dir: Path) -> dict[str, Any]:
    """Read the optional ``workspace.yaml`` sidecar for a session directory.

    Returns an empty dict when the file is absent, unreadable, or does not
    parse as a mapping — metadata from this file is always optional evidence,
    never required for discovery or analysis.
    """
    path = session_dir / WORKSPACE_METADATA_FILENAME
    if not path.is_file():
        return {}
    try:
        from ruamel.yaml import YAML

        yaml = YAML(typ="safe")
        with path.open(encoding="utf-8") as f:
            data = yaml.load(f)
    except Exception:  # noqa: BLE001 - any parse/read failure means "no metadata"
        return {}
    if not isinstance(data, dict):
        return {}
    return data


def _resolve_title(workspace_meta: dict[str, Any], renamed_title: str | None) -> str | None:
    """Resolve the best available session title from available evidence.

    Preference order: an explicit rename recorded in ``workspace.yaml``, a
    session rename observed live in the event log, then the session summary.
    None of these are required — discovery and analysis work without a title.
    """
    name = workspace_meta.get("name")
    if isinstance(name, str) and name.strip():
        return name
    if renamed_title:
        return renamed_title
    summary = workspace_meta.get("summary")
    if isinstance(summary, str) and summary.strip():
        return summary
    return None


# ─── events.jsonl parsing ─────────────────────────────────────────────────────


def resolve_events_source(source: Path) -> tuple[Path, Path | None]:
    """Resolve an explicit CLI source path to ``(events_path, session_dir)``.

    Accepts a session directory (containing ``events.jsonl``) or a direct
    path to an exported/relocated events file. ``session_dir`` is ``None``
    when the source is a bare file outside of a recognizable session
    directory (its ``workspace.yaml`` sidecar, if any, is then unavailable).

    Raises:
        ValueError: If ``source`` does not exist or is a directory without
            ``events.jsonl``.
    """
    source = Path(source)
    if source.is_dir():
        events_path = source / EVENTS_FILENAME
        if not events_path.is_file():
            msg = f"not a valid Copilot CLI session directory (missing {EVENTS_FILENAME}): {source}"
            raise ValueError(msg)
        return events_path, source
    if source.is_file():
        session_dir = source.parent if source.name == EVENTS_FILENAME else None
        return source, session_dir
    msg = f"Copilot CLI session source not found: {source}"
    raise ValueError(msg)


def _subagent_label(agent_id: str | None, subagent_started: dict[str, dict[str, Any]]) -> str:
    """Resolve a tool call's attribution label from its event ``agentId``.

    Returns ``"main"`` for the top-level session (no ``agentId`` on the
    event), the subagent's recorded display name when a matching
    ``subagent.started`` event was seen earlier in the log, or the raw
    ``agentId`` itself as a last-resort, still evidence-backed label when a
    subagent's start event was not captured (e.g. a truncated log or schema
    variation). Never fabricates a name.
    """
    if not agent_id:
        return "main"
    meta = subagent_started.get(agent_id)
    if meta and meta.get("name"):
        return str(meta["name"])
    return agent_id


def parse_events_file(events_path: Path) -> dict[str, Any]:
    """Parse a Copilot CLI ``events.jsonl`` file into aggregated evidence.

    Tolerates malformed lines and unrecognized event types (schema
    evolution): both are counted but do not abort parsing. Only the last
    ``session.shutdown`` event is used for the final per-model token
    breakdown, since Copilot CLI reports it as a cumulative session total.
    When no ``session.shutdown`` is present (an active or interrupted
    session), the last ``session.usage_checkpoint`` provides a best-effort
    fallback of provider-native counters only — token/model breakdown is
    not available at checkpoint granularity.
    """
    stats: dict[str, Any] = {
        "session_id": None,
        "schema_version": None,
        "producer": None,
        "copilot_version": None,
        "selected_model": None,
        "reasoning_effort": None,
        "cwd": None,
        "renamed_title": None,
        "start_time_ms": None,
        "last_event_ms": None,
        "resume_count": 0,
        "skill_events": [],
        "tool_rows": {},
        "shutdown_events": [],
        "checkpoint_events": [],
        "malformed_lines": 0,
        "invalid_timestamp_lines": 0,
        "line_count": 0,
        "structured_event_lines": 0,
        "unsupported_versions": set(),
        "unknown_event_types": {},
        "subagent_started": {},
        "subagent_completed": {},
        "usage_calls": [],
        "compaction_calls": [],
        "skill_timelines": {},
    }

    seen_usage_ids: set[str] = set()
    tool_start_names: dict[str, tuple[str, str | None]] = {}
    current_skill_by_agent: dict[str | None, str] = {}

    def _parse_ts(value: Any) -> int | None:
        """Parse a timestamp-shaped evidence field, counting invalid values.

        A missing/empty value is simply absent (not counted). A present but
        unparseable value (wrong type, or a string that doesn't parse) is
        counted under ``invalid_timestamp_lines`` so it can be surfaced as a
        diagnostic, and evaluates to ``None`` rather than raising.
        """
        if not value:
            return None
        ts = core.parse_since_to_ms(value)
        if ts is None:
            stats["invalid_timestamp_lines"] += 1
        return ts

    try:
        with events_path.open(encoding="utf-8") as f:
            for raw in f:
                line = raw.strip()
                if not line:
                    continue
                stats["line_count"] += 1
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    stats["malformed_lines"] += 1
                    continue
                if not isinstance(obj, dict):
                    # Valid JSON but not an event record (e.g. a bare list or
                    # scalar) — not interpretable, but not fatal either.
                    stats["malformed_lines"] += 1
                    continue

                etype = obj.get("type")
                if isinstance(etype, str) and etype:
                    stats["structured_event_lines"] += 1
                data = _as_mapping(obj.get("data"))
                agent_id = _clean_str(obj.get("agentId"))
                ts_ms = _parse_ts(obj.get("timestamp"))
                if ts_ms is not None and (
                    stats["last_event_ms"] is None or ts_ms > stats["last_event_ms"]
                ):
                    stats["last_event_ms"] = ts_ms

                if etype == "session.start":
                    stats["session_id"] = data.get("sessionId") or stats["session_id"]
                    version = data.get("version")
                    stats["schema_version"] = version
                    if version is not None and version not in SUPPORTED_SCHEMA_VERSIONS:
                        # Always normalize to str: mixing e.g. an int and a
                        # str version across session.start lines would
                        # otherwise make the sorted() diagnostic below raise
                        # TypeError (int/str are not orderable in Python 3),
                        # and an unhashable value (list/dict) can't be added
                        # to a set at all. str() is always hashable and
                        # always orderable against other strings.
                        stats["unsupported_versions"].add(str(version))
                    stats["producer"] = _clean_str(data.get("producer")) or stats["producer"]
                    stats["copilot_version"] = (
                        _clean_str(data.get("copilotVersion")) or stats["copilot_version"]
                    )
                    stats["selected_model"] = (
                        _clean_str(data.get("selectedModel")) or stats["selected_model"]
                    )
                    stats["reasoning_effort"] = (
                        _clean_str(data.get("reasoningEffort")) or stats["reasoning_effort"]
                    )
                    stats["cwd"] = (
                        _clean_str(_as_mapping(data.get("context")).get("cwd")) or stats["cwd"]
                    )
                    start_ms = _parse_ts(data.get("startTime"))
                    if start_ms is not None and (
                        stats["start_time_ms"] is None or start_ms < stats["start_time_ms"]
                    ):
                        stats["start_time_ms"] = start_ms
                elif etype == "session.resume":
                    stats["resume_count"] += 1
                    stats["selected_model"] = (
                        _clean_str(data.get("selectedModel")) or stats["selected_model"]
                    )
                    stats["cwd"] = (
                        _clean_str(_as_mapping(data.get("context")).get("cwd")) or stats["cwd"]
                    )
                elif etype == "skill.invoked":
                    name = _clean_str(data.get("name"))
                    if name:
                        # Skill scope is tracked per agentId (None = main
                        # session) so a subagent's skill invocations never
                        # bleed into the main session's tool attribution, and
                        # vice versa, when their events interleave.
                        current_skill_by_agent[agent_id] = name
                        stats["skill_events"].append((ts_ms, name))
                        if ts_ms is not None:
                            stats["skill_timelines"].setdefault(agent_id, []).append((ts_ms, name))
                elif etype == "session.usage_record":
                    usage = _as_mapping(data.get("usage"))
                    accounting = _as_mapping(usage.get("accounting"))
                    usage_id = _clean_str(accounting.get("usageId"))
                    if usage_id is not None:
                        if usage_id in seen_usage_ids:
                            continue
                        seen_usage_ids.add(usage_id)
                    model = _clean_str(usage.get("model"))
                    inp = _as_int(usage.get("inputTokens"))
                    out = _as_int(usage.get("outputTokens"))
                    if model is None or (inp is None and out is None):
                        continue
                    if core.is_utility_model(model):
                        # Utility models (gpt-4o*, gpt-4.1*, gpt-5.4-nano*) are free.
                        continue
                    stats["usage_calls"].append(
                        {
                            "ts_ms": ts_ms,
                            "agent_id": agent_id,
                            "model": model,
                            "input": inp or 0,
                            "cached": _as_int(usage.get("cacheReadTokens")) or 0,
                            "cache_write": _as_int(usage.get("cacheWriteTokens")),
                            "output": out or 0,
                            "nano_aiu": _as_number(
                                _as_mapping(usage.get("copilotUsage")).get("totalNanoAiu")
                            ),
                            "initiator": _clean_str(usage.get("initiator")),
                            "premium_requests": _as_number(usage.get("cost")),
                        }
                    )
                elif etype == "session.compaction_complete":
                    tokens = _as_mapping(data.get("compactionTokensUsed"))
                    if not tokens:
                        continue
                    inp = _as_int(tokens.get("inputTokens"))
                    out = _as_int(tokens.get("outputTokens"))
                    if inp is None and out is None:
                        continue
                    compaction_model = _compaction_model(data)
                    if core.is_utility_model(compaction_model):
                        continue
                    stats["compaction_calls"].append(
                        {
                            "ts_ms": ts_ms,
                            "agent_id": agent_id,
                            "model": compaction_model,
                            "input": inp or 0,
                            "cached": _as_int(tokens.get("cacheReadTokens")) or 0,
                            "cache_write": _as_int(tokens.get("cacheWriteTokens")),
                            "output": out or 0,
                            "nano_aiu": _as_number(
                                _as_mapping(tokens.get("copilotUsage")).get("totalNanoAiu")
                            ),
                            "llm_calls": _as_int(tokens.get("requestCount"))
                            or _as_int(data.get("requestCount"))
                            or 1,
                        }
                    )
                elif etype == "tool.execution_start":
                    call_id = _clean_str(data.get("toolCallId"))
                    if call_id:
                        tool_start_names[call_id] = (
                            _clean_str(data.get("toolName")) or "unknown",
                            agent_id,
                        )
                elif etype == "tool.execution_complete":
                    call_id = _clean_str(data.get("toolCallId"))
                    tool_name, start_agent_id = (
                        tool_start_names.get(call_id, ("unknown", None))
                        if call_id
                        else ("unknown", None)
                    )
                    effective_agent_id = agent_id or start_agent_id
                    skill = current_skill_by_agent.get(effective_agent_id, "unknown")
                    subagent_label = _subagent_label(effective_agent_id, stats["subagent_started"])
                    key = (tool_name, skill, subagent_label)
                    bucket = stats["tool_rows"].setdefault(
                        key, {"calls": 0, "success": 0, "failure": 0}
                    )
                    bucket["calls"] += 1
                    success = data.get("success")
                    if success is True:
                        bucket["success"] += 1
                    elif success is False:
                        bucket["failure"] += 1
                elif etype == "external_tool.requested":
                    tool_name = _clean_str(data.get("toolName")) or "unknown"
                    if tool_name == "rename_session":
                        title = _clean_str(_as_mapping(data.get("arguments")).get("title"))
                        if title:
                            stats["renamed_title"] = title
                    skill = current_skill_by_agent.get(agent_id, "unknown")
                    subagent_label = _subagent_label(agent_id, stats["subagent_started"])
                    key = (tool_name, skill, subagent_label)
                    bucket = stats["tool_rows"].setdefault(
                        key, {"calls": 0, "success": 0, "failure": 0}
                    )
                    bucket["calls"] += 1
                elif etype == "session.shutdown":
                    stats["shutdown_events"].append(data)
                elif etype == "session.usage_checkpoint":
                    stats["checkpoint_events"].append(data)
                elif etype == "subagent.started":
                    # A known type without an agentId has nothing to key the
                    # record by; it is intentionally dropped here rather than
                    # falling through to the unknown-type bucket below, since
                    # the type itself was recognized.
                    if agent_id:
                        stats["subagent_started"][agent_id] = {
                            "name": (
                                _clean_str(data.get("agentDisplayName"))
                                or _clean_str(data.get("agentName"))
                                or agent_id
                            ),
                            "model": _clean_str(data.get("model")),
                            "agent_type": _clean_str(data.get("agentType")),
                        }
                elif etype == "subagent.completed":
                    if agent_id:
                        stats["subagent_completed"][agent_id] = {
                            "total_tool_calls": _as_int(data.get("totalToolCalls")),
                            "total_tokens": _as_int(data.get("totalTokens")),
                            "duration_ms": _as_number(data.get("durationMs")),
                            "model": _clean_str(data.get("model")),
                        }
                elif isinstance(etype, str) and etype:
                    # A structured, non-empty event type this parser does not
                    # recognize (schema evolution, a newer producer, etc.).
                    # Count it explicitly so it can be surfaced as a
                    # diagnostic rather than silently dropped: an unknown
                    # event is never usage, but it is also never nothing.
                    stats["unknown_event_types"][etype] = (
                        stats["unknown_event_types"].get(etype, 0) + 1
                    )
    except OSError as exc:
        msg = f"could not read Copilot CLI events file: {events_path} ({exc})"
        raise ValueError(msg) from exc

    return stats


def canonical_session_id(events_path: Path, session_dir: Path | None, stats: dict[str, Any]) -> str:
    """Return the canonical session UUID for a CLI source, or raise ``ValueError``.

    Prefers the session directory name (the on-disk convention), falling back
    to the ``session.start`` event's own ``sessionId``. A file name such as
    ``events.jsonl`` is never used as an identity.
    """
    if session_dir is not None and SESSION_ID_RE.fullmatch(session_dir.name):
        return session_dir.name
    candidate = stats.get("session_id")
    if candidate and SESSION_ID_RE.fullmatch(str(candidate)):
        return str(candidate)
    msg = (
        f"could not determine a canonical session UUID for {events_path}: neither the "
        "session directory name nor a session.start event's sessionId is a valid UUID. "
        "Refusing to fabricate a session identity from the file name."
    )
    raise ValueError(msg)


def collect_cli_calls_with_id(source: Path) -> tuple[str, list[dict[str, Any]]]:
    """Return ``(canonical_session_id, calls)`` for a CLI session directory or events file."""
    events_path, session_dir = resolve_events_source(Path(source))
    stats = parse_events_file(events_path)
    return canonical_session_id(events_path, session_dir, stats), build_cli_calls(stats)


def collect_cli_calls(source: Path) -> list[dict[str, Any]]:
    """Return every normalized call record of a CLI session (no window applied)."""
    events_path, _ = resolve_events_source(Path(source))
    return build_cli_calls(parse_events_file(events_path))


def analyze_cli_session(
    source: Path,
    pricing: dict[str, Any],
    since_ms: int | None = None,
    until_ms: int | None = None,
) -> dict[str, Any]:
    """Analyze a Copilot CLI/Copilot App session and return a shared-shape result.

    ``source`` may be a session directory (the common case, discovered
    below a session-state root) or a direct path to an exported/relocated
    ``events.jsonl`` file. The returned dict follows the same contract as
    :func:`copilot_session_usage._internal.core.analyze_session` — including
    ``total``, ``model_breakdown``, ``skills``, and detail shaping — plus
    ``provider``, ``source``, ``provider_usage`` (CLI-native counters kept
    separate from the shared pricing calculation), and ``diagnostics`` for
    missing/malformed/unsupported evidence.

    Raises:
        ValueError: If ``source`` is not a readable Copilot CLI session
            source (see :func:`resolve_events_source`).
    """
    events_path, session_dir = resolve_events_source(Path(source))
    stats = parse_events_file(events_path)

    if stats["line_count"] == 0:
        msg = f"no events found in {events_path}: the file is empty."
        raise ValueError(msg)
    if stats["structured_event_lines"] == 0:
        msg = (
            f"{events_path} does not look like a Copilot CLI events.jsonl file: no recognized "
            "event records (JSON objects with a 'type' field) were found."
        )
        raise ValueError(msg)

    workspace_meta = read_workspace_metadata(session_dir) if session_dir else {}

    session_id = canonical_session_id(events_path, session_dir, stats)

    diagnostics: list[str] = []
    if stats["malformed_lines"]:
        diagnostics.append(
            f"{stats['malformed_lines']} malformed JSON line(s) were skipped in {events_path.name}."
        )
    if stats["invalid_timestamp_lines"]:
        diagnostics.append(
            f"{stats['invalid_timestamp_lines']} event(s) had a missing, non-string, or "
            "unparseable timestamp; those events were excluded from timing calculations "
            "rather than assumed to be at a fabricated instant."
        )
    if stats["unsupported_versions"]:
        diagnostics.append(
            "event schema version(s) "
            f"{sorted(stats['unsupported_versions'])} were not explicitly validated against "
            "this parser; fields were extracted best-effort using the known event shapes."
        )
    if stats["unknown_event_types"]:
        unknown_total = sum(stats["unknown_event_types"].values())
        unknown_kinds = ", ".join(sorted(stats["unknown_event_types"]))
        diagnostics.append(
            f"{unknown_total} event(s) had an unrecognized type ({unknown_kinds}); this parser "
            "does not know how to interpret them, so they were skipped and excluded from usage, "
            "tool, and skill attribution rather than guessed."
        )

    shutdown = stats["shutdown_events"][-1] if stats["shutdown_events"] else None
    checkpoint = stats["checkpoint_events"][-1] if stats["checkpoint_events"] else None

    total_premium_requests: int | float | None = None
    shutdown_type: str | None = None
    code_changes: dict[str, Any] | None = None
    active_duration_s: int | None = None
    models_from_evidence: set[str] = set()
    snapshot_nano: int | float | None = None

    if shutdown is not None:
        for model, metrics in _as_mapping(shutdown.get("modelMetrics")).items():
            if isinstance(model, str) and model and isinstance(metrics, dict):
                models_from_evidence.add(model)
        shutdown_type = _clean_str(shutdown.get("shutdownType"))
        raw_code_changes = shutdown.get("codeChanges")
        if raw_code_changes is not None and not isinstance(raw_code_changes, dict):
            diagnostics.append("session.shutdown.codeChanges was not a mapping; ignored.")
        else:
            code_changes = raw_code_changes
        api_duration_ms = _as_number(shutdown.get("totalApiDurationMs"))
        if api_duration_ms is not None:
            active_duration_s = round(api_duration_ms / 1000.0)
    for entry in _as_list(checkpoint.get("modelCacheState") if checkpoint else None):
        model_id = _clean_str(_as_mapping(entry).get("modelId"))
        if model_id:
            models_from_evidence.add(model_id)
    # The shutdown/checkpoint totalNanoAiu snapshots are cumulative, but they
    # miss usage from segments that ended without a shutdown. They are kept
    # only as a diagnostic cross-check, never as the cost source.
    snapshot_nano = max(
        (
            n
            for n in (
                _as_number(shutdown.get("totalNanoAiu")) if shutdown else None,
                _as_number(checkpoint.get("totalNanoAiu")) if checkpoint else None,
            )
            if n is not None
        ),
        default=None,
    )
    for source_event in (checkpoint, shutdown):
        if source_event is not None:
            premium = _as_number(source_event.get("totalPremiumRequests"))
            if premium is not None:
                total_premium_requests = premium

    if stats.get("selected_model"):
        models_from_evidence.add(stats["selected_model"])

    all_calls = build_cli_calls(stats)
    calls = core.filter_calls_by_window(all_calls, since_ms, until_ms)
    windowed = since_ms is not None or until_ms is not None

    if calls:
        summary = core.summarize_calls(calls, pricing)
        total = summary["total"]
        reconciliation = summary["reconciliation"]
        reconciliation["snapshot_usd"] = None
        reconciliation["snapshot_delta_usd"] = None
        if snapshot_nano is not None and not windowed:
            snapshot_usd = round(float(snapshot_nano) / core.NANO_AIU_PER_USD, core.USD_DECIMALS)
            delta = round(snapshot_usd - total["estimated_usd"], core.USD_DECIMALS)
            reconciliation["snapshot_usd"] = snapshot_usd
            reconciliation["snapshot_delta_usd"] = delta
            if delta > 0.005:
                diagnostics.append(
                    f"the last shutdown/checkpoint snapshot (${snapshot_usd:.4f}) is "
                    f"${delta:.4f} higher than the sum of per-call usage records "
                    f"(${total['estimated_usd']:.4f}). Snapshots only count usage up to the "
                    "last shutdown, so per-call records are the reported cost."
                )
    else:
        summary = {
            "total": core.empty_total(),
            "models": [],
            "model_breakdown": [],
            "subagents": [],
            "skill_breakdown": [],
            "initiator_breakdown": [],
            "reconciliation": None,
            "fallback_pricing_models": [],
        }
        total = summary["total"]
        reconciliation = None
        if not windowed:
            diagnostics.append(
                "no session.usage_record or session.compaction_complete events found in this "
                "session; usage totals and cost are unavailable."
            )

    model_breakdown = summary["model_breakdown"]
    total_nano_aiu = (
        sum(c["nano_aiu"] for c in calls if c["nano_aiu"] is not None) if calls else None
    )
    window_premium = (
        sum(c["premium_requests"] for c in calls if c["premium_requests"] is not None)
        if calls
        else None
    )
    if calls:
        total_premium_requests = window_premium
    elif windowed:
        total_premium_requests = None
    fallback_pricing_models = summary["fallback_pricing_models"]

    skill_names = sorted({name for _, name in stats["skill_events"]})
    active_skill = stats["skill_events"][-1][1] if stats["skill_events"] else None

    tool_breakdown = sorted(
        (
            {"tool": tool, "calls": row["calls"], "skill": skill, "subagent": subagent}
            for (tool, skill, subagent), row in stats["tool_rows"].items()
        ),
        key=lambda x: (-x["calls"], x["tool"], x["skill"]),
    )

    first_ts = stats.get("start_time_ms")
    last_ts = stats.get("last_event_ms")
    duration_s = (
        round((last_ts - first_ts) / 1000.0)
        if first_ts is not None and last_ts is not None
        else None
    )

    title = _resolve_title(workspace_meta, stats.get("renamed_title"))
    started_at = _yaml_to_iso(workspace_meta.get("created_at")) or core.ts_to_iso(first_ts)
    ended_at = _yaml_to_iso(workspace_meta.get("updated_at")) or core.ts_to_iso(last_ts)

    provider_usage = {
        "total_nano_aiu": total_nano_aiu,
        "total_premium_requests": total_premium_requests,
        "shutdown_type": shutdown_type,
        "resume_count": stats.get("resume_count", 0),
        "code_changes": code_changes,
    }

    return {
        "schema_version": core.SCHEMA_VERSION,
        "session_id": session_id,
        "session_dir": str(session_dir) if session_dir else str(events_path.parent),
        "provider": "cli",
        "source": str(events_path),
        "title": title,
        "cwd": workspace_meta.get("cwd") or stats.get("cwd"),
        "git_root": workspace_meta.get("git_root"),
        "branch": workspace_meta.get("branch"),
        "started_at": started_at,
        "ended_at": ended_at,
        "duration_seconds": duration_s,
        "active_duration_seconds": active_duration_s,
        "total": total,
        "models": summary["models"]
        or (sorted(models_from_evidence) if models_from_evidence else []),
        "fallback_pricing_models": fallback_pricing_models,
        "model_breakdown": model_breakdown,
        "subagents": summary["subagents"],
        "initiator_breakdown": summary["initiator_breakdown"],
        "reconciliation": reconciliation,
        "skills": {
            "detected": skill_names,
            "active": active_skill,
            "breakdown": summary["skill_breakdown"],
            "tool_breakdown": tool_breakdown,
        },
        "provider_usage": provider_usage,
        "diagnostics": diagnostics,
        "pricing_note": (
            "Every figure is aggregated from per-call records: each session.usage_record "
            "(deduplicated by usageId) and each session.compaction_complete event. Cost is "
            "the provider-billed copilotUsage.totalNanoAiu of each call (1 nanoAiu = 1e-11 "
            "USD, cost_source 'billed'); calls without it are priced from "
            "data/models-and-pricing.yml with exact cache-write counts (cost_source "
            "'estimated'). Shutdown/checkpoint snapshots are incomplete and only used for "
            "reconciliation.snapshot_usd. Models in fallback_pricing_models used the "
            "generic 'default' rate for estimated calls."
        ),
    }


def build_cli_calls(stats: dict[str, Any]) -> list[dict[str, Any]]:
    """Turn parsed usage/compaction events into normalized call records.

    Agent names are resolved after the whole file is read (``subagent.started``
    may appear after the first call); a compaction whose ``agentId`` is not a
    known subagent belongs to the main agent. Each call's skill is the most
    recent ``skill.invoked`` of its own agent at the call's timestamp.
    """
    started = stats.get("subagent_started", {})
    timelines = {
        agent: sorted(items, key=lambda it: it[0])
        for agent, items in stats.get("skill_timelines", {}).items()
    }

    def _skill(agent_id: str | None, ts_ms: int | None) -> str:
        return core.active_skill_at_ts(ts_ms, timelines.get(agent_id, [])) or "unknown"

    calls: list[dict[str, Any]] = []
    for raw, kind in (
        *((r, core.CALL_KIND_REQUEST) for r in stats.get("usage_calls", [])),
        *((r, core.CALL_KIND_COMPACTION) for r in stats.get("compaction_calls", [])),
    ):
        raw_agent = raw["agent_id"]
        agent_id = raw_agent if raw_agent and (raw_agent in started or kind == "request") else None
        agent_name = (
            None if agent_id is None else (started.get(agent_id) or {}).get("name") or agent_id
        )
        calls.append(
            core.make_call(
                ts_ms=raw["ts_ms"],
                model=raw["model"],
                input_tokens=raw["input"],
                cached_tokens=raw["cached"],
                cache_write_tokens=raw["cache_write"],
                output_tokens=raw["output"],
                nano_aiu=raw["nano_aiu"],
                agent=agent_name,
                agent_id=agent_id,
                initiator=(
                    raw.get("initiator")
                    if kind == core.CALL_KIND_REQUEST
                    else core.CALL_KIND_COMPACTION
                ),
                kind=kind,
                skill=_skill(agent_id, raw["ts_ms"]),
                llm_calls=raw.get("llm_calls") or 1,
                premium_requests=raw.get("premium_requests"),
            )
        )
    calls.sort(key=lambda c: (c["ts_ms"] is None, c["ts_ms"] or 0))
    return calls


# ─── Cheap metadata listing (no events.jsonl parse) ─────────────────────────


def _first_event_created_ms(session_dir: Path) -> int | None:
    """Best-effort session creation time from the first recorded event.

    Reads only the first non-empty line of ``events.jsonl`` (not a full
    parse) to keep session listing cheap. Prefers ``session.start``'s
    ``startTime``, falling back to the first event's own ``timestamp``.
    Returns ``None`` — never a file modification time, which is not evidence
    of when the session itself was created — when neither is available.
    """
    events_path = session_dir / EVENTS_FILENAME
    try:
        with events_path.open(encoding="utf-8") as f:
            for raw in f:
                line = raw.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    return None
                if not isinstance(obj, dict):
                    return None
                data = obj.get("data")
                if (
                    obj.get("type") == "session.start"
                    and isinstance(data, dict)
                    and data.get("startTime")
                ):
                    return core.parse_since_to_ms(data["startTime"])
                if obj.get("timestamp"):
                    return core.parse_since_to_ms(obj["timestamp"])
                return None
    except OSError:
        return None
    return None


def _session_metadata(session_dir: Path) -> dict[str, Any]:
    """Build a cheap (near parse-free) metadata record for a session directory."""
    workspace_meta = read_workspace_metadata(session_dir)
    created_ms = _yaml_to_ms(workspace_meta.get("created_at"))
    updated_ms = _yaml_to_ms(workspace_meta.get("updated_at"))
    if created_ms is None:
        created_ms = _first_event_created_ms(session_dir)
    return {
        "session_id": session_dir.name,
        "title": _resolve_title(workspace_meta, None),
        "workspace_folder": workspace_meta.get("cwd") or "",
        "workspace_hash": "",
        "created_ms": created_ms,
        "last_message_ms": updated_ms or created_ms,
        "has_debug_logs": True,
        "debug_log_dir": str(session_dir),
        "provider": "cli",
    }


def find_session_dir_by_id(session_id: str, roots: list[Path]) -> Path | None:
    """Search session-state roots for a session directory matching ``session_id``."""
    for root in roots:
        candidate = root / session_id
        if is_valid_session_dir(candidate):
            return candidate
    return None


def find_sessions_by_title(title: str, roots: list[Path]) -> list[dict[str, Any]]:
    """Search session-state roots for sessions whose title contains ``title``."""
    lower = title.lower()
    matches: list[dict[str, Any]] = []
    for root in roots:
        for session_dir in list_session_dirs(root):
            meta = _session_metadata(session_dir)
            if lower in (meta.get("title") or "").lower():
                matches.append(meta)
    return sorted(matches, key=lambda s: s.get("created_ms") or 0, reverse=True)


def find_latest_session_dir(roots: list[Path], workspace_filter: str | None = None) -> Path | None:
    """Return the most recently modified valid session directory across ``roots``."""
    latest: Path | None = None
    latest_mtime = 0.0
    for root in roots:
        for session_dir in list_session_dirs(root):
            if workspace_filter:
                meta = read_workspace_metadata(session_dir)
                if workspace_filter not in (meta.get("cwd") or ""):
                    continue
            events_path = session_dir / EVENTS_FILENAME
            try:
                mtime = events_path.stat().st_mtime
            except OSError:
                continue
            if mtime > latest_mtime:
                latest_mtime = mtime
                latest = session_dir
    return latest


def list_recent_sessions(
    roots: list[Path],
    limit: int = 20,
    since_ms: int | None = None,
    workspace_filter: str | None = None,
    require_logs: bool = False,  # noqa: ARG001 - kept for parity with vscode's signature
    active_since_ms: int | None = None,
) -> list[dict[str, Any]]:
    """List CLI/App sessions from ``roots``, sorted most-recent first.

    ``require_logs`` is accepted for signature parity with
    :func:`copilot_session_usage._internal.vscode.list_recent_sessions`: every
    directory returned by :func:`list_session_dirs` already has ``events.jsonl``,
    so it has no additional effect here. ``active_since_ms`` keeps sessions
    whose ``events.jsonl`` was modified at or after that instant (instead of
    filtering by creation time), so a long-running session that started
    before a call window is still analyzed.
    """
    all_sessions: list[dict[str, Any]] = []
    for root in roots:
        for session_dir in list_session_dirs(root):
            if active_since_ms is not None:
                try:
                    mtime_ms = (session_dir / EVENTS_FILENAME).stat().st_mtime * 1000
                except OSError:
                    continue
                if mtime_ms < active_since_ms:
                    continue
            meta = _session_metadata(session_dir)
            if since_ms and (meta.get("created_ms") or 0) < since_ms:
                continue
            if workspace_filter and workspace_filter not in meta.get("workspace_folder", ""):
                continue
            meta["created_at"] = core.ts_to_iso(meta.get("created_ms"))
            meta["last_activity_at"] = core.ts_to_iso(meta.get("last_message_ms"))
            all_sessions.append(meta)
    all_sessions.sort(key=lambda s: s.get("created_ms") or 0, reverse=True)
    return all_sessions[:limit]
