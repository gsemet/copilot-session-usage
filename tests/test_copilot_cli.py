"""Unit tests for the Copilot CLI/App provider (_internal/copilot_cli.py)."""

from __future__ import annotations

import json

import pytest

from copilot_session_usage._internal import copilot_cli, core

SID = "11111111-1111-1111-1111-111111111111"


@pytest.fixture
def pricing():
    return core.load_pricing(auto_refresh=False)


# ─── discovery ────────────────────────────────────────────────────────────────


def test_default_session_state_roots_empty_when_missing(tmp_path, mocker):
    mocker.patch("pathlib.Path.home", return_value=tmp_path)
    assert copilot_cli.default_session_state_roots() == []


def test_default_session_state_roots_found(tmp_path, mocker):
    root = tmp_path / ".copilot" / "session-state"
    root.mkdir(parents=True)
    mocker.patch("pathlib.Path.home", return_value=tmp_path)
    assert copilot_cli.default_session_state_roots() == [root]


def test_is_valid_session_dir_true(write_cli_session, tmp_path):
    session_dir = write_cli_session(tmp_path, SID)
    assert copilot_cli.is_valid_session_dir(session_dir) is True


def test_is_valid_session_dir_false_bad_name(tmp_path):
    session_dir = tmp_path / "not-a-uuid"
    session_dir.mkdir()
    (session_dir / "events.jsonl").write_text("{}\n", encoding="utf-8")
    assert copilot_cli.is_valid_session_dir(session_dir) is False


def test_is_valid_session_dir_false_missing_events(tmp_path):
    session_dir = tmp_path / SID
    session_dir.mkdir()
    assert copilot_cli.is_valid_session_dir(session_dir) is False


def test_list_session_dirs_filters_invalid(write_cli_session, tmp_path):
    write_cli_session(tmp_path, SID)
    (tmp_path / "not-a-uuid").mkdir()
    dirs = copilot_cli.list_session_dirs(tmp_path)
    assert [d.name for d in dirs] == [SID]


def test_list_session_dirs_missing_root(tmp_path):
    assert copilot_cli.list_session_dirs(tmp_path / "nope") == []


def test_find_session_dir_by_id(write_cli_session, tmp_path):
    write_cli_session(tmp_path, SID)
    found = copilot_cli.find_session_dir_by_id(SID, [tmp_path])
    assert found == tmp_path / SID


def test_find_session_dir_by_id_missing(tmp_path):
    assert copilot_cli.find_session_dir_by_id("missing", [tmp_path]) is None


def test_find_latest_session_dir(write_cli_session, tmp_path):
    older = write_cli_session(tmp_path, "11111111-1111-1111-1111-111111111111")
    newer = write_cli_session(tmp_path, "22222222-2222-2222-2222-222222222222")
    import os
    import time

    now = time.time()
    os.utime(older / "events.jsonl", (now - 100, now - 100))
    os.utime(newer / "events.jsonl", (now, now))
    assert copilot_cli.find_latest_session_dir([tmp_path]) == newer


def test_find_latest_session_dir_workspace_filter(write_cli_session, tmp_path):
    write_cli_session(
        tmp_path, SID, workspace={"cwd": "/proj-a", "created_at": "2026-01-01T00:00:00.000Z"}
    )
    assert copilot_cli.find_latest_session_dir([tmp_path], workspace_filter="/proj-b") is None
    assert copilot_cli.find_latest_session_dir([tmp_path], workspace_filter="/proj-a") is not None


def test_find_sessions_by_title(write_cli_session, tmp_path):
    write_cli_session(tmp_path, SID, workspace={"name": "Fixing the login bug", "cwd": "/proj"})
    matches = copilot_cli.find_sessions_by_title("login", [tmp_path])
    assert len(matches) == 1
    assert matches[0]["session_id"] == SID


def test_find_sessions_by_title_no_match(write_cli_session, tmp_path):
    write_cli_session(tmp_path, SID)
    assert copilot_cli.find_sessions_by_title("nonexistent-topic", [tmp_path]) == []


def test_list_recent_sessions_sorted_and_limited(write_cli_session, tmp_path):
    write_cli_session(
        tmp_path,
        "11111111-1111-1111-1111-111111111111",
        workspace={
            "created_at": "2026-01-01T00:00:00.000Z",
            "updated_at": "2026-01-01T00:00:00.000Z",
        },
    )
    write_cli_session(
        tmp_path,
        "22222222-2222-2222-2222-222222222222",
        workspace={
            "created_at": "2026-02-01T00:00:00.000Z",
            "updated_at": "2026-02-01T00:00:00.000Z",
        },
    )
    sessions = copilot_cli.list_recent_sessions([tmp_path], limit=1)
    assert len(sessions) == 1
    assert sessions[0]["session_id"] == "22222222-2222-2222-2222-222222222222"


