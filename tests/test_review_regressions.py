"""Regression tests for the independent-review findings (synthetic fixtures only)."""

from __future__ import annotations

import json

import pytest
from click.testing import CliRunner

from copilot_session_usage import api
from copilot_session_usage._internal import copilot_cli, core
from copilot_session_usage.cli import cli

SID = "22222222-2222-2222-2222-222222222222"
OLD_WORKSPACE = {
    "id": SID,
    "cwd": "/proj",
    "name": "Old Session",
    "created_at": "2025-01-01T00:00:00.000Z",
    "updated_at": "2026-01-01T00:00:10.000Z",
}


@pytest.fixture
def pricing():
    return core.load_pricing(auto_refresh=False)


def _usage(ts: str, uid: str, *, model: str = "gpt-6-luna", inp: int = 1000, out: int = 100):
    return {
        "type": "session.usage_record",
        "data": {
            "usage": {
                "model": model,
                "inputTokens": inp,
                "cacheReadTokens": 0,
                "cacheWriteTokens": 0,
                "outputTokens": out,
                "initiator": "user",
                "cost": 0,
                "copilotUsage": {"totalNanoAiu": 100_000_000},
                "accounting": {"usageId": uid},
            }
        },
        "id": uid,
        "timestamp": ts,
    }


def _start(session_id: str = SID, ts: str = "2025-01-01T00:00:00.000Z"):
    return {
        "type": "session.start",
        "data": {"sessionId": session_id, "version": 1, "startTime": ts},
        "id": "e1",
        "timestamp": ts,
        "parentId": None,
    }


def _vscode_dir(tmp_path, name="vs-sess", ts_ms=1_000_000):
    session_dir = tmp_path / name
    session_dir.mkdir()
    event = {
        "ts": ts_ms,
        "type": "llm_request",
        "attrs": {
            "model": "claude-sonnet-4.6",
            "inputTokens": 1_000_000,
            "outputTokens": 100_000,
            "cachedTokens": 0,
        },
    }
    (session_dir / "main.jsonl").write_text(json.dumps(event) + "\n", encoding="utf-8")
    return session_dir


# ── 1. aggregate from compact output ─────────────────────────────────────────


def test_aggregate_compact_analysis_keeps_usd(tmp_path):
    session_dir = _vscode_dir(tmp_path)
    compact = api.analyze_session(session_dir)
    assert "model_breakdown" not in compact
    assert compact["total"]["estimated_usd"] > 0
    aggregate = api.aggregate_sessions([compact])
    assert aggregate["estimated_usd"] == pytest.approx(compact["total"]["estimated_usd"])
    assert aggregate["llm_calls"] == 1


# ── 2. utility models excluded on CLI ────────────────────────────────────────


def test_cli_utility_records_and_compactions_excluded(write_cli_session, tmp_path, pricing):
    events = [
        _start(),
        _usage("2026-01-01T00:01:00.000Z", "u1"),
        _usage("2026-01-01T00:02:00.000Z", "u2", model="gpt-4.1-mini", inp=9000),
        {
            "type": "session.compaction_complete",
            "data": {
                "behaviorModelId": "gpt-5.4-nano",
                "compactionTokensUsed": {"inputTokens": 500, "outputTokens": 50},
            },
            "id": "c1",
            "timestamp": "2026-01-01T00:03:00.000Z",
        },
    ]
    session_dir = write_cli_session(tmp_path, SID, events=events, workspace={})
    result = copilot_cli.analyze_cli_session(session_dir, pricing)
    assert result["total"]["llm_calls"] == 1
    assert result["total"]["input_tokens"] == 1000
    calls = api.list_calls(session_dir, agent="cli")
    assert [c["model"] for c in calls] == ["gpt-6-luna"]


# ── 3. list uses activity, not creation time ─────────────────────────────────


@pytest.fixture
def old_cli_root(write_cli_session, tmp_path, mocker):
    root = tmp_path / "cli-root"
    root.mkdir()
    events = [_start(), _usage("2026-01-01T00:01:00.000Z", "u1")]
    write_cli_session(root, SID, events=events, workspace=dict(OLD_WORKSPACE))
    mocker.patch(
        "copilot_session_usage._internal.copilot_cli.default_session_state_roots",
        return_value=[root],
    )
    return root


def _cli_json(args):
    result = CliRunner().invoke(cli, ["--agent", "cli", *args, "--format", "json"])
    assert result.exit_code == 0, result.output
    return json.loads(result.output)


def test_list_includes_old_session_with_in_window_calls(old_cli_root):
    listed = _cli_json(["list", "--since", "2025-12-31T00:00:00Z"])
    assert [s["session_id"] for s in listed] == [SID]
    assert [s["session_id"] for s in _cli_json(["list", "--dir", str(old_cli_root)])] == [SID]
    assert len(_cli_json(["list", "--costs", "--since", "2025-12-31T00:00:00Z"])) == 1
    assert [
        s["session_id"] for s in api.list_sessions(agent="cli", since="2025-12-31T00:00:00Z")
    ] == [SID]


