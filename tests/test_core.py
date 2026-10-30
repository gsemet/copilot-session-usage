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


def test_billed_cost_is_preserved_in_every_breakdown(tmp_path):
    events = [
        {"type": "user_message", "ts": 1, "attrs": {"content": "/audit"}},
        {
            "type": "llm_request",
            "ts": 2,
            "attrs": {
                "model": "gpt-5.6-sol",
                "inputTokens": 1000,
                "outputTokens": 100,
                "cachedTokens": 500,
                "copilotUsageNanoAiu": 12_345_000_000,
            },
        },
    ]
    (tmp_path / "main.jsonl").write_text(
        "\n".join(json.dumps(event) for event in events), encoding="utf-8"
    )
    result = core.analyze_session(tmp_path, PRICING)
    assert result["total"]["estimated_usd"] == pytest.approx(0.12345)
    assert result["model_breakdown"][0]["estimated_usd"] == pytest.approx(0.12345)
    assert result["subagents"][0]["estimated_usd"] == pytest.approx(0.12345)
    assert result["skills"]["breakdown"][0]["estimated_usd"] == pytest.approx(0.12345)


def test_get_model_rates_exact_match():
    rates = core._get_model_rates("gpt-4o", 0, PRICING)
    assert rates["input_per_m"] == 0.25


@pytest.mark.parametrize("billing", [None, 0, 10_000_000_000])
def test_request_costs_use_billing_and_individual_context_tiers(tmp_path, billing):
    pricing = core.load_pricing(Path(core.__file__).parents[1] / "data")
    events = [{"type": "user_message", "ts": 1, "attrs": {"content": "/audit"}}]
    expected = 0.0
    for timestamp, input_tokens in enumerate([150_000, 150_000, 300_000], start=2):
        attrs = {
            "model": "gpt-5.6-sol",
            "inputTokens": input_tokens,
            "outputTokens": 1000,
            "cachedTokens": 100_000,
        }
        if timestamp == 2 and billing is not None:
            attrs["copilotUsageNanoAiu"] = billing
            expected += billing / 1e11
        else:
            expected += core.estimate_cost(input_tokens, 1000, 100_000, "gpt-5.6-sol", pricing)
        events.append({"type": "llm_request", "ts": timestamp, "attrs": attrs})
    (tmp_path / "main.jsonl").write_text(
        "\n".join(json.dumps(event) for event in events), encoding="utf-8"
    )
    result = core.analyze_session(tmp_path, pricing)
    assert result["total"]["estimated_usd"] == pytest.approx(round(expected, 4))
    for breakdown in [
        result["model_breakdown"],
        result["subagents"],
        result["skills"]["breakdown"],
    ]:
        assert breakdown[0]["estimated_usd"] == pytest.approx(round(expected, 6))


def test_get_model_rates_prefix_match():
    rates = core._get_model_rates("claude-haiku-4.6", 0, PRICING)
    assert rates["input_per_m"] == 0.08


def _gpt_54_row(model, threshold, tier, input_, cached, output):
    return {
        "model": model,
        "threshold": threshold,
        "tier": tier,
        "input": input_,
        "cached_input": cached,
        "output": output,
        "cache_write": "Not applicable",
    }


GPT_54_ROWS = [
    _gpt_54_row("GPT-5.4", "≤ 272K", "Default", "$2.50", "$0.25", "$15.00"),
    _gpt_54_row("GPT-5.4", "> 272K", "Long context", "$5.00", "$0.50", "$22.50"),
]


def test_versioned_model_uses_most_specific_pricing():
    rows = GPT_54_ROWS + [
        _gpt_54_row("GPT-5.4 mini", "Not applicable", "Default", "$0.75", "$0.075", "$4.50")
    ]
    pricing = core._build_pricing_from_yaml(rows, "test")
    rates = core._get_model_rates("gpt-5.4-mini-2026-10-01", 100_000, pricing)
    assert rates == pricing["models"]["gpt-5.4-mini"][0]


def test_request_costs_reconcile_across_files_and_skills(tmp_path):
    main = [
        {"type": "user_message", "ts": 1, "attrs": {"content": "/first"}},
        {
            "type": "llm_request",
            "ts": 2,
            "attrs": {
                "model": "claude-sonnet-4.6",
                "inputTokens": 1000,
                "copilotUsageNanoAiu": 10_000_000_000,
            },
        },
        {"type": "user_message", "ts": 3, "attrs": {"content": "/second"}},
    ]
    child = [
        {
            "type": "llm_request",
            "ts": 4,
            "attrs": {"model": "claude-sonnet-4.6", "inputTokens": 100_000},
        },
        {
            "type": "llm_request",
            "ts": 5,
            "attrs": {
                "model": "gpt-5.6-sol",
                "inputTokens": 1000,
                "copilotUsageNanoAiu": 20_000_000_000,
            },
        },
    ]
    for filename, events in [("main.jsonl", main), ("runSubagent-worker.jsonl", child)]:
        (tmp_path / filename).write_text(
            "\n".join(json.dumps(event) for event in events), encoding="utf-8"
        )
    result = core.analyze_session(tmp_path, PRICING)
    assert result["total"]["estimated_usd"] == pytest.approx(0.33)
    for breakdown in [
        result["model_breakdown"],
        result["subagents"],
        result["skills"]["breakdown"],
    ]:
        assert sum(row["estimated_usd"] for row in breakdown) == pytest.approx(0.33)
    assert {row["skill"]: row["estimated_usd"] for row in result["skills"]["breakdown"]} == {
        "/first": pytest.approx(0.1),
        "/second": pytest.approx(0.23),
    }


def test_cache_write_fallback_for_every_bundled_model_tier():
    pricing = core.load_pricing(Path(core.__file__).parents[1] / "data")
    for model, tiers in pricing["models"].items():
        previous_threshold = 0
        for tier in tiers:
            input_tokens = max(tier["threshold_tokens"] or 1000, previous_threshold + 1)
            cached_tokens = input_tokens // 2
            output_tokens = 1000
            fresh_rate = max(tier["input_per_m"], tier["cache_write_per_m"])
            expected = (
                (input_tokens - cached_tokens) * fresh_rate
                + cached_tokens * tier["cache_per_m"]
                + output_tokens * tier["output_per_m"]
            ) / 1e6
            assert core.estimate_cost(
                input_tokens, output_tokens, cached_tokens, model, pricing
            ) == pytest.approx(expected), (model, tier["tier"])
            previous_threshold = input_tokens


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