def test_list_recent_sessions_since_filter(write_cli_session, tmp_path):
    write_cli_session(
        tmp_path,
        SID,
        workspace={
            "created_at": "2026-01-01T00:00:00.000Z",
            "updated_at": "2026-01-01T00:00:00.000Z",
        },
    )
    since_ms = core.parse_since_to_ms("2026-06-01")
    assert copilot_cli.list_recent_sessions([tmp_path], since_ms=since_ms) == []


def test_read_workspace_metadata_missing_file(tmp_path):
    session_dir = tmp_path / SID
    session_dir.mkdir()
    assert copilot_cli.read_workspace_metadata(session_dir) == {}


def test_read_workspace_metadata_malformed(tmp_path):
    session_dir = tmp_path / SID
    session_dir.mkdir()
    (session_dir / "workspace.yaml").write_text("foo: [1, 2\n  bar: baz", encoding="utf-8")
    assert copilot_cli.read_workspace_metadata(session_dir) == {}


def test_read_workspace_metadata_not_a_mapping(tmp_path):
    session_dir = tmp_path / SID
    session_dir.mkdir()
    (session_dir / "workspace.yaml").write_text("- a\n- b\n", encoding="utf-8")
    assert copilot_cli.read_workspace_metadata(session_dir) == {}


# ─── resolve_events_source ────────────────────────────────────────────────────


def test_resolve_events_source_session_dir(write_cli_session, tmp_path):
    session_dir = write_cli_session(tmp_path, SID)
    events_path, resolved_dir = copilot_cli.resolve_events_source(session_dir)
    assert events_path == session_dir / "events.jsonl"
    assert resolved_dir == session_dir


def test_resolve_events_source_direct_file(write_cli_session, tmp_path):
    session_dir = write_cli_session(tmp_path, SID)
    events_path, resolved_dir = copilot_cli.resolve_events_source(session_dir / "events.jsonl")
    assert events_path == session_dir / "events.jsonl"
    assert resolved_dir == session_dir


def test_resolve_events_source_missing_events_in_dir(tmp_path):
    empty_dir = tmp_path / SID
    empty_dir.mkdir()
    with pytest.raises(ValueError, match="missing events.jsonl"):
        copilot_cli.resolve_events_source(empty_dir)


def test_resolve_events_source_nonexistent(tmp_path):
    with pytest.raises(ValueError, match="not found"):
        copilot_cli.resolve_events_source(tmp_path / "does-not-exist")


# ─── parse_events_file / analyze_cli_session ─────────────────────────────────


def test_analyze_cli_session_full_shutdown(write_cli_session, tmp_path, pricing):
    session_dir = write_cli_session(tmp_path, SID)
    result = copilot_cli.analyze_cli_session(session_dir, pricing)

    assert result["session_id"] == SID
    assert result["provider"] == "cli"
    assert result["source"] == str(session_dir / "events.jsonl")
    assert result["title"] == "Test CLI Session"
    assert result["total"]["input_tokens"] == 1000
    assert result["total"]["output_tokens"] == 100
    assert result["total"]["llm_calls"] == 1
    assert result["models"] == ["gpt-5.6-luna"]
    assert result["model_breakdown"][0]["model"] == "gpt-5.6-luna"
    # Shared token-based pricing (input 0.20 + output 1.20 + cache-write delta
    # per data/models-and-pricing.yml for gpt-5.6-luna, ≤200K tier), not the
    # provider-native nanoAiu figure (which is kept separate, see below).
    assert result["total"]["estimated_usd"] == pytest.approx(0.0004, abs=1e-6)
    assert result["active_duration_seconds"] == 5
    assert result["skills"]["detected"] == ["my-skill"]
    assert result["skills"]["active"] == "my-skill"
    assert result["skills"]["breakdown"] == []
    assert result["subagents"] == []
    assert result["diagnostics"] == []
    tool_row = result["skills"]["tool_breakdown"][0]
    assert tool_row == {"tool": "read_file", "calls": 1, "skill": "my-skill", "subagent": "main"}
    assert result["provider_usage"]["total_nano_aiu"] == 100_000_000
    assert result["provider_usage"]["shutdown_type"] == "routine"
    assert result["provider_usage"]["subagents"] == []