def test_list_excludes_touched_session_without_in_window_call(old_cli_root):
    # mtime is "now" (inside the window) but the only call predates it.
    assert _cli_json(["list", "--since", "2026-02-01T00:00:00Z"]) == []
    assert api.list_sessions(agent="cli", since="2026-02-01T00:00:00Z") == []


def test_since_until_help_mentions_calls():
    result = CliRunner().invoke(cli, ["list", "--help"])
    assert "sessions created" not in " ".join(result.output.split()).lower()


# ── 4. missing telemetry stays None ──────────────────────────────────────────


def test_empty_vscode_session_is_none_with_diagnostic(tmp_path):
    session_dir = tmp_path / "empty"
    session_dir.mkdir()
    result = core.analyze_session(session_dir, core.load_pricing(auto_refresh=False))
    assert result["total"]["llm_calls"] is None
    assert result["total"]["estimated_usd"] is None
    assert result["diagnostics"]


def test_aggregate_none_totals_not_coerced_to_zero():
    aggregate = core.aggregate_sessions([{"total": core.empty_total()}])
    assert aggregate["estimated_usd"] is None
    assert aggregate["llm_calls"] is None


def test_session_with_calls_outside_window_is_excluded(tmp_path):
    session_dir = _vscode_dir(tmp_path)
    batch = api.batch_analyze(5, workspace_roots=[tmp_path], since="2030-01-01T00:00:00Z")
    assert batch["sessions"] == []
    assert api.analyze_session(session_dir, since="2030-01-01T00:00:00Z")["total"]["llm_calls"] in (
        0,
        None,
    )


# ── 5. events.jsonl file path resolves canonical id ─────────────────────────


def test_list_calls_events_file_uses_session_uuid(write_cli_session, tmp_path):
    session_dir = write_cli_session(
        tmp_path, SID, events=[_start(), _usage("2026-01-01T00:01:00.000Z", "u1")], workspace={}
    )
    from_dir = api.list_calls(session_dir, agent="cli")
    from_file = api.list_calls(session_dir / "events.jsonl", agent="cli")
    assert {c["session_id"] for c in from_dir} == {SID}
    assert {c["session_id"] for c in from_file} == {SID}


def test_list_calls_exported_file_uses_start_event_id(tmp_path):
    exported = tmp_path / "events.jsonl"
    lines = [_start(), _usage("2026-01-01T00:01:00.000Z", "u1")]
    exported.write_text("\n".join(json.dumps(e) for e in lines) + "\n", encoding="utf-8")
    calls = api.list_calls(exported, agent="cli")
    assert {c["session_id"] for c in calls} == {SID}


# ── 6. compaction requestCount nesting ───────────────────────────────────────


def test_compaction_request_count_is_nested(write_cli_session, tmp_path, pricing):
    compaction = {
        "type": "session.compaction_complete",
        "data": {
            "behaviorModelId": "gpt-6-luna",
            "compactionTokensUsed": {
                "inputTokens": 5000,
                "outputTokens": 500,
                "requestCount": 3,
                "copilotUsage": {"totalNanoAiu": 300_000_000},
            },
        },
        "id": "c1",
        "timestamp": "2026-01-01T00:02:00.000Z",
    }
    events = [_start(), _usage("2026-01-01T00:01:00.000Z", "u1"), compaction]
    session_dir = write_cli_session(tmp_path, SID, events=events, workspace={})
    result = copilot_cli.analyze_cli_session(session_dir, pricing)
    assert result["total"]["compaction"]["calls"] == 3
    assert result["total"]["llm_calls"] == 4


# ── 7. shaping flags keep schema_version and reconciliation ─────────────────


def test_shaped_outputs_include_schema_version_and_reconciliation(tmp_path):
    session_dir = _vscode_dir(tmp_path)
    full = core.analyze_session(session_dir, core.load_pricing(auto_refresh=False))
    for shaped in (
        core.compute_efficiency_summary(full),
        core.shape_session_skill_breakdown(full),
        core.shape_session_tool_breakdown(full),
    ):
        assert shaped["schema_version"] == core.SCHEMA_VERSION
        assert "reconciliation" in shaped
    full["skills"] = {
        "breakdown": [
            {
                "skill": "/a",
                "input_tokens": 1,
                "output_tokens": 1,
                "cached_tokens": 0,
                "llm_calls": 1,
                "estimated_usd": 0.1,
            }
        ]
    }
    minimal = core.shape_session_minimal_skill(full, "/a")
    assert minimal is not None
    assert minimal["schema_version"] == core.SCHEMA_VERSION
    assert "reconciliation" in minimal


# ── Second review ────────────────────────────────────────────────────────────

_PRICING = {
    "models": {
        "default": [
            {"input_per_m": 0.3, "output_per_m": 1.5, "cache_per_m": 0.03, "tier": "Default"}
        ]
    }
}