@pytest.mark.parametrize(
    "model",
    [
        "GPT-4o",
        "gpt-4o-mini-2024-07-18",
        "GPT-4.1",
        "gpt-5.4-nano",
        "gpt-5.4-nano-2025-01-01",
    ],
)
def test_is_utility_model(model):
    assert core.is_utility_model(model)


@pytest.mark.parametrize("model", ["gpt-5.6-luna", "gpt-5.4", "claude-sonnet-4.6"])
def test_is_utility_model_rejects_billed_models(model):
    assert not core.is_utility_model(model)


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


@pytest.mark.parametrize("reverse", [False, True])
@pytest.mark.parametrize(
    ("upper", "lower", "boundary"),
    [
        ("≤ 272K", "> 272K", 272_000),
        ("<= 272K", "> 272K", 272_000),
        ("<= 271999", ">= 272K", 271_999),
        ("≤ 271999", "≥ 272K", 271_999),
    ],
)
def test_threshold_aware_pricing_is_order_independent(reverse, upper, lower, boundary):
    rows = [{**GPT_54_ROWS[0], "threshold": upper}, {**GPT_54_ROWS[1], "threshold": lower}]
    pricing = core._build_pricing_from_yaml(list(reversed(rows)) if reverse else rows, "test")
    pricing["models"]["gpt-5.4"].reverse()
    for tokens in [0, boundary - 1, boundary, boundary + 1, 500_000]:
        expected = rows[0] if tokens <= boundary else rows[1]
        assert core._get_model_rates("gpt-5.4", tokens, pricing)["tier"] == expected["tier"]
        cached = tokens // 2
        expected_cost = (
            (tokens - cached) * core._parse_price(expected["input"])
            + cached * core._parse_price(expected["cached_input"])
            + 1000 * core._parse_price(expected["output"])
        ) / 1e6
        assert core.estimate_cost(tokens, 1000, cached, "gpt-5.4", pricing) == pytest.approx(
            expected_cost
        )


def test_threshold_aware_pricing_does_not_ignore_lower_bound():
    pricing = core._build_pricing_from_yaml([{"model": "Test", "threshold": ">= 100K"}], "test")
    with pytest.raises(ValueError, match="no pricing tier"):
        core._get_model_rates("test", 99_999, pricing)


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


def _call(model, inp, out, cached=0, nano=None, write=None, **kw):
    return core.make_call(
        ts_ms=kw.pop("ts_ms", 1000),
        model=model,
        input_tokens=inp,
        cached_tokens=cached,
        output_tokens=out,
        cache_write_tokens=write,
        nano_aiu=nano,
        **kw,
    )


def test_summarize_calls_single_model_cost():
    summary = core.summarize_calls([_call("claude-sonnet-4.6", 1_000_000, 0)], PRICING)
    assert abs(summary["total"]["estimated_usd"] - 0.30) < 1e-9
    assert summary["total"]["cost_source"] == "estimated"


def test_summarize_calls_multi_model_priced_per_model():
    calls = [
        _call("claude-sonnet-4.6", 1_887_586, 47_184, 1_386_477),
        _call("Kimi-K2.6-azure", 6_168, 1_862),
    ]
    pricing = {
        "models": {
            **PRICING["models"],
            "Kimi-K2.6-azure": [
                {"input_per_m": 0.15, "output_per_m": 0.60, "cache_per_m": 0.015, "tier": "Default"}
            ],
        }
    }
    summary = core.summarize_calls(calls, pricing)
    wrong_cost = core.estimate_cost(
        1_887_586 + 6_168, 47_184 + 1_862, 1_386_477, "Kimi-K2.6-azure", pricing
    )
    assert summary["total"]["estimated_usd"] > wrong_cost * 1.5
    assert abs(summary["total"]["estimated_usd"] - 0.265) < 0.005
    assert sum(r["estimated_usd"] for r in summary["model_breakdown"]) == pytest.approx(
        summary["total"]["estimated_usd"]
    )


def test_dominant_model_by_input_tokens():
    priced = core.price_calls(
        [_call("claude-sonnet-4.6", 1_000_000, 0), _call("Kimi-K2.6-azure", 6_000, 0)], PRICING
    )
    assert core._dominant_model(priced) == "claude-sonnet-4.6"


def test_dominant_model_empty():
    assert core._dominant_model([]) == "unknown"


def test_dominant_model_ties_break_by_name():
    priced = core.price_calls([_call("b-model", 10, 0), _call("a-model", 10, 0)], PRICING)
    assert core._dominant_model(priced) == "a-model"


def test_price_calls_billed_zero_is_billed_not_estimated():
    priced = core.price_calls([_call("claude-sonnet-4.6", 1000, 10, nano=0)], PRICING)
    assert priced[0]["usd"] == 0.0
    assert priced[0]["cost_source"] == "billed"
    assert priced[0]["token_estimate_usd"] > 0


def test_summarize_calls_cost_source_billed_estimated_mixed():
    billed = _call("claude-sonnet-4.6", 1000, 10, nano=5_000_000_000)
    estimated = _call("claude-sonnet-4.6", 1000, 10)
    other = _call("claude-haiku-4.6", 1000, 10)
    assert core.summarize_calls([billed], PRICING)["total"]["cost_source"] == "billed"
    assert core.summarize_calls([estimated], PRICING)["total"]["cost_source"] == "estimated"
    mixed = core.summarize_calls([billed, estimated, other], PRICING)
    assert mixed["total"]["cost_source"] == "mixed"
    by_model = {r["model"]: r["cost_source"] for r in mixed["model_breakdown"]}
    assert by_model == {"claude-sonnet-4.6": "mixed", "claude-haiku-4.6": "estimated"}


def test_summarize_calls_reconciliation_block():
    billed = _call("claude-sonnet-4.6", 1_000_000, 0, nano=3_000_000_000)  # $0.03
    unbilled = _call("claude-sonnet-4.6", 1_000_000, 0)
    rec = core.summarize_calls([billed, unbilled], PRICING)["reconciliation"]
    assert rec["billed_usd"] == pytest.approx(0.03)
    assert rec["estimated_from_tokens_usd"] == pytest.approx(0.30)
    assert rec["delta_pct"] == pytest.approx(900.0)
    assert rec["calls_without_billing"] == 1