def test_analyze_cli_session_no_shutdown_falls_back_to_checkpoint(
    write_cli_session, tmp_path, pricing
):
    events = [
        {
            "type": "session.start",
            "data": {
                "sessionId": SID,
                "version": 1,
                "startTime": "2026-01-01T00:00:00.000Z",
                "selectedModel": "gpt-5.6-luna",
                "context": {"cwd": "/proj"},
            },
            "id": "e1",
            "timestamp": "2026-01-01T00:00:00.000Z",
            "parentId": None,
        },
        {
            "type": "session.usage_checkpoint",
            "data": {
                "totalNanoAiu": 42_000_000,
                "totalPremiumRequests": 2,
                "modelCacheState": [{"modelId": "gpt-5.6-luna"}],
            },
            "id": "e2",
            "timestamp": "2026-01-01T00:05:00.000Z",
            "parentId": "e1",
        },
    ]
    session_dir = write_cli_session(tmp_path, SID, events=events, workspace={})
    result = copilot_cli.analyze_cli_session(session_dir, pricing)

    # No per-model token evidence at checkpoint granularity: preserved as
    # missing, never fabricated as a measured zero.
    assert result["total"]["input_tokens"] is None
    assert result["total"]["output_tokens"] is None
    assert result["total"]["cached_tokens"] is None
    assert result["total"]["llm_calls"] is None
    assert result["total"]["cache_ratio"] is None
    assert result["total"]["estimated_usd"] is None
    assert result["model_breakdown"] == []
    assert result["models"] == ["gpt-5.6-luna"]
    assert len(result["diagnostics"]) == 1
    assert "no session.shutdown event found" in result["diagnostics"][0]
    # Provider-native nanoAiu is preserved separately and never used to
    # populate the shared estimated_usd.
    assert result["provider_usage"]["total_premium_requests"] == 2
    assert result["provider_usage"]["total_nano_aiu"] == 42_000_000


def test_analyze_cli_session_no_shutdown_no_checkpoint(write_cli_session, tmp_path, pricing):
    events = [
        {
            "type": "session.start",
            "data": {
                "sessionId": SID,
                "version": 1,
                "startTime": "2026-01-01T00:00:00.000Z",
                "selectedModel": "gpt-5.6-luna",
                "context": {"cwd": "/proj"},
            },
            "id": "e1",
            "timestamp": "2026-01-01T00:00:00.000Z",
            "parentId": None,
        },
    ]
    session_dir = write_cli_session(tmp_path, SID, events=events, workspace={})
    result = copilot_cli.analyze_cli_session(session_dir, pricing)
    assert result["total"]["estimated_usd"] is None
    assert result["total"]["input_tokens"] is None
    assert "usage totals and cost are unavailable" in result["diagnostics"][0]


def test_analyze_cli_session_malformed_lines_diagnostic(write_cli_session, tmp_path, pricing):
    session_dir = write_cli_session(tmp_path, SID)
    events_path = session_dir / "events.jsonl"
    with events_path.open("a", encoding="utf-8") as f:
        f.write("{not valid json\n")
    result = copilot_cli.analyze_cli_session(session_dir, pricing)
    assert any("malformed JSON line" in d for d in result["diagnostics"])


def test_analyze_cli_session_unsupported_schema_version_diagnostic(
    write_cli_session, tmp_path, pricing
):
    events = [
        {
            "type": "session.start",
            "data": {
                "sessionId": SID,
                "version": 99,
                "startTime": "2026-01-01T00:00:00.000Z",
                "selectedModel": "gpt-5.6-luna",
                "context": {"cwd": "/proj"},
            },
            "id": "e1",
            "timestamp": "2026-01-01T00:00:00.000Z",
            "parentId": None,
        },
    ]
    session_dir = write_cli_session(tmp_path, SID, events=events, workspace={})
    result = copilot_cli.analyze_cli_session(session_dir, pricing)
    assert any("schema version" in d for d in result["diagnostics"])


def test_parse_events_file_mixed_type_unsupported_versions_never_crashes_sort(tmp_path):
    """Mixed int and string versions must never make sorting the diagnostic fail.

    sorted() diagnostic in analyze_cli_session raise TypeError (int/str aren't
    orderable in Python 3): both are normalized to str before being tracked.
    """
    events = [
        {
            "type": "session.start",
            "data": {"sessionId": SID, "version": 99},
            "id": "e1",
            "timestamp": "2026-01-01T00:00:00.000Z",
            "parentId": None,
        },
        {
            "type": "session.start",
            "data": {"sessionId": SID, "version": "beta"},
            "id": "e2",
            "timestamp": "2026-01-01T00:00:01.000Z",
            "parentId": "e1",
        },
    ]
    events_path = tmp_path / "events.jsonl"
    events_path.write_text("\n".join(json.dumps(e) for e in events) + "\n", encoding="utf-8")
    stats = copilot_cli.parse_events_file(events_path)
    assert stats["unsupported_versions"] == {"99", "beta"}
    assert all(isinstance(v, str) for v in stats["unsupported_versions"])
    # sorted() must not raise even with a mix of int- and str-shaped versions.
    assert sorted(stats["unsupported_versions"]) == ["99", "beta"]


