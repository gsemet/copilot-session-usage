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


def _priced_bucket(v: dict[str, int | None]) -> dict[str, int]:
    """Narrow a per-model token bucket to concrete ``int``s for the shared pricing calculation.

    Only call this after confirming ``input``/``output``/``cached`` are all
    non-``None`` (see ``global_per_model`` completeness checks in
    :func:`analyze_cli_session`) — the ``or 0`` here is just a type
    narrowing, not a fallback for genuinely missing evidence: a reported
    ``0`` stays ``0``, and a real value is never replaced.
    """
    return {"input": v["input"] or 0, "output": v["output"] or 0, "cached": v["cached"] or 0}


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
    }

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


def analyze_cli_session(source: Path, pricing: dict[str, Any]) -> dict[str, Any]:
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

    session_id: str | None = None
    if session_dir is not None and SESSION_ID_RE.fullmatch(session_dir.name):
        # Trust the on-disk layout convention set by Copilot CLI itself.
        session_id = session_dir.name
    elif stats.get("session_id") and SESSION_ID_RE.fullmatch(str(stats["session_id"])):
        # Explicit source metadata: the session.start event's own sessionId.
        session_id = stats["session_id"]
    if session_id is None:
        msg = (
            f"could not determine a canonical session UUID for {events_path}: neither the "
            "session directory name nor a session.start event's sessionId is a valid UUID. "
            "Refusing to fabricate a session identity from the file name."
        )
        raise ValueError(msg)

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

    global_per_model: dict[str, dict[str, int | None]] = {}
    total_premium_requests: int | float | None = None
    total_nano_aiu: int | float | None = None
    shutdown_type: str | None = None
    code_changes: dict[str, Any] | None = None
    active_duration_s: int | None = None
    models_from_evidence: set[str] = set()

    if shutdown is not None:
        model_metrics = shutdown.get("modelMetrics")
        if model_metrics is not None and not isinstance(model_metrics, dict):
            diagnostics.append(
                "session.shutdown.modelMetrics was not a mapping; per-model token breakdown "
                "is unavailable."
            )
        for model, metrics in _as_mapping(model_metrics).items():
            if not isinstance(model, str) or not model:
                continue
            if not isinstance(metrics, dict):
                diagnostics.append(
                    f"modelMetrics entry for {model!r} was not a mapping; skipped rather than "
                    "fabricated."
                )
                continue
            usage = _as_mapping(metrics.get("usage"))
            requests = _as_mapping(metrics.get("requests"))
            global_per_model[model] = {
                "input": _as_int(usage.get("inputTokens")),
                "output": _as_int(usage.get("outputTokens")),
                "cached": _as_int(usage.get("cacheReadTokens")),
                "calls": _as_int(requests.get("count")),
            }
            models_from_evidence.add(model)
        total_premium_requests = _as_number(shutdown.get("totalPremiumRequests"))
        total_nano_aiu = _as_number(shutdown.get("totalNanoAiu"))
        shutdown_type = _clean_str(shutdown.get("shutdownType"))
        raw_code_changes = shutdown.get("codeChanges")
        if raw_code_changes is not None and not isinstance(raw_code_changes, dict):
            diagnostics.append("session.shutdown.codeChanges was not a mapping; ignored.")
        else:
            code_changes = raw_code_changes
        api_duration_ms = _as_number(shutdown.get("totalApiDurationMs"))
        if api_duration_ms is not None:
            active_duration_s = round(api_duration_ms / 1000.0)
    elif checkpoint is not None:
        diagnostics.append(
            "no session.shutdown event found (the session may still be active or was "
            "interrupted); per-model token totals and the shared cost calculation are "
            "unavailable. Only provider-native counters (nanoAiu, premium requests) from the "
            "last usage checkpoint are reported, under provider_usage."
        )
        total_premium_requests = _as_number(checkpoint.get("totalPremiumRequests"))
        total_nano_aiu = _as_number(checkpoint.get("totalNanoAiu"))
        raw_cache_state = checkpoint.get("modelCacheState")
        if raw_cache_state is not None and not isinstance(raw_cache_state, list):
            diagnostics.append(
                "session.usage_checkpoint.modelCacheState was not a list; model identity from "
                "the checkpoint is unavailable."
            )
        for entry in _as_list(raw_cache_state):
            model_id = _clean_str(_as_mapping(entry).get("modelId"))
            if model_id:
                models_from_evidence.add(model_id)
    else:
        diagnostics.append(
            "no session.shutdown or session.usage_checkpoint event found in this session; "
            "usage totals and cost are unavailable."
        )

    if stats.get("selected_model"):
        models_from_evidence.add(stats["selected_model"])

    def _sum_available(values: list[int | None]) -> int | None:
        """Sum the reported values, preserving total absence as ``None``.

        Never fabricates a ``0`` contribution for a model missing this
        specific field: only models that actually reported the field
        contribute to the total, and the total itself is ``None`` (not
        ``0``) when none of them did.
        """
        available = [v for v in values if v is not None]
        return sum(available) if available else None

    if global_per_model:
        total_input = _sum_available([v["input"] for v in global_per_model.values()])
        total_output = _sum_available([v["output"] for v in global_per_model.values()])
        total_cached = _sum_available([v["cached"] for v in global_per_model.values()])
        total_calls = _sum_available([v["calls"] for v in global_per_model.values()])
        if total_input is None:
            cache_ratio: float | None = None
        elif total_input == 0:
            cache_ratio = 0.0
        elif total_cached is not None:
            cache_ratio = round(total_cached / total_input, 3)
        else:
            cache_ratio = None

        # Shared estimated_usd comes only from the shared model/pricing
        # calculation over evidence-backed tokens — never from provider-native
        # nanoAiu, which is kept separate under provider_usage. Pricing only
        # runs for a model whose input/output/cached tokens are all present:
        # partial evidence for a model excludes it from the priced total
        # (with a diagnostic) rather than crashing or fabricating a cost from
        # a missing field treated as zero.
        priceable_models = {
            model: v
            for model, v in global_per_model.items()
            if v["input"] is not None and v["output"] is not None and v["cached"] is not None
        }
        unpriceable_models = sorted(set(global_per_model) - set(priceable_models))
        if unpriceable_models:
            diagnostics.append(
                f"model(s) {unpriceable_models} reported incomplete token usage in "
                "modelMetrics; their cost is excluded from the session total (other available "
                "fields, such as call counts, are still reported)."
            )
        total_usd: float | None = (
            core.estimate_cost_for_file(
                {model: _priced_bucket(v) for model, v in priceable_models.items()}, pricing
            )
            if priceable_models
            else None
        )
    else:
        # No per-model token evidence (active/interrupted session, or only a
        # checkpoint). Preserve the absence instead of reporting zero.
        total_input = total_output = total_cached = total_calls = None
        cache_ratio = None
        total_usd = None

    def _model_row_cost(model: str, v: dict[str, int | None]) -> float | None:
        if v["input"] is None or v["output"] is None or v["cached"] is None:
            return None
        return round(core.estimate_cost_for_file({model: _priced_bucket(v)}, pricing), 6)

    model_breakdown = sorted(
        (
            {
                "model": model,
                "input_tokens": v["input"],
                "output_tokens": v["output"],
                "cached_tokens": v["cached"],
                "llm_calls": v["calls"],
                "estimated_usd": _model_row_cost(model, v),
            }
            for model, v in global_per_model.items()
        ),
        key=lambda x: (x["estimated_usd"] is not None, x["estimated_usd"] or 0.0),
        reverse=True,
    )
    fallback_pricing_models = sorted(
        model for model in global_per_model if core.model_uses_fallback_pricing(model, pricing)
    )

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

    # Subagent evidence, preserved separately from the shared per-model
    # totals: subagent.completed only reports a combined totalTokens figure,
    # never a validated input/output/cached split, so it cannot be folded
    # into model_breakdown/subagents without fabricating that split.
    subagent_rows: list[dict[str, Any]] = []
    for agent_id, started in stats.get("subagent_started", {}).items():
        completed = stats.get("subagent_completed", {}).get(agent_id, {})
        duration_ms = completed.get("duration_ms")
        subagent_rows.append(
            {
                "agent_id": agent_id,
                "name": started.get("name"),
                "model": completed.get("model") or started.get("model"),
                "total_tool_calls": completed.get("total_tool_calls"),
                "total_tokens_reported": completed.get("total_tokens"),
                "duration_seconds": (
                    round(duration_ms / 1000.0) if isinstance(duration_ms, (int, float)) else None
                ),
            }
        )
    subagent_rows.sort(key=lambda r: (r.get("name") or "", r.get("agent_id") or ""))

    provider_usage = {
        "total_nano_aiu": total_nano_aiu,
        "total_premium_requests": total_premium_requests,
        "shutdown_type": shutdown_type,
        "resume_count": stats.get("resume_count", 0),
        "code_changes": code_changes,
        "subagents": subagent_rows,
    }

    return {
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
        "total": {
            "input_tokens": total_input,
            "output_tokens": total_output,
            "cached_tokens": total_cached,
            "llm_calls": total_calls,
            "estimated_usd": round(total_usd, 4) if total_usd is not None else None,
            "cache_ratio": cache_ratio,
        },
        "models": sorted(models_from_evidence)
        if models_from_evidence
        else [m["model"] for m in model_breakdown],
        "fallback_pricing_models": fallback_pricing_models,
        "model_breakdown": model_breakdown,
        # Empty rather than fabricated: subagent.completed reports only a
        # combined totalTokens figure (see provider_usage["subagents"]), with
        # no validated input/output/cached split to populate this shared,
        # per-subagent token/cost contract honestly.
        "subagents": [],
        "skills": {
            "detected": skill_names,
            "active": active_skill,
            "breakdown": [],
            "tool_breakdown": tool_breakdown,
        },
        "provider_usage": provider_usage,
        "diagnostics": diagnostics,
        "pricing_note": (
            "Cost estimates use the shared token-based pricing calculation from "
            "data/models-and-pricing.yml, the same as the VS Code provider. GitHub Copilot's "
            "own nanoAiu billing figure is kept separate under provider_usage.total_nano_aiu "
            "and never replaces the shared calculation. Models listed in "
            "fallback_pricing_models were priced with the generic 'default' rate."
        ),
    }


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
) -> list[dict[str, Any]]:
    """List CLI/App sessions from ``roots``, sorted most-recent first.

    ``require_logs`` is accepted for signature parity with
    :func:`copilot_session_usage._internal.vscode.list_recent_sessions`: every
    directory returned by :func:`list_session_dirs` already has ``events.jsonl``,
    so it has no additional effect here.
    """
    all_sessions: list[dict[str, Any]] = []
    for root in roots:
        for session_dir in list_session_dirs(root):
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