def test_renderers_survive_none_totals():
    empty = core.aggregate_sessions([{"total": core.empty_total()}])
    assert "n/a" in core.render_aggregate(empty)
    assert "n/a" in core._render_summary_footer(empty)
    none_row = {
        "skill": "/a",
        "sessions": 1,
        **dict.fromkeys(
            ("input_tokens", "cached_tokens", "output_tokens", "llm_calls", "estimated_usd")
        ),
    }
    assert "n/a" in core.render_skill_breakdown({"skill_breakdown": [none_row]})
    assert "n/a" in core.render_skills_aggregate({"skills": [none_row], "session_count": 1})
    assert core.render_aggregate(core.aggregate_sessions([]))
    split = {
        "model_split": [
            {
                "model": "m",
                "input_tokens": None,
                "cached_tokens": None,
                "output_tokens": None,
                "estimated_usd": None,
            }
        ]
    }
    assert "n/a" in core.render_aggregate(split)


def test_start_only_cli_session_table_commands(write_cli_session, tmp_path, mocker):
    root = tmp_path / "root"
    root.mkdir()
    write_cli_session(root, SID, events=[_start()], workspace={})
    mocker.patch(
        "copilot_session_usage._internal.copilot_cli.default_session_state_roots",
        return_value=[root],
    )
    runner = CliRunner()
    for args in (
        ["analyze", "--name", SID, "--aggregate", "--format", "table"],
        ["batch", "1", "--format", "table"],
    ):
        result = runner.invoke(cli, ["--agent", "cli", *args])
        assert result.exit_code == 0, (args, result.output, result.exception)
        assert "n/a" in result.output


def test_windowed_list_has_no_discovery_cap(mocker):
    newer = [
        {"session_id": f"new-{i}", "debug_log_dir": f"/x/{i}", "created_ms": 10_000 + i}
        for i in range(1500)
    ]
    older = {"session_id": "old", "debug_log_dir": "/x/old", "created_ms": 1}
    seen = {}

    def fake_list(agent, roots, limit, title, workspace_filter, active_since_ms=None):
        seen["limit"] = limit
        return (newer + [older])[:limit]

    mocker.patch("copilot_session_usage.api._list_recent", side_effect=fake_list)
    mocker.patch(
        "copilot_session_usage._internal.core.session_has_calls_in_window",
        side_effect=lambda s, since, until: s["session_id"] == "old",
    )
    result = api.list_sessions(limit=5, since="2000-01-01T00:00:00Z")
    assert [s["session_id"] for s in result] == ["old"]
    assert seen["limit"] > 1501


def test_windowed_list_stops_parsing_at_limit(mocker):
    sessions = [
        {"session_id": f"s{i}", "debug_log_dir": f"/x/{i}", "created_ms": 100 - i}
        for i in range(50)
    ]
    mocker.patch("copilot_session_usage.api._list_recent", return_value=sessions)
    checked = mocker.patch(
        "copilot_session_usage._internal.core.session_has_calls_in_window", return_value=True
    )
    result = api.list_sessions(limit=3, since="2000-01-01T00:00:00Z")
    assert len(result) == 3
    assert checked.call_count == 3


def test_selected_skill_reconciliation_is_scoped_to_skill():
    def call(skill, nano):
        return core.make_call(
            ts_ms=1000,
            model="m",
            input_tokens=1000,
            cached_tokens=0,
            output_tokens=0,
            cache_write_tokens=0,
            nano_aiu=nano,
            skill=skill,
        )

    summary = core.summarize_calls([call("/a", 1_000_000_000), call("/b", 2_000_000_000)], _PRICING)
    data = {
        "skills": {"breakdown": summary["skill_breakdown"]},
        "reconciliation": summary["reconciliation"],
    }
    assert data["reconciliation"]["billed_usd"] == pytest.approx(0.03)
    shaped = core.shape_session_minimal_skill(data, "/a")
    assert shaped["cost_usd"] == pytest.approx(0.01)
    assert shaped["reconciliation"]["billed_usd"] == pytest.approx(0.01)
    assert shaped["reconciliation"]["calls_without_billing"] == 0


def _total_line(text: str) -> str:
    return next(line for line in text.splitlines() if line.startswith("TOTAL"))


def _row(tokens, usd):
    return {
        "session_id": "s",
        "title": "t",
        "models": [],
        "total": {"input_tokens": tokens, "estimated_usd": usd},
    }


def test_table_totals_are_na_when_nothing_measured():
    for render in (core.render_costed_list, core._render_analyzed_rows):
        text = render([_row(None, None)])
        assert _total_line(text).split()[-2:] == ["n/a", "n/a"]


def test_table_totals_sum_only_measured_values():
    for render in (core.render_costed_list, core._render_analyzed_rows):
        text = render([_row(None, None), _row(2000, 1.5)])
        assert _total_line(text).split()[-2:] == ["2,000", "$1.50"]


def test_start_only_cli_costs_and_analyze_totals_na(write_cli_session, tmp_path, mocker):
    root = tmp_path / "root"
    root.mkdir()
    write_cli_session(root, SID, events=[_start()], workspace={})
    mocker.patch(
        "copilot_session_usage._internal.copilot_cli.default_session_state_roots",
        return_value=[root],
    )
    for args in (["list", "--costs"], ["analyze", "--name", SID, "--detail", "compact"]):
        result = CliRunner().invoke(cli, ["--agent", "cli", *args, "--format", "table"])
        assert result.exit_code == 0, result.output
        assert "$0.00" not in result.output