def test_analyze_cli_session_unknown_event_type_diagnostic(write_cli_session, tmp_path, pricing):
    """An unrecognized structured event type is tracked.

    and surfaced as an explicit diagnostic rather than silently ignored.
    """
    events = [
        {
            "type": "session.start",
            "data": {
                "sessionId": SID,
                "version": 1,
                "startTime": "2026-01-01T00:00:00.000Z",
                "context": {"cwd": "/proj"},
            },
            "id": "e1",
            "timestamp": "2026-01-01T00:00:00.000Z",
            "parentId": None,
        },
        {
            "type": "future.new_event_kind",
            "data": {"foo": "bar"},
            "id": "e2",
            "timestamp": "2026-01-01T00:00:01.000Z",
            "parentId": "e1",
        },
        {
            "type": "future.new_event_kind",
            "data": {"foo": "baz"},
            "id": "e3",
            "timestamp": "2026-01-01T00:00:02.000Z",
            "parentId": "e2",
        },
    ]
    session_dir = write_cli_session(tmp_path, SID, events=events, workspace={})
    result = copilot_cli.analyze_cli_session(session_dir, pricing)
    assert any("future.new_event_kind" in d and "2 event(s)" in d for d in result["diagnostics"])


def test_parse_events_file_unknown_event_type_counted(tmp_path):
    """Unknown event types are counted per-type; empty/missing 'type' is not."""
    events = [
        {"type": "session.start", "data": {"sessionId": SID}, "timestamp": None},
        {"type": "totally.unknown", "data": {}, "timestamp": None},
        {"type": "totally.unknown", "data": {}, "timestamp": None},
        {"type": "another.unknown", "data": {}, "timestamp": None},
        {"type": "", "data": {}, "timestamp": None},
        {"data": {}, "timestamp": None},
    ]
    events_path = tmp_path / "events.jsonl"
    events_path.write_text("\n".join(json.dumps(e) for e in events) + "\n", encoding="utf-8")
    stats = copilot_cli.parse_events_file(events_path)
    assert stats["unknown_event_types"] == {"totally.unknown": 2, "another.unknown": 1}


def test_parse_events_file_subagent_events_without_agent_id_not_unknown(tmp_path):
    """A recognized subagent.* type without an agentId is dropped, not mistaken for.

    an unrecognized event type (it must not appear in unknown_event_types).
    """
    events = [
        {"type": "session.start", "data": {"sessionId": SID}, "timestamp": None},
        {"type": "subagent.started", "data": {"agentDisplayName": "sub"}, "timestamp": None},
        {"type": "subagent.completed", "data": {"totalTokens": 5}, "timestamp": None},
    ]
    events_path = tmp_path / "events.jsonl"
    events_path.write_text("\n".join(json.dumps(e) for e in events) + "\n", encoding="utf-8")
    stats = copilot_cli.parse_events_file(events_path)
    assert stats["unknown_event_types"] == {}
    assert stats["subagent_started"] == {}
    assert stats["subagent_completed"] == {}


def test_analyze_cli_session_exported_file_without_session_dir(
    write_cli_session, tmp_path, pricing
):
    """A relocated events.jsonl with no sibling workspace.yaml still analyzes."""
    session_dir = write_cli_session(tmp_path, SID)
    exported = tmp_path / "exported-events.jsonl"
    exported.write_text(
        (session_dir / "events.jsonl").read_text(encoding="utf-8"), encoding="utf-8"
    )
    result = copilot_cli.analyze_cli_session(exported, pricing)
    assert result["session_id"] == SID  # recovered from session.start's sessionId
    assert result["title"] is None  # no workspace.yaml sidecar available


def test_analyze_cli_session_invalid_source_raises(tmp_path, pricing):
    with pytest.raises(ValueError):
        copilot_cli.analyze_cli_session(tmp_path / "missing", pricing)


def test_analyze_cli_session_rejects_arbitrary_json_file(tmp_path, pricing):
    """A JSON-per-line file with no 'type' fields is not a Copilot CLI event log."""
    arbitrary = tmp_path / "not-events.jsonl"
    arbitrary.write_text('{"foo": "bar"}\n{"baz": 1}\n', encoding="utf-8")
    with pytest.raises(ValueError, match="does not look like a Copilot CLI events.jsonl file"):
        copilot_cli.analyze_cli_session(arbitrary, pricing)


def test_analyze_cli_session_rejects_empty_file(tmp_path, pricing):
    empty = tmp_path / "empty-events.jsonl"
    empty.write_text("", encoding="utf-8")
    with pytest.raises(ValueError, match="the file is empty"):
        copilot_cli.analyze_cli_session(empty, pricing)


def test_analyze_cli_session_rejects_missing_uuid_identity(tmp_path, pricing):
    """A recognized event log with no UUID directory name nor valid sessionId is rejected."""
    exported = tmp_path / "some-export.jsonl"
    events = [
        {
            "type": "session.start",
            "data": {
                "sessionId": "not-a-valid-uuid",
                "version": 1,
                "startTime": "2026-01-01T00:00:00.000Z",
            },
            "id": "e1",
            "timestamp": "2026-01-01T00:00:00.000Z",
            "parentId": None,
        },
    ]
    exported.write_text("\n".join(json.dumps(e) for e in events) + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="could not determine a canonical session UUID"):
        copilot_cli.analyze_cli_session(exported, pricing)