def test_summarize_calls_empty_is_zero_not_unavailable():
    summary = core.summarize_calls([], PRICING)
    assert summary["total"]["input_tokens"] == 0
    assert summary["total"]["estimated_usd"] == 0
    assert summary["total"]["cost_source"] is None
    assert summary["reconciliation"]["delta_pct"] is None
    assert summary["model_breakdown"] == []


def test_summarize_calls_uncached_excludes_cache_read_and_write():
    call = _call("claude-sonnet-4.6", 1000, 10, cached=300, write=200)
    total = core.summarize_calls([call], PRICING)["total"]
    assert total["input_tokens"] == 1000
    assert total["cached_tokens"] == 300
    assert total["cache_write_tokens"] == 200
    assert total["uncached_input_tokens"] == 500
    assert total["cache_ratio"] == 0.3


def test_summarize_calls_cache_write_none_for_vscode_style_calls():
    total = core.summarize_calls([_call("claude-sonnet-4.6", 1000, 10, cached=400)], PRICING)[
        "total"
    ]
    assert total["cache_write_tokens"] is None
    assert total["uncached_input_tokens"] == 600


def test_summarize_calls_compaction_and_initiators():
    calls = [
        _call("claude-sonnet-4.6", 1000, 10, nano=1_000_000_000, initiator="user"),
        _call(
            "claude-sonnet-4.6",
            2000,
            20,
            nano=2_000_000_000,
            initiator="compaction",
            kind="compaction",
            llm_calls=3,
        ),
    ]
    summary = core.summarize_calls(calls, PRICING)
    assert summary["total"]["compaction"] == {"calls": 3, "estimated_usd": 0.02}
    assert summary["total"]["llm_calls"] == 4
    assert {r["initiator"]: r["llm_calls"] for r in summary["initiator_breakdown"]} == {
        "user": 1,
        "compaction": 3,
    }


def test_summarize_calls_per_model_usd_sums_to_total():
    calls = [
        _call("claude-sonnet-4.6", 1234, 56, nano=123_456_789),
        _call("claude-sonnet-4.6", 4321, 65, nano=987_654_321),
        _call("claude-haiku-4.6", 999, 9),
        _call("gpt-5.6-sol", 5, 5, nano=1_111_111_111),
    ]
    summary = core.summarize_calls(calls, PRICING)
    assert sum(r["estimated_usd"] for r in summary["model_breakdown"]) == pytest.approx(
        summary["total"]["estimated_usd"], abs=1e-9
    )


def test_estimate_call_usd_tier_uses_call_own_input_size():
    pricing = core.load_pricing(Path(core.__file__).parents[1] / "data")
    small = _call("gpt-5.6-sol", 150_000, 1000, cached=100_000)
    large = _call("gpt-5.6-sol", 300_000, 1000, cached=100_000)
    expected_small = core.estimate_cost(150_000, 1000, 100_000, "gpt-5.6-sol", pricing)
    expected_large = core.estimate_cost(300_000, 1000, 100_000, "gpt-5.6-sol", pricing)
    assert core.estimate_call_usd(small, pricing) == pytest.approx(expected_small)
    assert core.estimate_call_usd(large, pricing) == pytest.approx(expected_large)


def test_filter_calls_by_window():
    calls = [_call("m", 1, 1, ts_ms=t) for t in (100, 200, 300)] + [_call("m", 1, 1, ts_ms=None)]
    assert core.filter_calls_by_window(calls) is calls
    assert [c["ts_ms"] for c in core.filter_calls_by_window(calls, since_ms=200)] == [200, 300]
    assert [c["ts_ms"] for c in core.filter_calls_by_window(calls, until_ms=200)] == [100, 200]
    both = core.filter_calls_by_window(calls, since_ms=150, until_ms=250)
    assert [c["ts_ms"] for c in both] == [200]


def test_export_call_fields_and_deterministic_order():
    calls = [
        _call("claude-sonnet-4.6", 1000, 10, cached=100, nano=500_000_000, ts_ms=2000),
        _call("claude-sonnet-4.6", 500, 5, ts_ms=1000, agent="worker", agent_id="a1"),
    ]
    rows = core.session_calls_for_export(calls, PRICING, session_id="sid", provider="vscode")
    assert [r["ts_ms"] for r in rows] == [1000, 2000]
    assert set(rows[0]) == {
        "session_id",
        "provider",
        "ts_ms",
        "ts",
        "model",
        "input_tokens",
        "cached_tokens",
        "cache_write_tokens",
        "uncached_input_tokens",
        "output_tokens",
        "llm_calls",
        "nano_aiu",
        "estimated_usd",
        "cost_source",
        "agent",
        "agent_id",
        "initiator",
        "kind",
        "skill",
    }
    assert rows[1]["cost_source"] == "billed"
    assert rows[1]["estimated_usd"] == 0.005
    assert rows[1]["uncached_input_tokens"] == 900
    assert rows[0]["agent"] == "worker"
    assert rows[0]["cost_source"] == "estimated"


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


def _parse(path, **kw):
    return core.parse_vscode_calls(path, agent=kw.pop("agent", None), agent_id=None, **kw)


def test_parse_vscode_calls_single_model(tmp_path):
    f = tmp_path / "main.jsonl"
    f.write_text(
        _make_llm_event("claude-sonnet-4.6", 100, 50, 20, ts=1000)
        + "\n"
        + _make_llm_event("claude-sonnet-4.6", 200, 30, 0, ts=2000)
        + "\n",
        encoding="utf-8",
    )
    parsed = _parse(f)
    calls = parsed["calls"]
    assert len(calls) == 2
    assert sum(c["input"] for c in calls) == 300
    assert sum(c["output"] for c in calls) == 80
    assert sum(c["cached"] for c in calls) == 20
    assert {c["model"] for c in calls} == {"claude-sonnet-4.6"}
    assert all(c["cache_write"] is None and c["kind"] == "request" for c in calls)
    assert parsed["first_ts"] == 1000
    assert parsed["last_ts"] == 2000


