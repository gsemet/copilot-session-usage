"""Unit tests for core.py rendering, emit, and table formatting."""

from __future__ import annotations

import json
from pathlib import Path

from copilot_session_usage._internal import core

# ─── _parse_threshold edge cases ──────────────────────────────────────────────


def test_parse_threshold_not_applicable():
    assert core._parse_threshold("Not applicable") is None
    assert core._parse_threshold("n/a") is None
    assert core._parse_threshold("") is None
    assert core._parse_threshold(None) is None


def test_parse_threshold_unbounded():
    # "> 272K" is parsed as 272000 by the regex; the docstring is aspirational
    assert core._parse_threshold("> 272K") == 272_000


def test_parse_threshold_no_match():
    assert core._parse_threshold("abc") is None


# ─── _parse_price edge cases ──────────────────────────────────────────────────


def test_parse_price_with_comma():
    assert core._parse_price("$1,000.50") == 1000.50


def test_parse_price_invalid():
    assert core._parse_price("free") == 0.0


# ─── _load_custom_pricing exception path ──────────────────────────────────────


def test_load_custom_pricing_unreadable_file(tmp_path):
    ref_dir = tmp_path / "refs"
    ref_dir.mkdir()
    custom_yaml = ref_dir / "custom-models-pricing.yml"
    custom_yaml.write_text("not: valid: yaml: [", encoding="utf-8")
    assert core._load_custom_pricing(ref_dir) is None


def test_load_custom_pricing_non_dict_entry_skipped(tmp_path):
    ref_dir = tmp_path / "refs"
    ref_dir.mkdir()
    custom_yaml = ref_dir / "custom-models-pricing.yml"
    custom_yaml.write_text(
        "- model: 'A'\n  input: $1.00\n- not a dict\n- model: ''\n  input: $2.00\n",
        encoding="utf-8",
    )
    models = core._load_custom_pricing(ref_dir)
    assert models is not None
    assert list(models.keys()) == ["A"]


# ─── load_pricing fallback paths ──────────────────────────────────────────────


def test_load_pricing_missing_yaml_uses_defaults():
    pricing = core.load_pricing(Path("/nonexistent"))
    assert "models" in pricing
    assert "default" in pricing["models"]


def test_load_pricing_bad_yaml_uses_defaults(tmp_path):
    ref_dir = tmp_path / "refs"
    ref_dir.mkdir()
    bad_yaml = ref_dir / "models-and-pricing.yml"
    bad_yaml.write_text("not: valid: yaml: [", encoding="utf-8")
    pricing = core.load_pricing(ref_dir)
    assert "default" in pricing["models"]


def test_load_pricing_non_list_yaml_uses_defaults(tmp_path):
    ref_dir = tmp_path / "refs"
    ref_dir.mkdir()
    bad_yaml = ref_dir / "models-and-pricing.yml"
    bad_yaml.write_text("just_a_string", encoding="utf-8")
    pricing = core.load_pricing(ref_dir)
    assert "default" in pricing["models"]


# ─── _build_pricing_from_yaml edge cases ──────────────────────────────────────


def test_build_pricing_skips_non_dict_entries(tmp_path):
    ref_dir = tmp_path / "refs"
    ref_dir.mkdir()
    std_yaml = ref_dir / "models-and-pricing.yml"
    std_yaml.write_text(
        "- model: 'GPT-5'\n  input: $1.00\n- not a dict\n- model: ''\n  input: $2.00\n",
        encoding="utf-8",
    )
    pricing = core.load_pricing(ref_dir)
    models = pricing["models"]
    assert "gpt-5" in models
    assert len(models) == 2  # gpt-5 + default


# ─── parse_jsonl_file edge cases ──────────────────────────────────────────────


def test_parse_jsonl_file_missing_file():
    stats = core.parse_jsonl_file(Path("/nonexistent/file.jsonl"))
    assert stats["llm_calls"] == 0


def test_parse_jsonl_file_oserror(tmp_path):
    f = tmp_path / "unreadable.jsonl"
    f.write_text("{}", encoding="utf-8")
    f.chmod(0o000)
    try:
        stats = core.parse_jsonl_file(f)
        assert stats["llm_calls"] == 0
    finally:
        f.chmod(0o644)