def test_parse_events_file_tolerates_non_dict_json_lines(tmp_path):
    """A line that is valid JSON but not an object is skipped, not a crash."""
    events_path = tmp_path / "events.jsonl"
    events_path.write_text(
        "[1, 2, 3]\n"
        + json.dumps({"type": "session.start", "data": {"sessionId": SID}, "timestamp": None})
        + "\n",
        encoding="utf-8",
    )
    stats = copilot_cli.parse_events_file(events_path)
    assert stats["malformed_lines"] == 1
    assert stats["structured_event_lines"] == 1
    assert stats["session_id"] == SID


def test_resolve_title_prefers_name_over_summary():
    meta = {"name": "Renamed title", "summary": "Fallback summary"}
    assert copilot_cli._resolve_title(meta, None) == "Renamed title"


def test_resolve_title_falls_back_to_renamed_and_summary():
    assert copilot_cli._resolve_title({}, "Live rename") == "Live rename"
    assert copilot_cli._resolve_title({"summary": "A summary"}, None) == "A summary"
    assert copilot_cli._resolve_title({}, None) is None


# ─── resolve_session_state_roots (click-facing) ──────────────────────────────


def test_resolve_session_state_roots_explicit(tmp_path):
    root = tmp_path / "custom-root"
    root.mkdir()
    assert copilot_cli.resolve_session_state_roots(str(root)) == [root]


def test_resolve_session_state_roots_explicit_missing(tmp_path):
    import click

    with pytest.raises(click.ClickException, match="not found"):
        copilot_cli.resolve_session_state_roots(str(tmp_path / "missing"))


def test_resolve_session_state_roots_default_missing(mocker):
    import click

    mocker.patch(
        "copilot_session_usage._internal.copilot_cli.default_session_state_roots",
        return_value=[],
    )
    with pytest.raises(click.ClickException, match="No Copilot CLI session-state directory"):
        copilot_cli.resolve_session_state_roots(None)


def test_resolve_session_state_roots_default_found(tmp_path, mocker):
    mocker.patch(
        "copilot_session_usage._internal.copilot_cli.default_session_state_roots",
        return_value=[tmp_path],
    )
    assert copilot_cli.resolve_session_state_roots(None) == [tmp_path]


def test_parse_events_file_reads_malformed_and_valid_lines(tmp_path):
    events_path = tmp_path / "events.jsonl"
    events_path.write_text(
        "not json\n" + json.dumps({"type": "session.start", "data": {}, "timestamp": None}) + "\n",
        encoding="utf-8",
    )
    stats = copilot_cli.parse_events_file(events_path)
    assert stats["malformed_lines"] == 1
    assert stats["line_count"] == 2


# ─── malformed/shape-varying evidence hardening ──────────────────────────────


def test_parse_events_file_tolerates_non_string_and_invalid_timestamps(tmp_path):
    """Non-string/unparseable timestamps never crash parsing; they are counted, not fabricated."""
    events = [
        {"type": "session.start", "data": {"sessionId": SID}, "timestamp": 1735689600000},
        {"type": "skill.invoked", "data": {"name": "my-skill"}, "timestamp": "not-a-date"},
        {"type": "skill.invoked", "data": {"name": "my-skill"}, "timestamp": {"nested": True}},
        {"type": "skill.invoked", "data": {"name": "my-skill"}, "timestamp": ["a", "list"]},
    ]
    events_path = tmp_path / "events.jsonl"
    events_path.write_text("\n".join(json.dumps(e) for e in events) + "\n", encoding="utf-8")
    stats = copilot_cli.parse_events_file(events_path)
    assert stats["malformed_lines"] == 0
    assert stats["session_id"] == SID
    # An int, an unparseable string, and two non-string values: all invalid.
    assert stats["invalid_timestamp_lines"] == 4
    assert stats["last_event_ms"] is None


def test_parse_events_file_tolerates_non_mapping_data(tmp_path):
    """A 'data' field that isn't a mapping is treated as empty, never crashes."""
    events = [
        {"type": "session.start", "data": "not-a-mapping", "timestamp": None},
        {"type": "tool.execution_start", "data": ["a", "list"], "timestamp": None},
        {"type": "tool.execution_complete", "data": None, "timestamp": None},
        {"type": "skill.invoked", "data": 42, "timestamp": None},
    ]
    events_path = tmp_path / "events.jsonl"
    events_path.write_text("\n".join(json.dumps(e) for e in events) + "\n", encoding="utf-8")
    stats = copilot_cli.parse_events_file(events_path)
    assert stats["structured_event_lines"] == 4
    assert stats["session_id"] is None  # sessionId unavailable from a non-mapping data
    assert stats["skill_events"] == []  # no valid skill name extracted