def test_parse_vscode_calls_multi_model(tmp_path):
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
    calls = _parse(f)["calls"]
    assert len(calls) == 3
    assert sum(c["input"] for c in calls) == 1850
    assert {c["model"] for c in calls} == {"claude-sonnet-4.6", "Kimi-K2.6-azure"}
    assert sum(c["input"] for c in calls if c["model"] == "claude-sonnet-4.6") == 1800


def test_parse_vscode_calls_excludes_utility_models(tmp_path):
    f = tmp_path / "main.jsonl"
    f.write_text(
        _make_llm_event("gpt-4o-mini-2024-07-18", 900, 90, ts=1000)
        + "\n"
        + _make_llm_event("claude-sonnet-4.6", 100, 10, ts=2000)
        + "\n",
        encoding="utf-8",
    )
    calls = _parse(f)["calls"]
    assert [c["model"] for c in calls] == ["claude-sonnet-4.6"]
    assert calls[0]["input"] == 100
    assert calls[0]["output"] == 10


def test_parse_vscode_calls_skips_non_llm_events(tmp_path):
    f = tmp_path / "main.jsonl"
    f.write_text(
        _make_non_llm_event(ts=500)
        + "\n"
        + _make_llm_event("claude-sonnet-4.6", 100, 20, ts=1000)
        + "\n",
        encoding="utf-8",
    )
    parsed = _parse(f)
    assert len(parsed["calls"]) == 1
    # Non-LLM events still widen the wall-clock span.
    assert parsed["first_ts"] == 500
    assert parsed["calls"][0]["ts_ms"] == 1000


def test_parse_vscode_calls_empty(tmp_path):
    f = tmp_path / "empty.jsonl"
    f.write_text("", encoding="utf-8")
    parsed = _parse(f)
    assert parsed["calls"] == []
    assert parsed["first_ts"] is None


def test_parse_vscode_calls_bad_json_lines_skipped(tmp_path):
    f = tmp_path / "main.jsonl"
    f.write_text(
        "NOT JSON\n" + _make_llm_event("claude-sonnet-4.6", 50, 10, ts=1000) + "\n" + "{broken\n",
        encoding="utf-8",
    )
    assert len(_parse(f)["calls"]) == 1


def test_parse_vscode_calls_error_request_without_tokens_not_counted(tmp_path):
    """Regression (f): a failed llm_request has no token fields and is not a call."""
    f = tmp_path / "main.jsonl"
    failed = {
        "ts": 1500,
        "type": "llm_request",
        "attrs": {"model": "claude-sonnet-4.6", "error": "rate limited"},
    }
    f.write_text(
        _make_llm_event("claude-sonnet-4.6", 100, 10, ts=1000) + "\n" + json.dumps(failed) + "\n",
        encoding="utf-8",
    )
    calls = _parse(f)["calls"]
    assert len(calls) == 1
    summary = core.summarize_calls(calls, PRICING)
    assert summary["total"]["llm_calls"] == 1


def test_parse_vscode_calls_error_request_with_tokens_not_counted(tmp_path):
    f = tmp_path / "main.jsonl"
    failed = {
        "ts": 1500,
        "type": "llm_request",
        "attrs": {"model": "m", "error": "boom", "inputTokens": 99, "outputTokens": 9},
    }
    f.write_text(json.dumps(failed) + "\n", encoding="utf-8")
    assert _parse(f)["calls"] == []


def test_parse_vscode_calls_request_without_any_tokens_not_counted(tmp_path):
    f = tmp_path / "main.jsonl"
    f.write_text(
        json.dumps({"ts": 1, "type": "llm_request", "attrs": {"model": "claude-sonnet-4.6"}})
        + "\n",
        encoding="utf-8",
    )
    assert _parse(f)["calls"] == []


def test_parse_vscode_calls_nano_and_compaction_kind(tmp_path):
    f = tmp_path / "main.jsonl"
    events = [
        {
            "ts": 10,
            "type": "llm_request",
            "attrs": {
                "model": "claude-sonnet-4.6",
                "inputTokens": 10,
                "outputTokens": 1,
                "copilotUsageNanoAiu": 7,
                "debugName": "summarizeConversationHistory-full",
            },
        },
    ]
    f.write_text("\n".join(json.dumps(e) for e in events) + "\n", encoding="utf-8")
    call = _parse(f, agent="worker")["calls"][0]
    assert call["nano_aiu"] == 7
    assert call["kind"] == "compaction"
    assert call["agent"] == "worker"


def test_collect_vscode_session_calls_merges_files_sorted(tmp_path):
    (tmp_path / "main.jsonl").write_text(
        _make_llm_event("claude-sonnet-4.6", 10, 1, ts=3000) + "\n", encoding="utf-8"
    )
    (tmp_path / "runSubagent-w.jsonl").write_text(
        _make_llm_event("claude-sonnet-4.6", 20, 2, ts=1000) + "\n", encoding="utf-8"
    )
    collected = core.collect_vscode_session_calls(tmp_path)
    assert [c["ts_ms"] for c in collected["calls"]] == [1000, 3000]
    assert collected["first_ts"] == 1000
    assert collected["last_ts"] == 3000


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
    assert result["total"]["llm_calls"] is None
    assert result["total"]["estimated_usd"] is None
    assert result["reconciliation"] is None
    assert result["diagnostics"]
    assert result["model_breakdown"] == []
    assert result["active_duration_seconds"] is None


def test_analyze_session_excludes_utility_models(tmp_path):
    session_dir = _write_session(
        tmp_path,
        {
            "main.jsonl": [
                _make_llm_event("gpt-4o-mini-2024-07-18", 900, 90, ts=1_000_000),
                _make_llm_event("claude-sonnet-4.6", 100, 10, ts=2_000_000),
            ]
        },
    )
    result = core.analyze_session(session_dir, PRICING)

    assert result["total"]["llm_calls"] == 1
    assert result["total"]["input_tokens"] == 100
    assert result["models"] == ["claude-sonnet-4.6"]
    assert [model["model"] for model in result["model_breakdown"]] == ["claude-sonnet-4.6"]
    assert result["fallback_pricing_models"] == []


# ─── Detail-level shaping ─────────────────────────────────────────────────────