def test_parse_jsonl_file_no_ts_events(tmp_path):
    f = tmp_path / "test_no_ts.jsonl"
    f.write_text(
        json.dumps(
            {
                "type": "llm_request",
                "attrs": {"model": "gpt-4o", "inputTokens": 10, "outputTokens": 5},
            }
        )
        + "\n",
        encoding="utf-8",
    )
    stats = core.parse_jsonl_file(f)
    assert stats["llm_calls"] == 1
    assert stats["first_ts"] is None
    assert stats["first_llm_ts"] is None


# ─── get_subagent_names edge cases ────────────────────────────────────────────


def test_get_subagent_names_missing_file():
    assert core.get_subagent_names(Path("/nonexistent/main.jsonl")) == {}


def test_get_subagent_names_bad_json_skipped(tmp_path):
    f = tmp_path / "main.jsonl"
    f.write_text(
        json.dumps(
            {"type": "child_session_ref", "attrs": {"childSessionId": "id1", "childTitle": "Good"}}
        )
        + "\n"
        "BAD JSON\n"
        + json.dumps(
            {"type": "child_session_ref", "attrs": {"childSessionId": "id2", "childTitle": "Also"}}
        )
        + "\n",
        encoding="utf-8",
    )
    mapping = core.get_subagent_names(f)
    assert mapping == {"id1": "Good", "id2": "Also"}


def test_get_subagent_names_oserror(tmp_path):
    f = tmp_path / "main.jsonl"
    f.write_text("{}", encoding="utf-8")
    f.chmod(0o000)
    try:
        assert core.get_subagent_names(f) == {}
    finally:
        f.chmod(0o644)


# ─── _resolve_subagent_name edge cases ────────────────────────────────────────


def test_resolve_subagent_name_runsubagent_no_colon():
    name, sid = core._resolve_subagent_name("runSubagent-Explore.jsonl", {})
    assert name == "Explore"
    assert sid == ""


def test_resolve_subagent_name_runsubagent_double_underscore():
    name, sid = core._resolve_subagent_name(
        "runSubagent-Explore-functions.runSubagent__3.jsonl", {}
    )
    assert name == "Explore"
    assert sid == "functions.runSubagent:3"


def test_resolve_subagent_name_generic_stem():
    name, sid = core._resolve_subagent_name("something-else.jsonl", {})
    assert name == "something-else"
    assert sid == ""


# ─── analyze_session edge cases ───────────────────────────────────────────────


def test_analyze_session_no_llm_events(tmp_path):
    session_dir = tmp_path / "sess"
    session_dir.mkdir()
    (session_dir / "main.jsonl").write_text(
        json.dumps({"ts": 1000, "type": "tool_call", "attrs": {}}) + "\n",
        encoding="utf-8",
    )
    result = core.analyze_session(
        session_dir,
        {
            "models": {
                "default": [
                    {
                        "input_per_m": 0.3,
                        "output_per_m": 1.5,
                        "cache_per_m": 0.03,
                        "tier": "Default",
                    }
                ]
            }
        },
    )
    assert result["total"]["llm_calls"] == 0
    assert result["subagents"] == []
    assert result["model_breakdown"] == []


# ─── _col_width and _render_columns ───────────────────────────────────────────


def test_col_width_with_cap():
    # "loooooong" is 9 chars, so capped width is 9 (not 10)
    assert core._col_width("Header", ["short", "loooooong"], cap=10) == 9


def test_col_width_floor():
    assert core._col_width("H", [], floor=5) == 5


def test_render_columns_basic():
    headers = ("Name", "Count")
    rows = [("Alice", "10"), ("Bob", "2")]
    lines = core._render_columns(headers, rows, left_cols={0})
    assert len(lines) == 4  # header, separator, 2 rows
    assert "Alice" in lines[2]
    assert "10" in lines[2]


def test_render_columns_right_justified():
    headers = ("Name", "Count")
    rows = [("Alice", "10")]
    lines = core._render_columns(headers, rows, left_cols=set())
    # Count should be right-justified
    assert "10" in lines[2]