def test_analyze_cli_session_non_mapping_model_metrics_diagnostic(
    write_cli_session, tmp_path, pricing
):
    """A non-mapping 'modelMetrics' degrades to unavailable totals, not a crash."""
    events = [
        {
            "type": "session.start",
            "data": {"sessionId": SID, "version": 1, "startTime": "2026-01-01T00:00:00.000Z"},
            "id": "e1",
            "timestamp": "2026-01-01T00:00:00.000Z",
            "parentId": None,
        },
        {
            "type": "session.shutdown",
            "data": {"shutdownType": "routine", "modelMetrics": "not-a-mapping"},
            "id": "e2",
            "timestamp": "2026-01-01T00:00:05.000Z",
            "parentId": "e1",
        },
    ]
    session_dir = write_cli_session(tmp_path, SID, events=events, workspace={})
    result = copilot_cli.analyze_cli_session(session_dir, pricing)
    assert result["model_breakdown"] == []
    assert result["total"]["input_tokens"] is None
    assert result["total"]["estimated_usd"] is None
    assert any("modelMetrics was not a mapping" in d for d in result["diagnostics"])


def test_analyze_cli_session_skips_non_mapping_per_model_entry(
    write_cli_session, tmp_path, pricing
):
    """One malformed per-model entry is skipped with a diagnostic; other models are unaffected."""
    events = [
        {
            "type": "session.start",
            "data": {"sessionId": SID, "version": 1, "startTime": "2026-01-01T00:00:00.000Z"},
            "id": "e1",
            "timestamp": "2026-01-01T00:00:00.000Z",
            "parentId": None,
        },
        {
            "type": "session.shutdown",
            "data": {
                "shutdownType": "routine",
                "modelMetrics": {
                    "broken-model": "not-a-mapping",
                    "gpt-5.6-luna": {
                        "requests": {"count": 1},
                        "usage": {
                            "inputTokens": 1000,
                            "outputTokens": 100,
                            "cacheReadTokens": 0,
                        },
                    },
                },
            },
            "id": "e2",
            "timestamp": "2026-01-01T00:00:05.000Z",
            "parentId": "e1",
        },
    ]
    session_dir = write_cli_session(tmp_path, SID, events=events, workspace={})
    result = copilot_cli.analyze_cli_session(session_dir, pricing)
    assert [m["model"] for m in result["model_breakdown"]] == ["gpt-5.6-luna"]
    assert result["total"]["input_tokens"] == 1000
    assert result["total"]["estimated_usd"] is not None
    assert any("broken-model" in d for d in result["diagnostics"])


def test_analyze_cli_session_missing_per_model_field_preserved_as_none(
    write_cli_session, tmp_path, pricing
):
    """A model missing one usage field keeps that field as None, not a fabricated zero."""
    events = [
        {
            "type": "session.start",
            "data": {"sessionId": SID, "version": 1, "startTime": "2026-01-01T00:00:00.000Z"},
            "id": "e1",
            "timestamp": "2026-01-01T00:00:00.000Z",
            "parentId": None,
        },
        {
            "type": "session.shutdown",
            "data": {
                "shutdownType": "routine",
                "modelMetrics": {
                    "gpt-5.6-luna": {
                        "requests": {"count": 1},
                        # outputTokens is entirely absent from the usage evidence.
                        "usage": {"inputTokens": 1000, "cacheReadTokens": 0},
                    }
                },
            },
            "id": "e2",
            "timestamp": "2026-01-01T00:00:05.000Z",
            "parentId": "e1",
        },
    ]
    session_dir = write_cli_session(tmp_path, SID, events=events, workspace={})
    result = copilot_cli.analyze_cli_session(session_dir, pricing)
    row = result["model_breakdown"][0]
    assert row["input_tokens"] == 1000
    assert row["output_tokens"] is None
    assert row["cached_tokens"] == 0
    # Incomplete evidence for this model: cost is unavailable, not fabricated.
    assert row["estimated_usd"] is None
    assert result["total"]["estimated_usd"] is None
    assert result["total"]["output_tokens"] is None
    assert any("incomplete token usage" in d for d in result["diagnostics"])
    # Calls are still preserved even though tokens are incomplete.
    assert result["total"]["llm_calls"] == 1


def test_analyze_cli_session_checkpoint_non_list_model_cache_state(
    write_cli_session, tmp_path, pricing
):
    """A non-list 'modelCacheState' at checkpoint granularity never crashes."""
    events = [
        {
            "type": "session.start",
            "data": {"sessionId": SID, "version": 1, "startTime": "2026-01-01T00:00:00.000Z"},
            "id": "e1",
            "timestamp": "2026-01-01T00:00:00.000Z",
            "parentId": None,
        },
        {
            "type": "session.usage_checkpoint",
            "data": {"totalNanoAiu": 1, "modelCacheState": "not-a-list"},
            "id": "e2",
            "timestamp": "2026-01-01T00:05:00.000Z",
            "parentId": "e1",
        },
    ]
    session_dir = write_cli_session(tmp_path, SID, events=events, workspace={})
    result = copilot_cli.analyze_cli_session(session_dir, pricing)
    assert result["total"]["estimated_usd"] is None
    assert result["models"] == []
    assert any("modelCacheState was not a list" in d for d in result["diagnostics"])