@pytest.fixture
def full_session_result():
    return {
        "schema_version": 2,
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
                "cached_tokens": 400,
                "cache_write_tokens": None,
                "uncached_input_tokens": 400,
                "output_tokens": 150,
                "llm_calls": 3,
                "estimated_usd": 0.35,
                "cost_source": "billed",
            },
            {
                "model": "Kimi-K2.6-azure",
                "input_tokens": 200,
                "cached_tokens": 100,
                "cache_write_tokens": None,
                "uncached_input_tokens": 100,
                "output_tokens": 50,
                "llm_calls": 2,
                "estimated_usd": 0.07,
                "cost_source": "estimated",
            },
        ],
        "subagents": [
            {
                "name": "main",
                "subagent_id": None,
                "model": "claude-sonnet-4.6",
                "input_tokens": 1_000,
                "cached_tokens": 500,
                "cache_write_tokens": None,
                "uncached_input_tokens": 500,
                "output_tokens": 200,
                "llm_calls": 5,
                "estimated_usd": 0.42,
                "cost_source": "mixed",
            },
        ],
        "initiator_breakdown": [],
        "reconciliation": {
            "billed_usd": 0.35,
            "estimated_from_tokens_usd": 0.351,
            "delta_pct": 0.29,
            "calls_without_billing": 2,
        },
        "total": {
            "input_tokens": 1_000,
            "cached_tokens": 500,
            "cache_write_tokens": None,
            "uncached_input_tokens": 500,
            "output_tokens": 200,
            "llm_calls": 5,
            "estimated_usd": 0.42,
            "cost_source": "mixed",
            "cache_ratio": 0.5,
            "compaction": {"calls": 1, "estimated_usd": 0.02},
        },
        "pricing_note": "note",
        "skills": {
            "detected": ["/test-skill"],
            "active": "/test-skill",
            "breakdown": [
                {
                    "skill": "/test-skill",
                    "input_tokens": 1_000,
                    "cached_tokens": 500,
                    "cache_write_tokens": None,
                    "uncached_input_tokens": 500,
                    "output_tokens": 200,
                    "llm_calls": 5,
                    "estimated_usd": 0.42,
                    "cost_source": "mixed",
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
    assert set(batch.keys()) == {"schema_version", "summary", "sessions"}
    assert batch["schema_version"] == 2
    assert batch["summary"]["session_count"] == 2
    assert "model_split" not in batch["summary"]
    assert all("schema_version" not in s for s in batch["sessions"])


def _unavailable_session(base):
    return {
        **base,
        "session_id": "unavailable",
        "provider": "cli",
        "total": {
            "input_tokens": None,
            "cached_tokens": None,
            "cache_write_tokens": None,
            "uncached_input_tokens": None,
            "output_tokens": None,
            "llm_calls": None,
            "estimated_usd": None,
            "cost_source": None,
            "cache_ratio": None,
            "compaction": None,
        },
        "model_breakdown": [],
        "reconciliation": None,
    }


def test_shape_span_report_has_total_models_and_minimal_sessions(full_session_result):
    unavailable = _unavailable_session(full_session_result)
    report = core.shape_span_report(
        [full_session_result, unavailable],
        since="2026-07-01T00:00:00Z",
        until="2026-07-02T00:00:00Z",
    )

    assert set(report) == {
        "schema_version",
        "report",
        "period",
        "total",
        "reconciliation",
        "models",
        "sessions",
    }
    assert report["schema_version"] == 2
    assert report["report"] == "span"
    assert report["period"]["since"] == "2026-07-01T00:00:00Z"
    assert report["total"]["session_count"] == 2
    assert report["total"]["input_tokens"] == 1_000
    assert report["total"]["sessions_with_unavailable_cost"] == 1
    assert "reconciliation" not in report["total"]
    assert "model_split" not in report["total"]
    assert report["models"][0]["model"] == "claude-sonnet-4.6"
    assert report["models"][0]["session_count"] == 1
    assert report["sessions"][0]["total"]["estimated_usd"] == 0.42
    assert report["sessions"][1]["total"]["estimated_usd"] is None
    assert "skills" not in report["sessions"][0]
    assert "schema_version" not in report["sessions"][0]
    # Per-model USD adds up to the span total.
    assert sum(m["estimated_usd"] for m in report["models"]) == pytest.approx(
        report["total"]["estimated_usd"]
    )


def test_shape_span_report_removed_fields_absent(full_session_result):
    report = core.shape_span_report([full_session_result])
    removed = {
        "total_tokens",
        "cost_per_1m_tokens",
        "cost_per_1m_input_tokens",
        "split_ratio",
        "total_duration_seconds",
        "total_active_duration_seconds",
        "avg_cache_ratio",
    }
    assert not removed & set(report["total"])
    assert not any(removed & set(m) for m in report["models"])


# ─── Session usage trailer helpers ───────────────────────────────────────────


PRICING_WITH_PROVIDERS = {
    "models": {
        "claude-sonnet-4.6": [
            {
                "input_per_m": 0.30,
                "output_per_m": 1.50,
                "cache_per_m": 0.030,
                "provider": "anthropic",
                "display_name": "Claude Sonnet 4.6",
                "tier": "Default",
            }
        ],
        "kimi-k2.7-code": [
            {
                "input_per_m": 0.95,
                "output_per_m": 4.00,
                "cache_per_m": 0.19,
                "provider": "moonshot_ai",
                "display_name": "Kimi K2.7 Code",
                "tier": "Default",
            }
        ],
        "default": [
            {
                "input_per_m": 0.30,
                "output_per_m": 1.50,
                "cache_per_m": 0.030,
                "provider": "unknown",
                "display_name": "unknown",
                "tier": "Default",
            }
        ],
    }
}


def test_model_provider_exact_match():
    assert core._model_provider("claude-sonnet-4.6", PRICING_WITH_PROVIDERS) == "anthropic"


def test_model_provider_prefix_match():
    assert core._model_provider("kimi-k2.7-code-foo", PRICING_WITH_PROVIDERS) == "moonshot_ai"


def test_model_provider_unknown():
    assert core._model_provider("brand-new-model", PRICING_WITH_PROVIDERS) == "unknown"


def test_model_display_name_exact_match():
    assert (
        core._model_display_name("claude-sonnet-4.6", PRICING_WITH_PROVIDERS) == "Claude Sonnet 4.6"
    )


def test_model_display_name_prefix_match():
    assert (
        core._model_display_name("claude-sonnet-4.6-foo", PRICING_WITH_PROVIDERS)
        == "Claude Sonnet 4.6"
    )


def test_model_display_name_unknown_fallback():
    assert core._model_display_name("brand-new-model", PRICING_WITH_PROVIDERS) == "brand-new-model"


def test_clean_model_display_name():
    assert core._clean_model_display_name("Claude Sonnet 5[^sonnet-5-promo]") == "Claude Sonnet 5"
    assert (
        core._clean_model_display_name("Claude Opus 4.8 (fast mode) (preview)")
        == "Claude Opus 4.8 (fast mode)"
    )
    assert core._clean_model_display_name("GPT-5.4") == "GPT-5.4"


def test_format_millions():
    assert core._format_millions(4_123_000) == "4.12"
    assert core._format_millions(1_213_000) == "1.21"
    assert core._format_millions(3_900_000) == "3.9"
    assert core._format_millions(0) == "0"
    assert core._format_millions(1_000_000) == "1"


def test_build_session_usage_acc_trailers():
    result = {
        "model_breakdown": [
            {
                "model": "Kimi K2.7 Code",
                "input_tokens": 4_123_000,
                "output_tokens": 1_213_000,
                "cached_tokens": 3_900_000,
                "estimated_usd": 2.3055,
            },
            {
                "model": "claude-sonnet-4.6",
                "input_tokens": 1_000_000,
                "output_tokens": 200_000,
                "cached_tokens": 500_000,
                "estimated_usd": 0.42,
            },
        ]
    }
    trailers = core.build_session_usage_acc_trailers(result, PRICING_WITH_PROVIDERS)
    assert len(trailers) == 2
    assert (
        "Copilot-Session-Usage-Acc: Moonshot AI:Kimi K2.7 Code,"
        "in:4.12,out:1.21,cache:3.9,aic:230.55" in trailers
    )
    assert (
        "Copilot-Session-Usage-Acc: Anthropic:Claude Sonnet 4.6,"
        "in:1,out:0.2,cache:0.5,aic:42" in trailers
    )


def test_build_session_usage_aic_trailer():
    result = {"total": {"estimated_usd": 23.4567}}
    assert core.build_session_usage_aic_trailer(result) == "Copilot-Session-Usage-AIC: 2345.67"


def test_build_session_usage_aic_trailer_zero():
    assert core.build_session_usage_aic_trailer({}) == "Copilot-Session-Usage-AIC: 0"


def test_build_session_usage_acc_trailers_unknown_provider_fallback():
    result = {
        "model_breakdown": [
            {
                "model": "brand-new-model",
                "input_tokens": 1_000_000,
                "output_tokens": 0,
                "cached_tokens": 0,
                "estimated_usd": 0,
            },
        ]
    }
    trailers = core.build_session_usage_acc_trailers(result, PRICING_WITH_PROVIDERS)
    expected = "Copilot-Session-Usage-Acc: unknown:brand-new-model,in:1,out:0,cache:0,aic:0"
    assert trailers == [expected]


def test_build_session_usage_acc_trailers_excludes_utility_models():
    result = {
        "model_breakdown": [
            {
                "model": "gpt-4o-mini-2024-07-18",
                "input_tokens": 1_000_000,
                "output_tokens": 100,
                "cached_tokens": 0,
                "estimated_usd": 0.1,
            },
            {
                "model": "claude-sonnet-4.6",
                "input_tokens": 1_000_000,
                "output_tokens": 100,
                "cached_tokens": 0,
                "estimated_usd": 0.1,
            },
        ]
    }

    trailers = core.build_session_usage_acc_trailers(result, PRICING_WITH_PROVIDERS)

    assert len(trailers) == 1
    assert "gpt-4o-mini-2024-07-18" not in trailers[0]
    assert "Claude Sonnet 4.6" in trailers[0]


def test_build_session_usage_acc_trailers_empty():
    assert (
        core.build_session_usage_acc_trailers({"model_breakdown": []}, PRICING_WITH_PROVIDERS) == []
    )


def test_merge_session_results():
    results = [
        {
            "total": {
                "input_tokens": 1_000_000,
                "output_tokens": 200_000,
                "cached_tokens": 100_000,
                "llm_calls": 5,
                "estimated_usd": 1.5,
            },
            "model_breakdown": [
                {
                    "model": "gpt-4o",
                    "input_tokens": 1_000_000,
                    "output_tokens": 200_000,
                    "cached_tokens": 100_000,
                    "llm_calls": 5,
                    "estimated_usd": 1.5,
                },
            ],
        },
        {
            "total": {
                "input_tokens": 2_000_000,
                "output_tokens": 400_000,
                "cached_tokens": 0,
                "llm_calls": 10,
                "estimated_usd": 3.0,
            },
            "model_breakdown": [
                {
                    "model": "gpt-4o",
                    "input_tokens": 1_000_000,
                    "output_tokens": 200_000,
                    "cached_tokens": 0,
                    "llm_calls": 5,
                    "estimated_usd": 1.5,
                },
                {
                    "model": "claude-sonnet-4.6",
                    "input_tokens": 1_000_000,
                    "output_tokens": 200_000,
                    "cached_tokens": 0,
                    "llm_calls": 5,
                    "estimated_usd": 1.5,
                },
            ],
        },
    ]
    merged = core.merge_session_results(results)
    assert merged["total"]["input_tokens"] == 3_000_000
    assert merged["total"]["output_tokens"] == 600_000
    assert merged["total"]["cached_tokens"] == 100_000
    assert merged["total"]["llm_calls"] == 15
    assert merged["total"]["estimated_usd"] == 4.5
    assert len(merged["model_breakdown"]) == 2
    gpt = next(m for m in merged["model_breakdown"] if m["model"] == "gpt-4o")
    assert gpt["input_tokens"] == 2_000_000
    assert gpt["estimated_usd"] == 3.0


def test_merge_session_results_empty():
    assert core.merge_session_results([]) == {"total": {}, "model_breakdown": []}


def test_merge_session_results_partial_model_evidence_never_crashes():
    """A model_breakdown row with None fields never crashes the merge.

    crashes the per-model sum, and only the fully-reported session contributes to
    that field's merged total, matching the ``total``-level ``_measured`` behavior.
    """
    results = [
        {
            "total": {
                "input_tokens": None,
                "output_tokens": None,
                "cached_tokens": None,
                "llm_calls": None,
                "estimated_usd": None,
            },
            "model_breakdown": [
                {
                    "model": "gpt-partial",
                    "input_tokens": None,
                    "output_tokens": None,
                    "cached_tokens": None,
                    "llm_calls": 2,
                    "estimated_usd": None,
                },
            ],
        },
        {
            "total": {
                "input_tokens": 1_000,
                "output_tokens": 200,
                "cached_tokens": 100,
                "llm_calls": 3,
                "estimated_usd": 0.5,
            },
            "model_breakdown": [
                {
                    "model": "gpt-partial",
                    "input_tokens": 1_000,
                    "output_tokens": 200,
                    "cached_tokens": 100,
                    "llm_calls": 3,
                    "estimated_usd": 0.5,
                },
            ],
        },
    ]
    merged = core.merge_session_results(results)
    gpt = merged["model_breakdown"][0]
    assert gpt["model"] == "gpt-partial"
    assert gpt["input_tokens"] == 1_000
    assert gpt["output_tokens"] == 200
    assert gpt["cached_tokens"] == 100
    assert gpt["llm_calls"] == 5
    assert gpt["estimated_usd"] == 0.5


def test_shape_batch_empty():
    batch = core.shape_batch([], "compact")
    assert batch["summary"]["session_count"] == 0
    assert batch["summary"]["estimated_usd"] is None
    assert batch["summary"]["reconciliation"] is None
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


@pytest.mark.parametrize("value", [None, 12345, 12.5, {"a": 1}, ["a"], True, False])
def test_parse_since_to_ms_non_string_returns_none(value):
    """Non-string evidence (e.g. from JSON-parsed CLI events) never raises."""
    assert core.parse_since_to_ms(value) is None


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
    assert summary["input_tokens"] == 1_000
    assert summary["uncached_input_tokens"] == 500
    assert summary["estimated_usd"] == 0.42
    assert summary["cost_source"] == "mixed"
    assert not {"total_tokens", "cost_per_1m_tokens"} & set(summary)
    assert [m["model"] for m in summary["model_split"]] == ["claude-sonnet-4.6", "Kimi-K2.6-azure"]
    assert not {"split_ratio", "cost_per_1m_input_tokens"} & set(summary["model_split"][0])


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
    assert summary["input_tokens"] == 0
    assert summary["estimated_usd"] == 0.0
    assert summary["model_split"] == []


def test_compute_efficiency_summary_unavailable_evidence_stays_none():
    """Unavailable evidence (e.g. a CLI session without usage records) propagates as None."""
    result = {
        "session_id": "s1",
        "title": "Unavailable",
        "total": {
            "input_tokens": None,
            "output_tokens": None,
            "cached_tokens": None,
            "llm_calls": None,
            "estimated_usd": None,
            "cache_ratio": None,
        },
        "model_breakdown": [],
    }
    summary = core.compute_efficiency_summary(result)
    assert summary["input_tokens"] is None
    assert summary["output_tokens"] is None
    assert summary["llm_calls"] is None
    assert summary["estimated_usd"] is None
    assert summary["cache_ratio"] is None


def test_compute_efficiency_summary_partial_model_evidence_preserved_and_no_crash():
    """A model row with partial evidence never crashes the efficiency summary.

    Its own None fields are preserved rather than fabricated as 0.
    """
    result = {
        "session_id": "s1",
        "title": "Partial",
        "total": {
            "input_tokens": 500,
            "output_tokens": 100,
            "cached_tokens": 0,
            "llm_calls": 3,
            "estimated_usd": 0.1,
            "cache_ratio": 0.0,
        },
        "model_breakdown": [
            {
                "model": "gpt-partial",
                "input_tokens": None,
                "output_tokens": None,
                "cached_tokens": None,
                "llm_calls": 2,
                "estimated_usd": None,
            },
            {
                "model": "gpt-full",
                "input_tokens": 500,
                "output_tokens": 100,
                "cached_tokens": 0,
                "llm_calls": 1,
                "estimated_usd": 0.1,
            },
        ],
    }
    summary = core.compute_efficiency_summary(result)
    by_model = {m["model"]: m for m in summary["model_split"]}
    assert by_model["gpt-partial"]["input_tokens"] is None
    assert by_model["gpt-partial"]["output_tokens"] is None
    assert by_model["gpt-partial"]["cached_tokens"] is None
    assert by_model["gpt-partial"]["estimated_usd"] is None
    assert by_model["gpt-partial"]["llm_calls"] == 2
    assert by_model["gpt-full"]["input_tokens"] == 500
    assert summary["model_split"][0]["model"] == "gpt-full"


# ─── Aggregate sessions ───────────────────────────────────────────────────────


def test_aggregate_sessions(full_session_result):
    aggregate = core.aggregate_sessions([full_session_result, full_session_result])
    assert aggregate["session_count"] == 2
    assert aggregate["input_tokens"] == 2_000
    assert aggregate["cached_tokens"] == 1_000
    assert aggregate["uncached_input_tokens"] == 1_000
    assert aggregate["output_tokens"] == 400
    assert aggregate["llm_calls"] == 10
    assert aggregate["cache_write_tokens"] is None
    assert aggregate["cost_source"] == "mixed"
    assert aggregate["compaction"] == {"calls": 2, "estimated_usd": 0.04}
    assert aggregate["reconciliation"]["billed_usd"] == 0.7
    assert aggregate["reconciliation"]["calls_without_billing"] == 4
    assert len(aggregate["model_split"]) == 2
    assert {m["session_count"] for m in aggregate["model_split"]} == {2}


def test_aggregate_sessions_has_no_removed_fields(full_session_result):
    aggregate = core.aggregate_sessions([full_session_result])
    for removed in (
        "total_tokens",
        "total_input_tokens",
        "total_estimated_usd",
        "avg_cache_ratio",
        "cost_per_1m_tokens",
        "total_duration_seconds",
        "total_active_duration_seconds",
    ):
        assert removed not in aggregate


def test_aggregate_cache_ratio_is_token_weighted_and_input_not_double_counted():
    """Regression (d): ratio = sum(cached)/sum(input), never a mean of ratios."""

    def session(inp, cached, out):
        return {
            "total": {
                "input_tokens": inp,
                "cached_tokens": cached,
                "uncached_input_tokens": inp - cached,
                "output_tokens": out,
                "llm_calls": 1,
                "estimated_usd": 0.1,
                "cache_ratio": round(cached / inp, 3),
            },
            "model_breakdown": [],
        }

    # Per-session ratios are 0.9 and 0.0: the unweighted mean would be 0.45.
    aggregate = core.aggregate_sessions([session(1000, 900, 10), session(9000, 0, 90)])
    assert aggregate["cache_ratio"] == 0.09
    assert aggregate["input_tokens"] == 10_000
    assert aggregate["output_tokens"] == 100
    assert "total_tokens" not in aggregate


def test_aggregate_sessions_empty():
    aggregate = core.aggregate_sessions([])
    assert aggregate["session_count"] == 0
    assert aggregate["estimated_usd"] is None
    assert aggregate["cache_ratio"] is None
    assert aggregate["cost_source"] is None
    assert aggregate["model_split"] == []


def test_aggregate_sessions_excludes_unavailable_evidence(full_session_result):
    """A session with unavailable evidence contributes nothing to totals."""
    unavailable = _unavailable_session(full_session_result)
    only_available = core.aggregate_sessions([full_session_result])
    with_unavailable = core.aggregate_sessions([full_session_result, unavailable])
    assert with_unavailable["input_tokens"] == only_available["input_tokens"]
    assert with_unavailable["estimated_usd"] == only_available["estimated_usd"]
    assert with_unavailable["cache_ratio"] == only_available["cache_ratio"]
    assert with_unavailable["session_count"] == 2


def test_aggregate_sessions_partial_model_evidence_never_crashes():
    """A model_breakdown row with None fields across sessions never crashes."""
    partial = {
        "session_id": "s1",
        "title": "Partial",
        "total": {
            "input_tokens": None,
            "output_tokens": None,
            "cached_tokens": None,
            "llm_calls": 2,
            "estimated_usd": None,
        },
        "model_breakdown": [
            {
                "model": "gpt-partial",
                "input_tokens": None,
                "output_tokens": None,
                "cached_tokens": None,
                "llm_calls": 2,
                "estimated_usd": None,
            },
        ],
    }
    full = {
        "session_id": "s2",
        "title": "Full",
        "total": {
            "input_tokens": 1_000,
            "output_tokens": 200,
            "cached_tokens": 100,
            "llm_calls": 3,
            "estimated_usd": 0.5,
        },
        "model_breakdown": [
            {
                "model": "gpt-partial",
                "input_tokens": 1_000,
                "output_tokens": 200,
                "cached_tokens": 100,
                "llm_calls": 3,
                "estimated_usd": 0.5,
            },
        ],
    }
    aggregate = core.aggregate_sessions([partial, full])
    assert aggregate["session_count"] == 2
    assert aggregate["input_tokens"] == 1_000
    assert aggregate["llm_calls"] == 5
    model_row = aggregate["model_split"][0]
    assert model_row["model"] == "gpt-partial"
    assert model_row["input_tokens"] == 1_000
    assert model_row["llm_calls"] == 5
    assert model_row["estimated_usd"] == 0.5


def test_aggregate_sessions_model_usd_sums_to_total(full_session_result):
    aggregate = core.aggregate_sessions([full_session_result, full_session_result])
    assert sum(m["estimated_usd"] for m in aggregate["model_split"]) == pytest.approx(
        aggregate["estimated_usd"], abs=1e-9
    )


def test_shape_batch_excludes_unavailable_cost_and_reports_count(full_session_result):
    unavailable = _unavailable_session(full_session_result)
    batch = core.shape_batch([full_session_result, unavailable], "compact")
    assert batch["summary"]["estimated_usd"] == full_session_result["total"]["estimated_usd"]
    assert batch["summary"]["input_tokens"] == full_session_result["total"]["input_tokens"]
    assert batch["summary"]["sessions_with_unavailable_cost"] == 1


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


def test_detect_session_skills_from_system_prompt_and_tools(tmp_path):
    session_dir = tmp_path / "sess"
    session_dir.mkdir()
    system_prompt = [{"type": "text", "content": "<skill><name>loaded-skill</name></skill>"}]
    (session_dir / "system_prompt_0.json").write_text(
        json.dumps({"content": json.dumps(system_prompt)}), encoding="utf-8"
    )
    tools = [
        {
            "type": "function",
            "name": "skill",
            "description": "Invoke /namespace on-demand-skill",
            "parameters": {"properties": {"skills": {"enum": ["parameter-skill"]}}},
        },
        {
            "type": "function",
            "name": "run_terminal",
            "description": "Run commands such as /absolute/path",
        },
    ]
    (session_dir / "tools_0.json").write_text(
        json.dumps({"content": json.dumps(tools)}), encoding="utf-8"
    )

    detected = core.detect_session_skills(session_dir)

    assert set(detected["detected"]) == {
        "loaded-skill",
        "/namespace on-demand-skill",
        "parameter-skill",
    }


def test_detect_session_skills_ignores_malformed_artifacts(tmp_path):
    session_dir = tmp_path / "sess"
    session_dir.mkdir()
    (session_dir / "system_prompt_0.json").write_text("not json", encoding="utf-8")
    (session_dir / "tools_0.json").write_text("not json", encoding="utf-8")

    assert core.detect_session_skills(session_dir) == {"detected": []}


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
    calls = core.parse_vscode_calls(f, agent="main", agent_id=None, skill_timeline=timeline)[
        "calls"
    ]
    assert [c["skill"] for c in calls] == ["/my-skill", "/my-skill"]
    assert sum(c["input"] for c in calls) == 300


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
        "schema_version": core.SCHEMA_VERSION,
        "reconciliation": None,
        "skill": "/a",
        "cost_usd": 0.1,
        "input_tokens": 100,
        "output_tokens": 10,
        "cache_write_tokens": None,
        "uncached_input_tokens": None,
        "cached_tokens": 0,
        "llm_calls": 1,
        "cost_source": None,
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