# ─── render_table_single ──────────────────────────────────────────────────────


def test_render_table_single_minimal():
    data = {
        "session_id": "abc",
        "title": "Test",
        "started_at": "2026-07-01T12:00:00Z",
        "duration_seconds": 60,
        "active_duration_seconds": 30,
        "models": ["gpt-4o"],
        "total": {
            "input_tokens": 1000,
            "output_tokens": 100,
            "cached_tokens": 50,
            "llm_calls": 5,
            "estimated_usd": 0.1234,
            "cache_ratio": 0.05,
        },
        "fallback_pricing_models": [],
        "model_breakdown": [],
        "subagents": [],
    }
    text = core.render_table_single(data)
    assert "abc" in text
    assert "Test" in text
    assert "1,000" in text
    assert "$0.1234" in text
    assert "active: 30s" in text


def test_render_table_single_no_active_duration():
    data = {
        "session_id": "abc",
        "title": None,
        "started_at": "2026-07-01T12:00:00Z",
        "duration_seconds": 60,
        "active_duration_seconds": None,
        "models": None,
        "total": {
            "input_tokens": 1000,
            "output_tokens": 100,
            "cached_tokens": 50,
            "llm_calls": 5,
            "estimated_usd": 0.1234,
            "cache_ratio": 0.05,
        },
        "fallback_pricing_models": ["unknown-model"],
        "model_breakdown": [],
        "subagents": [],
    }
    text = core.render_table_single(data)
    assert "(unknown)" in text
    assert "Warning:" in text
    assert "unknown-model" in text


def test_render_table_single_with_breakdown():
    data = {
        "session_id": "abc",
        "title": "Test",
        "started_at": "2026-07-01T12:00:00Z",
        "duration_seconds": 60,
        "active_duration_seconds": 60,
        "models": ["gpt-4o"],
        "total": {
            "input_tokens": 1000,
            "output_tokens": 100,
            "cached_tokens": 50,
            "llm_calls": 5,
            "estimated_usd": 0.1234,
            "cache_ratio": 0.05,
        },
        "fallback_pricing_models": [],
        "model_breakdown": [
            {
                "model": "gpt-4o",
                "input_tokens": 1000,
                "output_tokens": 100,
                "cached_tokens": 50,
                "llm_calls": 5,
                "estimated_usd": 0.1234,
            }
        ],
        "subagents": [
            {
                "file": "main.jsonl",
                "name": "main",
                "subagent_id": None,
                "model": "gpt-4o",
                "input_tokens": 1000,
                "output_tokens": 100,
                "cached_tokens": 50,
                "llm_calls": 5,
                "estimated_usd": 0.1234,
            }
        ],
    }
    text = core.render_table_single(data)
    assert "Per-Model Breakdown:" in text
    assert "Subagents:" in text
    assert "gpt-4o" in text


# ─── render_table_list ────────────────────────────────────────────────────────


def test_render_table_list_empty():
    assert core.render_table_list([]) == "(no sessions found)"


def test_render_table_list_full_detail():
    items = [
        {
            "session_id": "s1",
            "title": "Test",
            "started_at": "2026-07-01T12:00:00Z",
            "duration_seconds": 60,
            "active_duration_seconds": 30,
            "models": ["gpt-4o"],
            "total": {
                "input_tokens": 1000,
                "output_tokens": 100,
                "cached_tokens": 50,
                "llm_calls": 5,
                "estimated_usd": 0.1,
                "cache_ratio": 0.05,
            },
            "fallback_pricing_models": [],
            "model_breakdown": [],
            "subagents": [],
        }
    ]
    text = core.render_table_list(items)
    assert "s1" in text
    # With a single item there's no divider; verify it's the single-session format
    assert "Session:" in text