def test_analyze_cli_session_checkpoint_non_mapping_model_cache_entry(
    write_cli_session, tmp_path, pricing
):
    """A non-mapping entry inside 'modelCacheState' is skipped, not a crash."""
    events = [
        {
            "type": "session.start",
            "data": {"sessionId": SID, "version": 1, "startTime": "2026-01-01T00:00:00.000Z"},
            "id": "e1",
            "timestamp": "2026-01-01T00:00:00.000Z",
            "parentId": None,
        },
        {
            "type": "session.usage_checkpoint",
            "data": {"totalNanoAiu": 1, "modelCacheState": ["not-a-mapping", {"modelId": "m1"}]},
            "id": "e2",
            "timestamp": "2026-01-01T00:05:00.000Z",
            "parentId": "e1",
        },
    ]
    session_dir = write_cli_session(tmp_path, SID, events=events, workspace={})
    result = copilot_cli.analyze_cli_session(session_dir, pricing)
    assert result["models"] == ["m1"]


def test_parse_events_file_non_hashable_schema_version(tmp_path):
    """An unhashable/malformed 'version' value in session.start never crashes tracking."""
    events_path = tmp_path / "events.jsonl"
    events_path.write_text(
        json.dumps(
            {
                "type": "session.start",
                "data": {"sessionId": SID, "version": ["not", "hashable"]},
                "timestamp": None,
            }
        )
        + "\n",
        encoding="utf-8",
    )
    stats = copilot_cli.parse_events_file(events_path)
    assert stats["session_id"] == SID
    assert stats["unsupported_versions"] == {"['not', 'hashable']"}


def test_parse_events_file_non_mapping_context_and_arguments(tmp_path):
    """A non-mapping 'context'/'arguments' field never crashes cwd/title extraction."""
    events = [
        {
            "type": "session.start",
            "data": {"sessionId": SID, "context": "not-a-mapping"},
            "timestamp": None,
        },
        {
            "type": "external_tool.requested",
            "data": {"toolName": "rename_session", "arguments": "not-a-mapping"},
            "timestamp": None,
        },
    ]
    events_path = tmp_path / "events.jsonl"
    events_path.write_text("\n".join(json.dumps(e) for e in events) + "\n", encoding="utf-8")
    stats = copilot_cli.parse_events_file(events_path)
    assert stats["cwd"] is None
    assert stats["renamed_title"] is None


def test_parse_events_file_non_string_tool_call_id(tmp_path):
    """A non-string 'toolCallId' is treated as absent, never used as an unhashable dict key."""
    events = [
        {
            "type": "tool.execution_start",
            "data": {"toolCallId": ["not", "hashable"], "toolName": "read_file"},
            "timestamp": None,
        },
        {
            "type": "tool.execution_complete",
            "data": {"toolCallId": ["not", "hashable"], "success": True},
            "timestamp": None,
        },
    ]
    events_path = tmp_path / "events.jsonl"
    events_path.write_text("\n".join(json.dumps(e) for e in events) + "\n", encoding="utf-8")
    stats = copilot_cli.parse_events_file(events_path)
    assert list(stats["tool_rows"].values())[0]["calls"] == 1


# ─── subagent/agentId attribution ────────────────────────────────────────────


def _subagent_events(main_agent_tool: bool = True) -> list[dict]:
    """Build an event log with one main-session tool call and one subagent tool call."""
    agent_id = "22222222-2222-2222-2222-222222222222"
    events = [
        {
            "type": "session.start",
            "data": {
                "sessionId": SID,
                "version": 1,
                "startTime": "2026-01-01T00:00:00.000Z",
                "selectedModel": "gpt-5.6-luna",
                "context": {"cwd": "/proj"},
            },
            "id": "e1",
            "timestamp": "2026-01-01T00:00:00.000Z",
            "parentId": None,
        },
    ]
    if main_agent_tool:
        events += [
            {
                "type": "skill.invoked",
                "data": {"name": "main-skill"},
                "id": "e2",
                "timestamp": "2026-01-01T00:00:01.000Z",
                "parentId": "e1",
            },
            {
                "type": "tool.execution_start",
                "data": {"toolCallId": "call-main", "toolName": "read_file"},
                "id": "e3",
                "timestamp": "2026-01-01T00:00:02.000Z",
                "parentId": "e2",
            },
            {
                "type": "tool.execution_complete",
                "data": {"toolCallId": "call-main", "success": True},
                "id": "e4",
                "timestamp": "2026-01-01T00:00:03.000Z",
                "parentId": "e3",
            },
        ]
    events += [
        {
            "type": "subagent.started",
            "data": {
                "toolCallId": "call-spawn",
                "agentName": "Test Subagent",
                "agentDisplayName": "Test Subagent",
                "model": "gpt-5.6-luna",
            },
            "agentId": agent_id,
            "id": "e5",
            "timestamp": "2026-01-01T00:00:04.000Z",
            "parentId": "e1",
        },
        {
            "type": "skill.invoked",
            "data": {"name": "sub-skill"},
            "agentId": agent_id,
            "id": "e6",
            "timestamp": "2026-01-01T00:00:05.000Z",
            "parentId": "e5",
        },
        {
            "type": "tool.execution_start",
            "data": {"toolCallId": "call-sub", "toolName": "write_file"},
            "agentId": agent_id,
            "id": "e7",
            "timestamp": "2026-01-01T00:00:06.000Z",
            "parentId": "e6",
        },
        {
            "type": "tool.execution_complete",
            "data": {"toolCallId": "call-sub", "success": True},
            "agentId": agent_id,
            "id": "e8",
            "timestamp": "2026-01-01T00:00:07.000Z",
            "parentId": "e7",
        },
        {
            "type": "subagent.completed",
            "data": {
                "toolCallId": "call-spawn",
                "agentName": "Test Subagent",
                "model": "gpt-5.6-luna",
                "totalToolCalls": 1,
                "totalTokens": 1234,
                "durationMs": 3000,
            },
            "agentId": agent_id,
            "id": "e9",
            "timestamp": "2026-01-01T00:00:08.000Z",
            "parentId": "e8",
        },
    ]
    return events


