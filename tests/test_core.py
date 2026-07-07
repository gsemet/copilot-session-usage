"""Unit tests for core.py — pricing, JSONL parsing, shaping, rendering."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from copilot_session_usage._internal import core

# ─── Pricing helpers ──────────────────────────────────────────────────────────

PRICING = {
    "models": {
        "claude-sonnet-4.6": [
            {"input_per_m": 0.30, "output_per_m": 1.50, "cache_per_m": 0.030, "tier": "Default"}
        ],
        "gpt-4o": [
            {"input_per_m": 0.25, "output_per_m": 1.00, "cache_per_m": 0.025, "tier": "Default"}
        ],
        "claude-haiku": [
            {"input_per_m": 0.08, "output_per_m": 0.40, "cache_per_m": 0.008, "tier": "Default"}
        ],
        "default": [
            {"input_per_m": 0.30, "output_per_m": 1.50, "cache_per_m": 0.030, "tier": "Default"}
        ],
    }
}


def test_estimate_cost_no_cache():
    cost = core.estimate_cost(1_000_000, 0, 0, "claude-sonnet-4.6", PRICING)
    assert abs(cost - 0.30) < 1e-9


def test_estimate_cost_with_cache():
    cost = core.estimate_cost(1_000_000, 0, 500_000, "claude-sonnet-4.6", PRICING)
    expected = 500_000 * 0.30 / 1e6 + 500_000 * 0.030 / 1e6
    assert abs(cost - expected) < 1e-9


def test_estimate_cost_output_only():
    cost = core.estimate_cost(0, 1_000_000, 0, "gpt-4o", PRICING)
    assert abs(cost - 1.00) < 1e-9


def test_get_model_rates_exact_match():
    rates = core._get_model_rates("gpt-4o", 0, PRICING)
    assert rates["input_per_m"] == 0.25


def test_get_model_rates_prefix_match():
    rates = core._get_model_rates("claude-haiku-4.6", 0, PRICING)
    assert rates["input_per_m"] == 0.08


def test_get_model_rates_fallback():
    rates = core._get_model_rates("unknown-model-xyz", 0, PRICING)
    assert rates["input_per_m"] == 0.30  # default


# ─── Model name normalization ─────────────────────────────────────────────────


def test_normalize_model_name_basic():
    assert core._normalize_model_name("GPT-5.4") == "gpt-5.4"


def test_normalize_model_name_footnote_stripped():
    assert core._normalize_model_name("Claude Sonnet 5[^sonnet-5-promo]") == "claude-sonnet-5"


def test_normalize_model_name_preview_stripped():
    assert core._normalize_model_name("Claude Opus 4.8 (preview)") == "claude-opus-4.8"


def test_normalize_model_name_fast_mode_preserved():
    """Fast mode is a functional variant and must stay distinct."""
    assert (
        core._normalize_model_name("Claude Opus 4.8 (fast mode) (preview)")
        == "claude-opus-4.8-(fast-mode)"
    )


# ─── Threshold-aware pricing ──────────────────────────────────────────────────


def test_threshold_aware_pricing_low_tier():
    pricing = {
        "models": {
            "gpt-5.4": [
                {
                    "input_per_m": 2.50,
                    "output_per_m": 15.00,
                    "cache_per_m": 0.25,
                    "tier": "Default",
                    "threshold_tokens": 272_000,
                },
                {
                    "input_per_m": 5.00,
                    "output_per_m": 22.50,
                    "cache_per_m": 0.50,
                    "tier": "Long context",
                    "threshold_tokens": None,
                },
            ]
        }
    }
    rates = core._get_model_rates("gpt-5.4", 100_000, pricing)
    assert rates["input_per_m"] == 2.50
    assert rates["tier"] == "Default"


def test_threshold_aware_pricing_high_tier():
    pricing = {
        "models": {
            "gpt-5.4": [
                {
                    "input_per_m": 2.50,
                    "output_per_m": 15.00,
                    "cache_per_m": 0.25,
                    "tier": "Default",
                    "threshold_tokens": 272_000,
                },
                {
                    "input_per_m": 5.00,
                    "output_per_m": 22.50,
                    "cache_per_m": 0.50,
                    "tier": "Long context",
                    "threshold_tokens": None,
                },
            ]
        }
    }
    rates = core._get_model_rates("gpt-5.4", 300_000, pricing)
    assert rates["input_per_m"] == 5.00
    assert rates["tier"] == "Long context"


def test_threshold_aware_pricing_exact_boundary():
    pricing = {
        "models": {
            "gpt-5.4": [
                {
                    "input_per_m": 2.50,
                    "output_per_m": 15.00,
                    "cache_per_m": 0.25,
                    "tier": "Default",
                    "threshold_tokens": 272_000,
                },
                {
                    "input_per_m": 5.00,
                    "output_per_m": 22.50,
                    "cache_per_m": 0.50,
                    "tier": "Long context",
                    "threshold_tokens": None,
                },
            ]
        }
    }
    rates = core._get_model_rates("gpt-5.4", 272_000, pricing)
    assert rates["input_per_m"] == 2.50


def test_estimate_cost_with_threshold():
    pricing = {
        "models": {
            "gpt-5.4": [
                {
                    "input_per_m": 2.50,
                    "output_per_m": 15.00,
                    "cache_per_m": 0.25,
                    "tier": "Default",
                    "threshold_tokens": 272_000,
                },
                {
                    "input_per_m": 5.00,
                    "output_per_m": 22.50,
                    "cache_per_m": 0.50,
                    "tier": "Long context",
                    "threshold_tokens": None,
                },
            ]
        }
    }
    low_cost = core.estimate_cost(100_000, 10_000, 0, "gpt-5.4", pricing)
    high_cost = core.estimate_cost(300_000, 10_000, 0, "gpt-5.4", pricing)
    assert high_cost > low_cost * 1.5


# ─── Fallback pricing detection ───────────────────────────────────────────────


def test_model_uses_fallback_pricing_exact_match():
    assert core.model_uses_fallback_pricing("gpt-4o", PRICING) is False


def test_model_uses_fallback_pricing_prefix_match():
    assert core.model_uses_fallback_pricing("claude-haiku-4.6", PRICING) is False


def test_model_uses_fallback_pricing_unknown_model():
    assert core.model_uses_fallback_pricing("some-brand-new-model", PRICING) is True


# ─── Custom model pricing ─────────────────────────────────────────────────────


def test_load_custom_pricing_reads_yaml(tmp_path):
    ref_dir = tmp_path / "references"
    ref_dir.mkdir()
    custom_yaml = ref_dir / "custom-models-pricing.yml"
    custom_yaml.write_text(
        "- model: 'Kimi-K2.6-azure'\n"
        "  provider: custom\n"
        "  input: $0.15\n"
        "  cached_input: $0.015\n"
        "  output: $0.60\n",
        encoding="utf-8",
    )
    models = core._load_custom_pricing(ref_dir)
    assert models is not None
    assert "Kimi-K2.6-azure" in models
    tier = models["Kimi-K2.6-azure"][0]
    assert tier["input_per_m"] == 0.15
    assert tier["output_per_m"] == 0.60
    assert tier["cache_per_m"] == 0.015


def test_load_custom_pricing_missing_file_returns_none(tmp_path):
    ref_dir = tmp_path / "references"
    ref_dir.mkdir()
    assert core._load_custom_pricing(ref_dir) is None


def test_load_custom_pricing_empty_list_returns_none(tmp_path):
    ref_dir = tmp_path / "references"
    ref_dir.mkdir()
    custom_yaml = ref_dir / "custom-models-pricing.yml"
    custom_yaml.write_text("[]\n", encoding="utf-8")
    assert core._load_custom_pricing(ref_dir) is None


def test_load_pricing_merges_custom_models(tmp_path):
    ref_dir = tmp_path / "references"
    ref_dir.mkdir()
    std_yaml = ref_dir / "models-and-pricing.yml"
    std_yaml.write_text(
        "- model: 'GPT-5 mini'\n"
        "  provider: openai\n"
        "  input: $0.25\n"
        "  cached_input: $0.025\n"
        "  output: $2.00\n",
        encoding="utf-8",
    )
    custom_yaml = ref_dir / "custom-models-pricing.yml"
    custom_yaml.write_text(
        "- model: 'Kimi-K2.6-azure'\n"
        "  provider: custom\n"
        "  input: $0.00\n"
        "  cached_input: $0.00\n"
        "  output: $0.00\n",
        encoding="utf-8",
    )
    pricing = core.load_pricing(ref_dir)
    models = pricing.get("models", {})
    assert "gpt-5-mini" in models
    assert "Kimi-K2.6-azure" in models
    assert models["Kimi-K2.6-azure"][0]["input_per_m"] == 0.0


def test_custom_model_not_flagged_as_fallback():
    pricing = {
        "models": {
            "claude-sonnet-4.6": [
                {"input_per_m": 0.30, "output_per_m": 1.50, "cache_per_m": 0.030, "tier": "Default"}
            ],
            "Kimi-K2.6-azure": [
                {"input_per_m": 0.00, "output_per_m": 0.00, "cache_per_m": 0.00, "tier": "Default"}
            ],
            "default": [
                {"input_per_m": 0.30, "output_per_m": 1.50, "cache_per_m": 0.030, "tier": "Default"}
            ],
        }
    }
    assert core.model_uses_fallback_pricing("Kimi-K2.6-azure", pricing) is False


# ─── Per-model cost helpers ───────────────────────────────────────────────────


def test_estimate_cost_for_file_single_model():
    per_model = {
        "claude-sonnet-4.6": {"input": 1_000_000, "output": 0, "cached": 0},
    }
    cost = core.estimate_cost_for_file(per_model, PRICING)
    assert abs(cost - 0.30) < 1e-9


def test_estimate_cost_for_file_multi_model():
    per_model = {
        "claude-sonnet-4.6": {"input": 1_887_586, "output": 47_184, "cached": 1_386_477},
        "Kimi-K2.6-azure": {"input": 6_168, "output": 1_862, "cached": 0},
    }
    pricing = {
        "models": {
            "claude-sonnet-4.6": [
                {"input_per_m": 0.30, "output_per_m": 1.50, "cache_per_m": 0.030, "tier": "Default"}
            ],
            "Kimi-K2.6-azure": [
                {"input_per_m": 0.15, "output_per_m": 0.60, "cache_per_m": 0.015, "tier": "Default"}
            ],
            "default": [
                {"input_per_m": 0.30, "output_per_m": 1.50, "cache_per_m": 0.030, "tier": "Default"}
            ],
        }
    }
    cost = core.estimate_cost_for_file(per_model, pricing)
    wrong_cost = core.estimate_cost(
        1_887_586 + 6_168, 47_184 + 1_862, 1_386_477, "Kimi-K2.6-azure", pricing
    )
    assert cost > wrong_cost * 1.5, "Per-model pricing must be >1.5x the wrong single-model price"
    assert abs(cost - 0.265) < 0.005


def test_dominant_model_by_input_tokens():
    per_model = {
        "claude-sonnet-4.6": {"input": 1_000_000, "output": 0, "cached": 0, "calls": 22},
        "Kimi-K2.6-azure": {"input": 6_000, "output": 0, "cached": 0, "calls": 1},
    }
    assert core._dominant_model(per_model) == "claude-sonnet-4.6"


def test_dominant_model_empty():
    assert core._dominant_model({}) == "unknown"


# ─── JSONL parsing ────────────────────────────────────────────────────────────


def _make_llm_event(model: str, inp: int, out: int, cached: int = 0, ts: int = 1000) -> str:
    return json.dumps(
        {
            "ts": ts,
            "type": "llm_request",
            "attrs": {
                "model": model,
                "inputTokens": inp,
                "outputTokens": out,
                "cachedTokens": cached,
            },
        }
    )


def _make_non_llm_event(ts: int = 500) -> str:
    return json.dumps({"ts": ts, "type": "tool_call", "attrs": {}})


def test_parse_jsonl_file_single_model(tmp_path):
    f = tmp_path / "main.jsonl"
    f.write_text(
        _make_llm_event("claude-sonnet-4.6", 100, 50, 20, ts=1000)
        + "\n"
        + _make_llm_event("claude-sonnet-4.6", 200, 30, 0, ts=2000)
        + "\n",
        encoding="utf-8",
    )
    stats = core.parse_jsonl_file(f)
    assert stats["llm_calls"] == 2
    assert stats["input_tokens"] == 300
    assert stats["output_tokens"] == 80
    assert stats["cached_tokens"] == 20
    assert stats["models"] == ["claude-sonnet-4.6"]
    assert stats["per_model"]["claude-sonnet-4.6"]["calls"] == 2
    assert stats["first_llm_ts"] == 1000
    assert stats["last_llm_ts"] == 2000


def test_parse_jsonl_file_multi_model(tmp_path):
    f = tmp_path / "main.jsonl"
    f.write_text(
        _make_llm_event("claude-sonnet-4.6", 1000, 50, ts=1000)
        + "\n"
        + _make_llm_event("claude-sonnet-4.6", 800, 30, ts=2000)
        + "\n"
        + _make_llm_event("Kimi-K2.6-azure", 50, 5, ts=3000)
        + "\n",
        encoding="utf-8",
    )
    stats = core.parse_jsonl_file(f)
    assert stats["llm_calls"] == 3
    assert stats["input_tokens"] == 1850
    assert set(stats["models"]) == {"claude-sonnet-4.6", "Kimi-K2.6-azure"}
    assert stats["per_model"]["claude-sonnet-4.6"]["input"] == 1800
    assert stats["per_model"]["Kimi-K2.6-azure"]["input"] == 50
    assert stats["first_llm_ts"] == 1000
    assert stats["last_llm_ts"] == 3000


def test_parse_jsonl_file_skips_non_llm_events(tmp_path):
    f = tmp_path / "main.jsonl"
    f.write_text(
        _make_non_llm_event(ts=500) + "\n" + _make_llm_event("gpt-4o", 100, 20, ts=1000) + "\n",
        encoding="utf-8",
    )
    stats = core.parse_jsonl_file(f)
    assert stats["llm_calls"] == 1
    assert stats["first_ts"] == 500
    assert stats["first_llm_ts"] == 1000


def test_parse_jsonl_file_empty(tmp_path):
    f = tmp_path / "empty.jsonl"
    f.write_text("", encoding="utf-8")
    stats = core.parse_jsonl_file(f)
    assert stats["llm_calls"] == 0
    assert stats["per_model"] == {}


def test_parse_jsonl_file_bad_json_lines_skipped(tmp_path):
    f = tmp_path / "main.jsonl"
    f.write_text(
        "NOT JSON\n" + _make_llm_event("gpt-4o", 50, 10, ts=1000) + "\n" + "{broken\n",
        encoding="utf-8",
    )
    stats = core.parse_jsonl_file(f)
    assert stats["llm_calls"] == 1


# ─── Subagent name resolution ─────────────────────────────────────────────────


def test_resolve_subagent_name_main():
    name, sid = core._resolve_subagent_name("main.jsonl", {})
    assert name == "main"
    assert sid == ""


def test_resolve_subagent_name_title_generation():
    name, sid = core._resolve_subagent_name("title-0b41b9df-e28e-4312.jsonl", {})
    assert name == "title-generation"
    assert sid == ""


def test_resolve_subagent_name_runsubagent_with_mapping():
    mapping = {"functions.runSubagent:16": "Skill Eval Grader"}
    name, sid = core._resolve_subagent_name(
        "runSubagent-default-functions.runSubagent:16.jsonl", mapping
    )
    assert name == "Skill Eval Grader"
    assert sid == "functions.runSubagent:16"


def test_resolve_subagent_name_runsubagent_fallback():
    name, sid = core._resolve_subagent_name("runSubagent-Explore-functions.runSubagent:3.jsonl", {})
    assert name == "Explore"
    assert sid == "functions.runSubagent:3"


def test_resolve_subagent_name_runsubagent_hyphen_separator():
    """Windows may write ``-`` instead of ``:`` in the filename."""
    name, sid = core._resolve_subagent_name("runSubagent-Explore-functions.runSubagent-3.jsonl", {})
    assert name == "Explore"
    assert sid == "functions.runSubagent:3"


# ─── Session analysis (integration over tmp files) ────────────────────────────


def _write_session(tmp_path: Path, files: dict[str, list[str]]) -> Path:
    session_dir = tmp_path / "abc123"
    session_dir.mkdir()
    for filename, lines in files.items():
        (session_dir / filename).write_text("\n".join(lines) + "\n", encoding="utf-8")
    return session_dir


def test_analyze_session_single_model(tmp_path):
    session_dir = _write_session(
        tmp_path,
        {
            "main.jsonl": [
                _make_llm_event("claude-sonnet-4.6", 1000, 100, 200, ts=1_000_000),
                _make_llm_event("claude-sonnet-4.6", 500, 50, 0, ts=2_000_000),
            ]
        },
    )
    result = core.analyze_session(session_dir, PRICING)
    assert result["total"]["input_tokens"] == 1500
    assert result["total"]["output_tokens"] == 150
    assert result["total"]["cached_tokens"] == 200
    assert result["total"]["llm_calls"] == 2
    assert result["models"] == ["claude-sonnet-4.6"]
    assert result["fallback_pricing_models"] == []
    assert len(result["model_breakdown"]) == 1
    assert result["model_breakdown"][0]["model"] == "claude-sonnet-4.6"
    assert result["active_duration_seconds"] == 1000


def test_analyze_session_multi_model_correct_cost(tmp_path):
    pricing = {
        "models": {
            "claude-sonnet-4.6": [
                {"input_per_m": 0.30, "output_per_m": 1.50, "cache_per_m": 0.030, "tier": "Default"}
            ],
            "Kimi-K2.6-azure": [
                {"input_per_m": 0.15, "output_per_m": 0.60, "cache_per_m": 0.015, "tier": "Default"}
            ],
            "default": [
                {"input_per_m": 0.30, "output_per_m": 1.50, "cache_per_m": 0.030, "tier": "Default"}
            ],
        }
    }
    session_dir = _write_session(
        tmp_path,
        {
            "main.jsonl": [
                _make_llm_event("claude-sonnet-4.6", 1_887_586, 47_184, 1_386_477, ts=1_000_000),
                _make_llm_event("Kimi-K2.6-azure", 6_168, 1_862, 0, ts=2_000_000),
            ]
        },
    )
    result = core.analyze_session(session_dir, pricing)
    assert result["total"]["estimated_usd"] > 0.20
    assert len(result["model_breakdown"]) == 2
    breakdown_models = {b["model"] for b in result["model_breakdown"]}
    assert "claude-sonnet-4.6" in breakdown_models
    assert "Kimi-K2.6-azure" in breakdown_models
    sonnet = next(b for b in result["model_breakdown"] if b["model"] == "claude-sonnet-4.6")
    kimi = next(b for b in result["model_breakdown"] if b["model"] == "Kimi-K2.6-azure")
    assert sonnet["estimated_usd"] > kimi["estimated_usd"] * 50


def test_analyze_session_models_ordered_by_cost_not_alphabetically(tmp_path):
    pricing = {
        "models": {
            "claude-sonnet-4.6": [
                {"input_per_m": 0.30, "output_per_m": 1.50, "cache_per_m": 0.030, "tier": "Default"}
            ],
            "Kimi-K2.6-azure": [
                {"input_per_m": 0.15, "output_per_m": 0.60, "cache_per_m": 0.015, "tier": "Default"}
            ],
            "default": [
                {"input_per_m": 0.30, "output_per_m": 1.50, "cache_per_m": 0.030, "tier": "Default"}
            ],
        }
    }
    session_dir = _write_session(
        tmp_path,
        {
            "main.jsonl": [
                _make_llm_event("claude-sonnet-4.6", 1_887_586, 47_184, 1_386_477, ts=1_000_000),
                _make_llm_event("Kimi-K2.6-azure", 6_168, 1_862, 0, ts=2_000_000),
            ]
        },
    )
    result = core.analyze_session(session_dir, pricing)
    assert result["models"][0] == "claude-sonnet-4.6"


def test_analyze_session_fallback_pricing_models_flagged(tmp_path):
    session_dir = _write_session(
        tmp_path,
        {"main.jsonl": [_make_llm_event("brand-new-unlisted-model", 1000, 100, ts=1_000_000)]},
    )
    result = core.analyze_session(session_dir, PRICING)
    assert result["fallback_pricing_models"] == ["brand-new-unlisted-model"]


def test_analyze_session_active_duration_vs_session_duration(tmp_path):
    session_dir = _write_session(
        tmp_path,
        {
            "main.jsonl": [
                json.dumps({"ts": 0, "type": "session_start", "attrs": {}}),
                _make_llm_event("claude-sonnet-4.6", 100, 10, ts=3_600_000),
                _make_llm_event("claude-sonnet-4.6", 100, 10, ts=3_610_000),
                json.dumps({"ts": 7_200_000, "type": "session_end", "attrs": {}}),
            ]
        },
    )
    result = core.analyze_session(session_dir, PRICING)
    assert result["duration_seconds"] == 7200
    assert result["active_duration_seconds"] == 10


def test_analyze_session_with_subagent(tmp_path):
    main_events = [
        json.dumps(
            {
                "ts": 1_000_000,
                "type": "child_session_ref",
                "attrs": {"childSessionId": "functions.runSubagent:1", "childTitle": "Explore"},
            }
        ),
        _make_llm_event("claude-sonnet-4.6", 500, 50, ts=1_000_000),
    ]
    subagent_events = [
        _make_llm_event("claude-sonnet-4.6", 300, 30, ts=1_500_000),
    ]
    session_dir = _write_session(
        tmp_path,
        {
            "main.jsonl": main_events,
            # Use ``__`` instead of ``:`` so the test passes on Windows
            # where ``:`` is an illegal filename character.
            "runSubagent-Explore-functions.runSubagent__1.jsonl": subagent_events,
        },
    )
    result = core.analyze_session(session_dir, PRICING)
    assert result["total"]["input_tokens"] == 800
    assert len(result["subagents"]) == 2
    names = {s["name"] for s in result["subagents"]}
    assert "main" in names
    assert "Explore" in names


def test_analyze_session_empty_dir(tmp_path):
    session_dir = tmp_path / "empty-session"
    session_dir.mkdir()
    result = core.analyze_session(session_dir, PRICING)
    assert result["total"]["llm_calls"] == 0
    assert result["total"]["estimated_usd"] == 0.0
    assert result["model_breakdown"] == []
    assert result["active_duration_seconds"] is None


# ─── Detail-level shaping ─────────────────────────────────────────────────────


@pytest.fixture
def full_session_result():
    return {
        "session_id": "abc12345-1234-1234-1234-123456789abc",
        "session_dir": "/some/local/path",
        "title": "Test session",
        "started_at": "2026-07-01T12:00:00Z",
        "ended_at": "2026-07-01T12:10:00Z",
        "duration_seconds": 600,
        "active_duration_seconds": 300,
        "models": ["claude-sonnet-4.6", "Kimi-K2.6-azure"],
        "fallback_pricing_models": [],
        "model_breakdown": [
            {
                "model": "claude-sonnet-4.6",
                "input_tokens": 800,
                "output_tokens": 150,
                "cached_tokens": 400,
                "llm_calls": 3,
                "estimated_usd": 0.35,
            },
        ],
        "subagents": [
            {
                "file": "main.jsonl",
                "name": "main",
                "subagent_id": None,
                "model": "claude-sonnet-4.6",
                "input_tokens": 800,
                "output_tokens": 150,
                "cached_tokens": 400,
                "llm_calls": 3,
                "estimated_usd": 0.35,
            },
        ],
        "total": {
            "input_tokens": 1_000,
            "output_tokens": 200,
            "cached_tokens": 500,
            "llm_calls": 5,
            "estimated_usd": 0.42,
            "cache_ratio": 0.5,
        },
        "pricing_note": "note",
        "skills": {
            "detected": ["/test-skill"],
            "active": "/test-skill",
            "breakdown": [
                {
                    "skill": "/test-skill",
                    "input_tokens": 1_000,
                    "output_tokens": 200,
                    "cached_tokens": 500,
                    "llm_calls": 5,
                    "estimated_usd": 0.42,
                }
            ],
            "tool_breakdown": [
                {"tool": "read_file", "calls": 3, "skill": "/test-skill", "subagent": "main"}
            ],
        },
    }


def test_shape_session_full_is_identity(full_session_result):
    assert core.shape_session(full_session_result, "full") is full_session_result


def test_shape_session_minimal_smallest(full_session_result):
    shaped = core.shape_session(full_session_result, "minimal")
    assert "model_breakdown" not in shaped
    assert "subagents" not in shaped
    assert "fallback_pricing_models" not in shaped
    assert "pricing_note" not in shaped
    assert "skills" not in shaped
    assert shaped["total"] == full_session_result["total"]
    assert shaped["session_id"] == full_session_result["session_id"]
    assert "session_dir" not in shaped


def test_shape_session_compact_has_models_and_fallback_no_breakdown(full_session_result):
    shaped = core.shape_session(full_session_result, "compact")
    assert "model_breakdown" not in shaped
    assert "subagents" not in shaped
    assert shaped["models"] == full_session_result["models"]
    assert shaped["fallback_pricing_models"] == []
    assert shaped["pricing_note"] == "note"
    assert shaped["skills"] == full_session_result["skills"]


# ─── --format detailed alias ──────────────────────────────────────────────────


def test_resolve_detail_forces_full_for_detailed_format():
    assert core.resolve_detail("compact", "detailed") == "full"
    assert core.resolve_detail("minimal", "detailed") == "full"


def test_resolve_detail_passthrough_for_json_and_table():
    assert core.resolve_detail("compact", "json") == "compact"
    assert core.resolve_detail("minimal", "table") == "minimal"


def test_normalize_format_detailed_becomes_table():
    assert core.normalize_format("detailed") == "table"


def test_normalize_format_json_and_table_unchanged():
    assert core.normalize_format("json") == "json"
    assert core.normalize_format("table") == "table"


def test_format_choice_accepts_detailed():
    assert "detailed" in core.FORMAT_CHOICE.choices


def test_shape_session_size_ordering(full_session_result):
    sizes = {
        level: len(json.dumps(core.shape_session(full_session_result, level)))
        for level in ("minimal", "compact", "full")
    }
    assert sizes["minimal"] < sizes["compact"] < sizes["full"]


def test_shape_batch_always_has_summary_and_sessions(full_session_result):
    batch = core.shape_batch([full_session_result, full_session_result], "compact")
    assert set(batch.keys()) == {"summary", "sessions"}
    assert batch["summary"]["session_count"] == 2
    assert batch["summary"]["total_input_tokens"] == 2_000
    assert abs(batch["summary"]["total_estimated_usd"] - 0.84) < 1e-9
    assert len(batch["sessions"]) == 2
    for s in batch["sessions"]:
        assert "model_breakdown" not in s


def test_shape_batch_empty():
    batch = core.shape_batch([], "compact")
    assert batch["summary"]["session_count"] == 0
    assert batch["summary"]["total_estimated_usd"] == 0.0
    assert batch["sessions"] == []


# ─── Utilities ────────────────────────────────────────────────────────────────


def test_ts_to_iso_known_value():
    result = core.ts_to_iso(1_782_864_000_000)
    assert result == "2026-07-01T00:00:00Z"


def test_ts_to_iso_none():
    assert core.ts_to_iso(None) is None


@pytest.mark.parametrize(
    ("value", "expected_approx"),
    [
        ("2026-07-01", 1_782_864_000_000),
        ("2026-07-01T00:00:00Z", 1_782_864_000_000),
        ("2026-07-01T00:00:00", 1_782_864_000_000),
    ],
)
def test_parse_since_to_ms(value, expected_approx):
    result = core.parse_since_to_ms(value)
    assert result is not None
    assert abs(result - expected_approx) < 1000


def test_parse_since_to_ms_with_timezone_offset():
    result = core.parse_since_to_ms("2026-07-01T02:00:00+02:00")
    assert result is not None
    assert abs(result - 1_782_864_000_000) < 1000


def test_parse_since_to_ms_invalid_returns_none():
    assert core.parse_since_to_ms("not-a-date") is None


# ─── Name filtering ───────────────────────────────────────────────────────────


def test_filter_sessions_by_name_matches_title():
    sessions = [
        {"session_id": "s1", "title": "PRD: /path/to/prd"},
        {"session_id": "s2", "title": "Other topic"},
    ]
    result = core.filter_sessions_by_name(sessions, r"PRD:.*/path/to/prd")
    assert len(result) == 1
    assert result[0]["session_id"] == "s1"


def test_filter_sessions_by_name_matches_session_id():
    sessions = [
        {"session_id": "abc-123-prd", "title": "No match"},
        {"session_id": "s2", "title": "Other"},
    ]
    result = core.filter_sessions_by_name(sessions, r"prd")
    assert len(result) == 1
    assert result[0]["session_id"] == "abc-123-prd"


def test_filter_sessions_by_name_invalid_regex_raises():
    with pytest.raises(ValueError, match="Invalid name regex"):
        core.filter_sessions_by_name([], r"[invalid")


# ─── Efficiency summary ───────────────────────────────────────────────────────


def test_compute_efficiency_summary(full_session_result):
    summary = core.compute_efficiency_summary(full_session_result)
    assert summary["session_id"] == full_session_result["session_id"]
    assert summary["cache_ratio"] == 0.5
    assert summary["total_tokens"] == 1_700
    assert summary["cost_per_1m_tokens"] > 0
    assert len(summary["model_split"]) == 1
    assert summary["model_split"][0]["model"] == "claude-sonnet-4.6"


def test_compute_efficiency_summary_empty_model_breakdown():
    result = {
        "session_id": "s1",
        "title": "Empty",
        "total": {
            "input_tokens": 0,
            "output_tokens": 0,
            "cached_tokens": 0,
            "llm_calls": 0,
            "estimated_usd": 0.0,
            "cache_ratio": 0.0,
        },
        "model_breakdown": [],
    }
    summary = core.compute_efficiency_summary(result)
    assert summary["total_tokens"] == 0
    assert summary["cost_per_1m_tokens"] == 0.0
    assert summary["model_split"] == []


# ─── Aggregate sessions ───────────────────────────────────────────────────────


def test_aggregate_sessions(full_session_result):
    aggregate = core.aggregate_sessions([full_session_result, full_session_result])
    assert aggregate["session_count"] == 2
    assert aggregate["total_input_tokens"] == 2_000
    assert aggregate["total_tokens"] == 3_400
    assert aggregate["avg_cache_ratio"] == 0.5
    assert aggregate["cost_per_1m_tokens"] > 0
    assert len(aggregate["model_split"]) == 1


def test_aggregate_sessions_empty():
    aggregate = core.aggregate_sessions([])
    assert aggregate["session_count"] == 0
    assert aggregate["total_estimated_usd"] == 0.0
    assert aggregate["model_split"] == []


# ─── JSON path query ──────────────────────────────────────────────────────────


def test_query_json_path_nested_dict():
    data = {"total": {"estimated_usd": 1.23}}
    assert core.query_json_path(data, ".total.estimated_usd") == 1.23


def test_query_json_path_array_index():
    data = {"items": [{"name": "first"}, {"name": "second"}]}
    assert core.query_json_path(data, ".items[0].name") == "first"


def test_query_json_path_array_wildcard():
    data = {"items": [{"name": "first"}, {"name": "second"}]}
    assert core.query_json_path(data, ".items[*]") == [{"name": "first"}, {"name": "second"}]


def test_query_json_path_missing_key_returns_none():
    data = {"total": {"estimated_usd": 1.23}}
    assert core.query_json_path(data, ".total.missing") is None


def test_query_json_path_no_leading_dot():
    data = {"total": {"estimated_usd": 1.23}}
    assert core.query_json_path(data, "total.estimated_usd") == 1.23


# ─── Queryable fields reference ───────────────────────────────────────────────


def test_get_queryable_fields():
    fields = core.get_queryable_fields()
    assert "session_id" in fields
    assert "total.estimated_usd" in fields


# ─── Directory session listing ────────────────────────────────────────────────


def test_list_session_dirs(tmp_path):
    debug_dir = tmp_path / "debug-logs"
    debug_dir.mkdir()
    session_a = debug_dir / "sess-a"
    session_a.mkdir()
    (session_a / "main.jsonl").write_text("{}", encoding="utf-8")
    session_b = debug_dir / "sess-b"
    session_b.mkdir()
    (session_b / "main.jsonl").write_text("{}", encoding="utf-8")
    (debug_dir / "not-a-session.txt").write_text("", encoding="utf-8")

    sessions = core.list_session_dirs(debug_dir)
    assert len(sessions) == 2
    assert {s["session_id"] for s in sessions} == {"sess-a", "sess-b"}


def test_list_session_dirs_missing_dir():
    assert core.list_session_dirs(Path("/nonexistent/debug-logs")) == []


def test_list_session_dirs_skips_dirs_without_jsonl(tmp_path):
    debug_dir = tmp_path / "debug-logs"
    debug_dir.mkdir()
    (debug_dir / "empty-dir").mkdir()
    assert core.list_session_dirs(debug_dir) == []


# ─── Skill detection and attribution ──────────────────────────────────────────


def _make_user_message_event(content: str, ts: int = 1000) -> str:
    return json.dumps({"ts": ts, "type": "user_message", "attrs": {"content": content}})


def _make_skill_discovery_event(details: str, ts: int = 1000) -> str:
    return json.dumps(
        {"ts": ts, "type": "discovery", "name": "Skill Discovery", "attrs": {"details": details}}
    )


def _make_custom_instructions_event(details: str, ts: int = 1000) -> str:
    return json.dumps(
        {"ts": ts, "type": "generic", "name": "Custom Instructions", "attrs": {"details": details}}
    )


def test_extract_slash_command_skill_namespace():
    assert (
        core._extract_slash_command_skill("/compendium-generic get-session-costs")
        == "/compendium-generic get-session-costs"
    )


def test_extract_slash_command_skill_single_token():
    assert core._extract_slash_command_skill("/deploy") == "/deploy"


def test_extract_slash_command_skill_ignores_regular_text():
    assert core._extract_slash_command_skill("hello /world") is None


def test_extract_slash_command_skill_trims_extra_args():
    assert (
        core._extract_slash_command_skill("/compendium-generic grill-me some extra args")
        == "/compendium-generic grill-me"
    )


def test_extract_skills_from_discovery():
    details = "loaded: ['skill-a', 'skill-b']"
    assert core._extract_skills_from_discovery(details) == ["skill-a", "skill-b"]


def test_extract_skills_from_generic_details():
    details = "skills: [2] skill-a, skill-b\nagents: agent-1"
    assert core._extract_skills_from_generic_details(details) == ["skill-a", "skill-b"]


def test_build_skill_timeline_from_user_messages(tmp_path):
    session_dir = tmp_path / "sess"
    session_dir.mkdir()
    (session_dir / "main.jsonl").write_text(
        _make_user_message_event("/skill-a", ts=1000)
        + "\n"
        + _make_user_message_event("/skill-b", ts=2000)
        + "\n",
        encoding="utf-8",
    )
    timeline = core.build_skill_timeline(session_dir)
    assert timeline == [(1000, "/skill-a"), (2000, "/skill-b")]


def test_active_skill_at_ts_returns_most_recent(tmp_path):
    timeline = [(1000, "/skill-a"), (2000, "/skill-b")]
    assert core.active_skill_at_ts(1500, timeline) == "/skill-a"
    assert core.active_skill_at_ts(2500, timeline) == "/skill-b"
    assert core.active_skill_at_ts(500, timeline) is None


def test_detect_session_skills_from_multiple_sources(tmp_path):
    session_dir = tmp_path / "sess"
    session_dir.mkdir()
    (session_dir / "main.jsonl").write_text(
        _make_user_message_event("/skill-a", ts=1000)
        + "\n"
        + _make_skill_discovery_event("loaded: ['skill-b']", ts=2000)
        + "\n"
        + _make_custom_instructions_event("skills: [1] skill-c\nagents: x", ts=3000)
        + "\n",
        encoding="utf-8",
    )
    detected = core.detect_session_skills(session_dir)
    assert set(detected["detected"]) == {"/skill-a", "skill-b", "skill-c"}


def test_parse_jsonl_file_attributes_to_skill(tmp_path):
    f = tmp_path / "main.jsonl"
    f.write_text(
        _make_user_message_event("/my-skill", ts=500)
        + "\n"
        + _make_llm_event("claude-sonnet-4.6", 100, 50, ts=1000)
        + "\n"
        + _make_llm_event("claude-sonnet-4.6", 200, 30, ts=2000)
        + "\n",
        encoding="utf-8",
    )
    timeline = core.build_skill_timeline(tmp_path)
    stats = core.parse_jsonl_file(f, timeline)
    assert stats["per_skill"]["/my-skill"]["input"] == 300
    assert stats["per_skill"]["/my-skill"]["calls"] == 2


def test_parse_tool_calls(tmp_path):
    session_dir = tmp_path / "sess"
    session_dir.mkdir()
    (session_dir / "main.jsonl").write_text(
        _make_user_message_event("/my-skill", ts=500)
        + "\n"
        + json.dumps({"ts": 1000, "type": "tool_call", "name": "read_file", "attrs": {}})
        + "\n"
        + json.dumps({"ts": 2000, "type": "tool_call", "name": "run_in_terminal", "attrs": {}})
        + "\n",
        encoding="utf-8",
    )
    timeline = core.build_skill_timeline(session_dir)
    calls = core.parse_tool_calls(session_dir, timeline)
    assert len(calls) == 2
    assert calls[0]["tool"] == "read_file"
    assert calls[0]["skill"] == "/my-skill"
    assert calls[0]["subagent"] == "main"


def test_aggregate_tool_calls(tmp_path):
    calls = [
        {"tool": "read_file", "skill": "/my-skill", "subagent": "main"},
        {"tool": "read_file", "skill": "/my-skill", "subagent": "main"},
        {"tool": "run_in_terminal", "skill": "/my-skill", "subagent": "main"},
    ]
    breakdown = core.aggregate_tool_calls(calls)
    assert len(breakdown) == 2
    read_file = next(b for b in breakdown if b["tool"] == "read_file")
    assert read_file["calls"] == 2


def test_analyze_session_skill_breakdown(tmp_path):
    session_dir = _write_session(
        tmp_path,
        {
            "main.jsonl": [
                _make_user_message_event("/my-skill", ts=500),
                _make_llm_event("claude-sonnet-4.6", 1000, 100, 200, ts=1000),
                _make_llm_event("claude-sonnet-4.6", 500, 50, 0, ts=2000),
            ]
        },
    )
    result = core.analyze_session(session_dir, PRICING)
    assert result["skills"]["active"] == "/my-skill"
    assert "/my-skill" in {s["skill"] for s in result["skills"]["breakdown"]}
    skill = next(s for s in result["skills"]["breakdown"] if s["skill"] == "/my-skill")
    assert skill["input_tokens"] == 1500
    assert skill["llm_calls"] == 2


def test_shape_session_skill_breakdown():
    data = {
        "session_id": "s1",
        "title": "Test",
        "skills": {
            "breakdown": [
                {
                    "skill": "/a",
                    "input_tokens": 100,
                    "output_tokens": 10,
                    "cached_tokens": 0,
                    "llm_calls": 1,
                    "estimated_usd": 0.1,
                }
            ]
        },
    }
    shaped = core.shape_session_skill_breakdown(data)
    assert shaped["skill_breakdown"][0]["skill"] == "/a"


def test_shape_session_tool_breakdown():
    data = {
        "session_id": "s1",
        "title": "Test",
        "skills": {
            "tool_breakdown": [{"tool": "read_file", "calls": 5, "skill": "/a", "subagent": "main"}]
        },
    }
    shaped = core.shape_session_tool_breakdown(data)
    assert shaped["tool_breakdown"][0]["tool"] == "read_file"


def test_shape_session_minimal_skill_found():
    data = {
        "skills": {
            "breakdown": [
                {
                    "skill": "/a",
                    "input_tokens": 100,
                    "output_tokens": 10,
                    "cached_tokens": 0,
                    "llm_calls": 1,
                    "estimated_usd": 0.1,
                }
            ]
        }
    }
    shaped = core.shape_session_minimal_skill(data, "/a")
    assert shaped == {
        "skill": "/a",
        "cost_usd": 0.1,
        "input_tokens": 100,
        "output_tokens": 10,
        "cached_tokens": 0,
        "llm_calls": 1,
    }


def test_shape_session_minimal_skill_not_found():
    assert core.shape_session_minimal_skill({"skills": {"breakdown": []}}, "/missing") is None


def test_aggregate_skills():
    results = [
        {
            "skills": {
                "breakdown": [
                    {
                        "skill": "/a",
                        "input_tokens": 100,
                        "output_tokens": 10,
                        "cached_tokens": 0,
                        "llm_calls": 1,
                        "estimated_usd": 0.1,
                    }
                ]
            }
        },
        {
            "skills": {
                "breakdown": [
                    {
                        "skill": "/a",
                        "input_tokens": 200,
                        "output_tokens": 20,
                        "cached_tokens": 0,
                        "llm_calls": 2,
                        "estimated_usd": 0.2,
                    }
                ]
            }
        },
    ]
    aggregate = core.aggregate_skills(results)
    assert aggregate["session_count"] == 2
    skill = next(s for s in aggregate["skills"] if s["skill"] == "/a")
    assert skill["input_tokens"] == 300
    assert skill["llm_calls"] == 3
    assert skill["estimated_usd"] == 0.3


def test_parse_last_window_to_ms():
    result = core.parse_last_window_to_ms("1h")
    assert result is not None
    from datetime import datetime, timezone

    expected = int((datetime.now(timezone.utc).timestamp() - 3600) * 1000)
    assert abs(result - expected) < 1000


def test_parse_last_window_to_ms_invalid():
    assert core.parse_last_window_to_ms("not-a-duration") is None


def test_render_skill_breakdown():
    data = {
        "skill_breakdown": [
            {
                "skill": "/a",
                "input_tokens": 1000,
                "output_tokens": 100,
                "cached_tokens": 0,
                "llm_calls": 5,
                "estimated_usd": 0.1234,
            }
        ]
    }
    text = core.render_skill_breakdown(data)
    assert "/a" in text
    assert "$0.1234" in text


def test_render_tool_breakdown():
    data = {
        "tool_breakdown": [{"tool": "read_file", "calls": 5, "skill": "/a", "subagent": "main"}]
    }
    text = core.render_tool_breakdown(data)
    assert "read_file" in text
    assert "/a" in text


def test_render_skills_aggregate():
    data = {
        "session_count": 2,
        "skills": [
            {
                "skill": "/a",
                "sessions": 2,
                "input_tokens": 300,
                "output_tokens": 30,
                "cached_tokens": 0,
                "llm_calls": 3,
                "estimated_usd": 0.3,
            }
        ],
    }
    text = core.render_skills_aggregate(data)
    assert "/a" in text
    assert "$0.3000" in text