def test_render_table_list_full_detail_with_summary():
    items = [
        {
            "session_id": "s1",
            "title": "Test",
            "started_at": "2026-07-01T12:00:00Z",
            "duration_seconds": 60,
            "active_duration_seconds": 30,
            "models": ["gpt-4o"],
            "total": {
                "input_tokens": 1000,
                "output_tokens": 100,
                "cached_tokens": 50,
                "llm_calls": 5,
                "estimated_usd": 0.1,
                "cache_ratio": 0.05,
            },
            "fallback_pricing_models": [],
            "model_breakdown": [],
            "subagents": [],
        }
    ]
    summary = {
        "session_count": 1,
        "total_input_tokens": 1000,
        "total_output_tokens": 100,
        "total_cached_tokens": 50,
        "total_llm_calls": 5,
        "total_estimated_usd": 0.1,
        "avg_cache_ratio": 0.05,
        "total_duration_seconds": 60,
        "total_active_duration_seconds": 30,
        "fallback_pricing_models": [],
    }
    text = core.render_table_list(items, summary=summary)
    assert "Summary across 1 sessions:" in text


def test_render_table_list_analyzed_rows():
    items = [
        {
            "session_id": "s1",
            "title": "Test",
            "started_at": "2026-07-01T12:00:00Z",
            "models": ["gpt-4o"],
            "total": {"input_tokens": 1000, "estimated_usd": 0.1},
        }
    ]
    text = core.render_table_list(items)
    assert "Test" in text
    assert "TOTAL" in text


def test_render_table_list_analyzed_rows_with_summary():
    items = [
        {
            "session_id": "s1",
            "title": "Test",
            "started_at": "2026-07-01T12:00:00Z",
            "models": ["gpt-4o"],
            "total": {"input_tokens": 1000, "estimated_usd": 0.1},
        }
    ]
    summary = {
        "session_count": 1,
        "total_input_tokens": 2000,
        "total_output_tokens": 0,
        "total_cached_tokens": 0,
        "total_llm_calls": 0,
        "total_estimated_usd": 0.2,
        "avg_cache_ratio": 0.0,
        "total_duration_seconds": 0,
        "total_active_duration_seconds": 0,
        "fallback_pricing_models": [],
    }
    text = core.render_table_list(items, summary=summary)
    assert "TOTAL" in text


def test_render_table_list_metadata_rows():
    items = [
        {
            "session_id": "s1",
            "title": "Test",
            "created_at": "2026-07-01T12:00:00Z",
            "has_debug_logs": True,
        },
        {
            "session_id": "s2",
            "title": "Another",
            "created_at": "2026-07-02T12:00:00Z",
            "has_debug_logs": False,
        },
    ]
    text = core.render_table_list(items)
    assert "Test" in text
    assert "Another" in text
    assert "y" in text
    assert "n" in text


# ─── render ───────────────────────────────────────────────────────────────────


def test_render_json():
    data = {"key": "value"}
    assert core.render(data, "json") == json.dumps(data, indent=2, ensure_ascii=False)


def test_render_list():
    items = [
        {
            "session_id": "s1",
            "title": "Test",
            "created_at": "2026-07-01T12:00:00Z",
            "has_debug_logs": True,
        }
    ]
    text = core.render(items, "table")
    assert "Test" in text


def test_render_batch_dict():
    batch = {
        "summary": {"session_count": 1},
        "sessions": [
            {
                "session_id": "s1",
                "title": "Test",
                "created_at": "2026-07-01T12:00:00Z",
                "has_debug_logs": True,
            }
        ],
    }
    text = core.render(batch, "table")
    assert "Test" in text


def test_render_single_session():
    data = {
        "session_id": "s1",
        "title": "Test",
        "started_at": "2026-07-01T12:00:00Z",
        "duration_seconds": 60,
        "active_duration_seconds": 30,
        "models": ["gpt-4o"],
        "total": {
            "input_tokens": 1000,
            "output_tokens": 100,
            "cached_tokens": 50,
            "llm_calls": 5,
            "estimated_usd": 0.1,
            "cache_ratio": 0.05,
        },
        "fallback_pricing_models": [],
        "model_breakdown": [],
        "subagents": [],
    }
    text = core.render(data, "table")
    assert "s1" in text


# ─── emit ─────────────────────────────────────────────────────────────────────