def test_tool_breakdown_attributes_subagent_tool_calls(write_cli_session, tmp_path, pricing):
    session_dir = write_cli_session(tmp_path, SID, events=_subagent_events(), workspace={})
    result = copilot_cli.analyze_cli_session(session_dir, pricing)

    tool_breakdown = {row["tool"]: row for row in result["skills"]["tool_breakdown"]}
    assert tool_breakdown["read_file"] == {
        "tool": "read_file",
        "calls": 1,
        "skill": "main-skill",
        "subagent": "main",
    }
    assert tool_breakdown["write_file"] == {
        "tool": "write_file",
        "calls": 1,
        "skill": "sub-skill",
        "subagent": "Test Subagent",
    }


def test_provider_usage_preserves_subagent_evidence(write_cli_session, tmp_path, pricing):
    session_dir = write_cli_session(tmp_path, SID, events=_subagent_events(), workspace={})
    result = copilot_cli.analyze_cli_session(session_dir, pricing)

    subagents = result["provider_usage"]["subagents"]
    assert len(subagents) == 1
    row = subagents[0]
    assert row["agent_id"] == "22222222-2222-2222-2222-222222222222"
    assert row["name"] == "Test Subagent"
    assert row["model"] == "gpt-5.6-luna"
    assert row["total_tool_calls"] == 1
    assert row["total_tokens_reported"] == 1234
    assert row["duration_seconds"] == 3


def test_tool_breakdown_uses_raw_agent_id_when_subagent_started_unseen(
    write_cli_session, tmp_path, pricing
):
    """Tool calls under an unmapped agentId are attributed to the raw id, not merged into main."""
    agent_id = "33333333-3333-3333-3333-333333333333"
    events = [
        {
            "type": "session.start",
            "data": {"sessionId": SID, "version": 1, "startTime": "2026-01-01T00:00:00.000Z"},
            "id": "e1",
            "timestamp": "2026-01-01T00:00:00.000Z",
            "parentId": None,
        },
        {
            "type": "tool.execution_start",
            "data": {"toolCallId": "call-x", "toolName": "orphan_tool"},
            "agentId": agent_id,
            "id": "e2",
            "timestamp": "2026-01-01T00:00:01.000Z",
            "parentId": "e1",
        },
        {
            "type": "tool.execution_complete",
            "data": {"toolCallId": "call-x", "success": True},
            "agentId": agent_id,
            "id": "e3",
            "timestamp": "2026-01-01T00:00:02.000Z",
            "parentId": "e2",
        },
    ]
    session_dir = write_cli_session(tmp_path, SID, events=events, workspace={})
    result = copilot_cli.analyze_cli_session(session_dir, pricing)
    row = result["skills"]["tool_breakdown"][0]
    assert row["subagent"] == agent_id


# ─── evidence-backed creation time (no mtime fallback) ───────────────────────


def test_session_metadata_created_ms_from_first_event_not_mtime(write_cli_session, tmp_path):
    import os
    import time

    session_dir = write_cli_session(tmp_path, SID, workspace={})
    events_path = session_dir / "events.jsonl"
    # Set the file's mtime far in the future so a correct implementation
    # cannot be silently passing by coincidence.
    future = time.time() + 100_000
    os.utime(events_path, (future, future))

    meta = copilot_cli._session_metadata(session_dir)
    expected_ms = core.parse_since_to_ms("2026-01-01T00:00:00.000Z")
    assert meta["created_ms"] == expected_ms
    assert meta["created_ms"] != int(future * 1000)


def test_session_metadata_created_ms_none_when_no_evidence(tmp_path):
    session_dir = tmp_path / SID
    session_dir.mkdir()
    (session_dir / "events.jsonl").write_text("", encoding="utf-8")
    meta = copilot_cli._session_metadata(session_dir)
    assert meta["created_ms"] is None