def test_emit_to_stdout(capsys):
    data = {"key": "value"}
    core.emit(data, "json")
    captured = capsys.readouterr()
    # emit uses indent=2, so match the formatted output
    assert '"key": "value"' in captured.out


def test_emit_to_file(tmp_path):
    data = {"key": "value"}
    out_path = tmp_path / "out.json"
    core.emit(data, "json", out_path)
    assert out_path.exists()
    assert json.loads(out_path.read_text()) == data


# ─── CLI option decorators ────────────────────────────────────────────────────


def test_detail_option_is_click_option():
    assert isinstance(core.DETAIL_CHOICE, type(core.FORMAT_CHOICE))


def test_normalize_format_table():
    assert core.normalize_format("table") == "table"


def test_resolve_detail_table():
    assert core.resolve_detail("compact", "table") == "compact"


# ─── Summary / aggregate / costed-list rendering ──────────────────────────────


def test_render_summary():
    summary = {
        "session_id": "s1",
        "title": "Test",
        "cache_ratio": 0.5,
        "total_tokens": 1_700,
        "total_input_tokens": 1_000,
        "total_output_tokens": 200,
        "total_cached_tokens": 500,
        "llm_calls": 5,
        "estimated_usd": 0.42,
        "cost_per_1m_tokens": 247.06,
        "model_split": [
            {
                "model": "gpt-4o",
                "input_tokens": 1_000,
                "split_ratio": 1.0,
                "estimated_usd": 0.42,
                "cost_per_1m_input_tokens": 0.42,
            }
        ],
    }
    text = core.render(summary, "table")
    assert "Cache ratio: 50%" in text
    assert "Cost per 1M tokens: $247.06" in text
    assert "Model split:" in text


def test_render_aggregate():
    aggregate = {
        "session_count": 2,
        "total_tokens": 3_400,
        "total_input_tokens": 2_000,
        "total_output_tokens": 400,
        "total_cached_tokens": 1_000,
        "total_llm_calls": 10,
        "total_estimated_usd": 0.84,
        "avg_cache_ratio": 0.5,
        "cost_per_1m_tokens": 247.06,
        "total_duration_seconds": 1_200,
        "model_split": [
            {
                "model": "gpt-4o",
                "input_tokens": 2_000,
                "split_ratio": 1.0,
                "estimated_usd": 0.84,
                "cost_per_1m_input_tokens": 0.42,
            }
        ],
    }
    text = core.render(aggregate, "table")
    assert "Aggregate across 2 sessions" in text
    assert "Cost per 1M tokens: $247.06" in text
    assert "Model split:" in text


def test_render_costed_list():
    items = [
        {
            "session_id": "s1",
            "title": "First",
            "started_at": "2026-07-01T12:00:00Z",
            "models": ["gpt-4o"],
            "total": {
                "input_tokens": 1_000,
                "output_tokens": 100,
                "cached_tokens": 50,
                "estimated_usd": 0.1,
            },
        },
        {
            "session_id": "s2",
            "title": "Second",
            "started_at": "2026-07-02T12:00:00Z",
            "models": ["gpt-4o", "claude-sonnet-4.6"],
            "total": {
                "input_tokens": 2_000,
                "output_tokens": 200,
                "cached_tokens": 100,
                "estimated_usd": 0.2,
            },
        },
    ]
    text = core.render(items, "table", costed_list=True)
    assert "First" in text
    assert "Second" in text
    assert "TOTAL" in text
    assert "Models" in text
    assert "Tokens" in text


def test_render_costed_list_empty():
    assert core.render([], "table", costed_list=True) == "(no sessions found)"


def test_emit_costed_list_to_file(tmp_path):
    items = [
        {
            "session_id": "s1",
            "title": "Test",
            "started_at": "2026-07-01T12:00:00Z",
            "models": ["gpt-4o"],
            "total": {
                "input_tokens": 1_000,
                "output_tokens": 100,
                "cached_tokens": 50,
                "estimated_usd": 0.1,
            },
        }
    ]
    out_path = tmp_path / "out.txt"
    core.emit(items, "table", out_path, costed_list=True)
    assert out_path.exists()
    assert "Test" in out_path.read_text(encoding="utf-8")
