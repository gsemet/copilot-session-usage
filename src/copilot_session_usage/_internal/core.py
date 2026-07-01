"""Shared cost-analysis core for coding-agent session cost analytics.

This module is a library, not an entry point. It has zero knowledge of
*where* session logs live — that is provider-specific discovery logic (see
``vscode.py`` for the VS Code Copilot extension). It only knows how to:

- price tokens against bundled ``data/models-and-pricing.yml`` (or embedded defaults)
- parse the "Copilot debug log" JSONL event schema (``llm_request`` events)
  shared across GitHub Copilot surfaces
- aggregate per-file stats into a session-level report
- shape that report to a requested detail level (``minimal``/``compact``/``full``)
- render JSON or a human-readable table
- expose reusable Click option decorators so every provider CLI looks the same
"""

from __future__ import annotations

import contextlib
import json
import re
from collections.abc import Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import click

# ─── Bundled data file access (works in wheels and editable installs) ───────


def _read_data_file(name: str) -> str | None:
    """Read a bundled data file using importlib.resources.

    Returns the file contents as a string, or None if the file is not found.
    This works whether the package is installed as a wheel (zip) or editable.
    """
    try:
        from importlib.resources import files

        ref = files("copilot_session_usage.data") / name
        return ref.read_text(encoding="utf-8")
    except Exception:
        return None


# ─── Embedded default pricing (USD per million tokens) ───────────────────────
# Approximate estimates; update with: just refresh-pricing

DEFAULT_PRICING: dict = {
    "_note": "Approximate per-token costs (USD/M). Estimates only — not GitHub's billing.",
    "_source": "embedded defaults",
    "models": {
        # Anthropic Claude
        "claude-3-5-sonnet": [
            {"input_per_m": 0.30, "output_per_m": 1.50, "cache_per_m": 0.030, "tier": "Default"}
        ],
        "claude-3-7-sonnet": [
            {"input_per_m": 0.30, "output_per_m": 1.50, "cache_per_m": 0.030, "tier": "Default"}
        ],
        "claude-sonnet-4-5": [
            {"input_per_m": 0.30, "output_per_m": 1.50, "cache_per_m": 0.030, "tier": "Default"}
        ],
        "claude-sonnet-4.6": [
            {"input_per_m": 0.30, "output_per_m": 1.50, "cache_per_m": 0.030, "tier": "Default"}
        ],
        "claude-opus-4-5": [
            {"input_per_m": 1.50, "output_per_m": 7.50, "cache_per_m": 0.150, "tier": "Default"}
        ],
        "claude-opus-4.6": [
            {"input_per_m": 1.50, "output_per_m": 7.50, "cache_per_m": 0.150, "tier": "Default"}
        ],
        "claude-haiku-4-5": [
            {"input_per_m": 0.08, "output_per_m": 0.40, "cache_per_m": 0.008, "tier": "Default"}
        ],
        "claude-haiku-4.6": [
            {"input_per_m": 0.08, "output_per_m": 0.40, "cache_per_m": 0.008, "tier": "Default"}
        ],
        # OpenAI
        "gpt-4o": [
            {"input_per_m": 0.25, "output_per_m": 1.00, "cache_per_m": 0.025, "tier": "Default"}
        ],
        "gpt-4o-mini": [
            {"input_per_m": 0.015, "output_per_m": 0.060, "cache_per_m": 0.002, "tier": "Default"}
        ],
        "o3": [
            {"input_per_m": 10.00, "output_per_m": 40.00, "cache_per_m": 1.000, "tier": "Default"}
        ],
        "o3-mini": [
            {"input_per_m": 1.10, "output_per_m": 4.40, "cache_per_m": 0.550, "tier": "Default"}
        ],
        "o4-mini": [
            {"input_per_m": 1.10, "output_per_m": 4.40, "cache_per_m": 0.550, "tier": "Default"}
        ],
        # Google Gemini
        "gemini-1.5-pro": [
            {"input_per_m": 0.125, "output_per_m": 0.375, "cache_per_m": 0.013, "tier": "Default"}
        ],
        "gemini-2.0-flash": [
            {"input_per_m": 0.075, "output_per_m": 0.30, "cache_per_m": 0.008, "tier": "Default"}
        ],
        "gemini-2.5-pro": [
            {"input_per_m": 0.125, "output_per_m": 0.375, "cache_per_m": 0.013, "tier": "Default"}
        ],
        # Moonshot (Azure-hosted)
        "Kimi-K2.6-azure": [
            {"input_per_m": 0.15, "output_per_m": 0.60, "cache_per_m": 0.015, "tier": "Default"}
        ],
        # Fallback for unknown models
        "default": [
            {"input_per_m": 0.30, "output_per_m": 1.50, "cache_per_m": 0.030, "tier": "Default"}
        ],
    },
}


# ─── Pricing helpers ──────────────────────────────────────────────────────────


def _normalize_model_name(name: str) -> str:
    """Normalize a raw model name from the YAML to our internal key format.

    Examples:
        "GPT-5.4" → "gpt-5.4"
        "Claude Sonnet 4.6" → "claude-sonnet-4.6"
        "Claude Sonnet 5[^sonnet-5-promo]" → "claude-sonnet-5"
        "Claude Opus 4.8 (fast mode) (preview)" → "claude-opus-4.8"
    """
    cleaned = re.sub(r"\[\^[^\]]+\]", "", name)
    cleaned = re.sub(r"\s*\([^)]*\)", "", cleaned)
    cleaned = cleaned.strip()
    return re.sub(r"\s+", "-", cleaned.lower())


def _parse_threshold(threshold: str) -> int | None:
    """Parse a threshold string from the YAML into a token count.

    Examples:
        "≤ 272K" → 272_000
        "> 272K" → None  (unbounded / long-context tier)
        "Not applicable" → None
    """
    if not threshold or threshold.lower() in ("not applicable", "n/a", ""):
        return None
    match = re.search(r"([0-9]+(?:\.[0-9]+)?)\s*([KM]?)", threshold)
    if not match:
        return None
    value = float(match.group(1))
    suffix = match.group(2).upper()
    multiplier = {"K": 1_000, "M": 1_000_000}.get(suffix, 1)
    return int(value * multiplier)


def _parse_price(price: str) -> float:
    """Parse a price string like '$2.50' into a float."""
    cleaned = price.replace("$", "").replace(",", "").strip()
    try:
        return float(cleaned)
    except ValueError:
        return 0.0


def _load_custom_pricing(ref_dir: Path | None = None) -> dict[str, list[dict]] | None:
    """Load custom model pricing from custom-models-pricing.yml.

    Returns a dict of model_name → [tier_dict] or None if the file is missing
    or unreadable. Custom entries override/extend the standard pricing.

    When ``ref_dir`` is None, reads from the bundled package data.
    """
    text: str | None = None
    if ref_dir is not None:
        custom_path = ref_dir / "custom-models-pricing.yml"
        if custom_path.exists():
            with contextlib.suppress(Exception):
                text = custom_path.read_text(encoding="utf-8")
    else:
        text = _read_data_file("custom-models-pricing.yml")

    if text is None:
        return None
    try:
        from ruamel.yaml import YAML

        yaml = YAML(typ="safe")
        entries = yaml.load(text)
        if not isinstance(entries, list):
            return None
        models: dict[str, list[dict]] = {}
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            raw_name = entry.get("model", "")
            if not raw_name:
                continue
            name = raw_name.strip()
            tier = {
                "input_per_m": _parse_price(entry.get("input", "0")),
                "output_per_m": _parse_price(entry.get("output", "0")),
                "cache_per_m": _parse_price(entry.get("cached_input", "0")),
                "tier": entry.get("tier", "Default"),
                "threshold_tokens": None,
            }
            models[name] = [tier]
        return models if models else None
    except Exception:
        return None


def load_pricing(ref_dir: Path | None = None) -> dict:
    """Load pricing from models-and-pricing.yml, merge custom-models-pricing.yml.

    Fall back to embedded defaults if files are missing or unreadable.

    Args:
        ref_dir: Directory containing models-and-pricing.yml and
            custom-models-pricing.yml. If None, reads from the bundled data
            shipped with the package via importlib.resources.
    """
    text: str | None = None
    source = "embedded defaults"
    if ref_dir is not None:
        yaml_path = ref_dir / "models-and-pricing.yml"
        if yaml_path.exists():
            with contextlib.suppress(Exception):
                text = yaml_path.read_text(encoding="utf-8")
                source = str(yaml_path)
    else:
        text = _read_data_file("models-and-pricing.yml")
        source = "bundled models-and-pricing.yml"

    pricing: dict | None = None
    if text is not None:
        try:
            from ruamel.yaml import YAML

            yaml = YAML(typ="safe")
            entries = yaml.load(text)
            if isinstance(entries, list):
                pricing = _build_pricing_from_yaml(entries, source)
        except Exception:
            pass
    if pricing is None:
        pricing = DEFAULT_PRICING.copy()

    custom_models = _load_custom_pricing(ref_dir)
    if custom_models:
        pricing.setdefault("models", {}).update(custom_models)

    return pricing


def _build_pricing_from_yaml(entries: list[dict], source: str) -> dict:
    """Convert YAML entries into the tier-aware pricing dict."""
    models: dict[str, list[dict]] = {}
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        raw_name = entry.get("model", "")
        if not raw_name:
            continue
        name = _normalize_model_name(raw_name)
        tier = {
            "input_per_m": _parse_price(entry.get("input", "0")),
            "output_per_m": _parse_price(entry.get("output", "0")),
            "cache_per_m": _parse_price(entry.get("cached_input", "0")),
            "tier": entry.get("tier", "Default"),
            "threshold_tokens": _parse_threshold(entry.get("threshold", "")),
        }
        models.setdefault(name, []).append(tier)

    for name, tiers in models.items():
        models[name] = sorted(
            tiers, key=lambda t: (t["threshold_tokens"] is None, t["threshold_tokens"] or 0)
        )

    if "default" not in models:
        models["default"] = DEFAULT_PRICING["models"]["default"]

    return {
        "_note": (
            "Per-token costs in USD per million tokens. Source: GitHub Copilot official pricing."
        ),
        "_source": source,
        "models": models,
    }


def _get_model_rates(model: str, input_tok: int, pricing: dict[str, Any]) -> dict[str, Any]:
    """Return pricing rates for a model at the given input-token volume.

    Uses exact match, then prefix match, then 'default'. When the matched
    model has multiple tiers (e.g. GPT-5.4 ≤272K vs >272K), selects the
    appropriate tier based on ``input_tok``.
    """
    models = pricing.get("models", {})
    tiers = models.get(model)
    if tiers is None:
        for key in models:
            if key != "default" and model.startswith(key):
                tiers = models[key]
                break
    if tiers is None:
        tiers = models.get("default", [{}])

    if len(tiers) == 1:
        return tiers[0]  # type: ignore[no-any-return]

    for tier in tiers:
        threshold = tier.get("threshold_tokens")
        if threshold is not None and input_tok <= threshold:
            return tier  # type: ignore[no-any-return]
    return tiers[-1]  # type: ignore[no-any-return]


def model_uses_fallback_pricing(model: str, pricing: dict[str, Any]) -> bool:
    """Return True if `model` matches no pricing key except the generic 'default'."""
    models = pricing.get("models", {})
    if model in models:
        return False
    return not any(key != "default" and model.startswith(key) for key in models)


def estimate_cost(
    input_tok: int, output_tok: int, cached_tok: int, model: str, pricing: dict[str, Any]
) -> float:
    """Compute estimated USD cost. Cached tokens are billed at cache_per_m rate.

    Threshold-aware: the correct tier is selected automatically based on
    ``input_tok`` so long-context requests use the higher rate.
    """
    rates = _get_model_rates(model, input_tok, pricing)
    billable_input = max(0, input_tok - cached_tok)
    return (  # type: ignore[no-any-return]
        billable_input * rates.get("input_per_m", 0.0) / 1_000_000
        + cached_tok * rates.get("cache_per_m", 0.0) / 1_000_000
        + output_tok * rates.get("output_per_m", 0.0) / 1_000_000
    )


def estimate_cost_for_file(per_model: dict[str, dict[str, int]], pricing: dict[str, Any]) -> float:
    """Sum costs per-model bucket — avoids mis-attribution when a file uses >1 model."""
    return sum(
        estimate_cost(v["input"], v["output"], v["cached"], model, pricing)
        for model, v in per_model.items()
    )


def _dominant_model(per_model: dict[str, dict]) -> str:
    """Return the model with the most input tokens (representative label only)."""
    if not per_model:
        return "unknown"
    return max(per_model, key=lambda m: per_model[m]["input"])


# ─── JSONL parsing ────────────────────────────────────────────────────────────


def parse_jsonl_file(path: Path) -> dict:
    """Parse a single .jsonl file and return aggregated token stats.

    Only ``llm_request`` events carry token data — every other event type
    is ignored for cost purposes, though non-LLM timestamps still count
    toward wall-clock ``first_ts``/``last_ts``.
    """
    stats: dict = {
        "file": path.name,
        "input_tokens": 0,
        "output_tokens": 0,
        "cached_tokens": 0,
        "llm_calls": 0,
        "per_model": {},
        "models": set(),
        "first_ts": None,
        "last_ts": None,
        "first_llm_ts": None,
        "last_llm_ts": None,
    }
    try:
        with path.open(encoding="utf-8") as f:
            for raw in f:
                line = raw.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    continue
                ts: int | None = obj.get("ts")
                if ts is not None:
                    if stats["first_ts"] is None or ts < stats["first_ts"]:
                        stats["first_ts"] = ts
                    if stats["last_ts"] is None or ts > stats["last_ts"]:
                        stats["last_ts"] = ts
                if obj.get("type") == "llm_request":
                    attrs = obj.get("attrs", {})
                    inp = attrs.get("inputTokens", 0)
                    out = attrs.get("outputTokens", 0)
                    cch = attrs.get("cachedTokens", 0)
                    stats["input_tokens"] += inp
                    stats["output_tokens"] += out
                    stats["cached_tokens"] += cch
                    stats["llm_calls"] += 1
                    model: str = attrs.get("model", "") or "unknown"
                    stats["models"].add(model)
                    bucket = stats["per_model"].setdefault(
                        model, {"input": 0, "output": 0, "cached": 0, "calls": 0}
                    )
                    bucket["input"] += inp
                    bucket["output"] += out
                    bucket["cached"] += cch
                    bucket["calls"] += 1
                    if ts is not None:
                        if stats["first_llm_ts"] is None or ts < stats["first_llm_ts"]:
                            stats["first_llm_ts"] = ts
                        if stats["last_llm_ts"] is None or ts > stats["last_llm_ts"]:
                            stats["last_llm_ts"] = ts
    except OSError:
        pass
    stats["models"] = sorted(stats["models"])
    return stats


def get_subagent_names(main_jsonl: Path) -> dict[str, str]:
    """Extract {childSessionId → childTitle} from child_session_ref events."""
    mapping: dict[str, str] = {}
    if not main_jsonl.exists():
        return mapping
    try:
        with main_jsonl.open(encoding="utf-8") as f:
            for raw in f:
                line = raw.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if obj.get("type") == "child_session_ref":
                    attrs = obj.get("attrs", {})
                    child_id: str = attrs.get("childSessionId", "")
                    child_title: str = attrs.get("childTitle", "unknown")
                    if child_id:
                        mapping[child_id] = child_title
    except OSError:
        pass
    return mapping


def _resolve_subagent_name(filename: str, subagent_names: dict[str, str]) -> tuple[str, str]:
    """Parse JSONL filename to (display_name, subagent_id).

    Pattern: runSubagent-<AgentName>-functions.runSubagent:<id>.jsonl
    The separator between ``functions.runSubagent`` and the ID is treated as
    a wildcard — any run of non-alphanumeric characters is accepted. This
    makes the parser resilient to OS-specific filename sanitisation (e.g.
    Windows replacing ``:`` with ``-`` or ``__``).
    """
    stem = filename.removesuffix(".jsonl")
    if not stem.startswith("runSubagent-"):
        name = (
            "main"
            if stem == "main"
            else ("title-generation" if stem.startswith("title-") else stem)
        )
        return name, ""

    match = re.search(r"functions\.runSubagent(.+)$", stem)
    if match:
        # Strip any separator characters to recover the bare ID
        id_part = re.sub(r"^[^a-zA-Z0-9]+", "", match.group(1))
        subagent_id = f"functions.runSubagent:{id_part}"
        if subagent_id in subagent_names:
            return subagent_names[subagent_id], subagent_id
        name_part = stem[: match.start()].removeprefix("runSubagent-").rstrip("-")
        return name_part, subagent_id

    return stem.removeprefix("runSubagent-"), ""


# ─── Session analysis ─────────────────────────────────────────────────────────


def ts_to_iso(ts_ms: int | None) -> str | None:
    """Convert epoch milliseconds to ISO 8601 UTC string."""
    if ts_ms is None:
        return None
    return datetime.fromtimestamp(ts_ms / 1000.0, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def analyze_session(session_dir: Path, pricing: dict) -> dict:
    """Analyze all JSONL files in a session directory.

    Reads every *.jsonl file to capture costs from both the parent agent
    (main.jsonl) and all subagents (runSubagent-*.jsonl). Subagents
    often account for 70-80% of total cost.
    """
    session_dir = Path(session_dir)
    session_id = session_dir.name
    subagent_names = get_subagent_names(session_dir / "main.jsonl")

    file_results: list[dict] = []
    global_first_ts: int | None = None
    global_last_ts: int | None = None
    all_models: set[str] = set()

    for jsonl_file in sorted(session_dir.glob("*.jsonl")):
        stats = parse_jsonl_file(jsonl_file)
        if stats["llm_calls"] == 0:
            continue
        file_results.append(stats)
        if stats["first_ts"] is not None and (
            global_first_ts is None or stats["first_ts"] < global_first_ts
        ):
            global_first_ts = stats["first_ts"]
        if stats["last_ts"] is not None and (
            global_last_ts is None or stats["last_ts"] > global_last_ts
        ):
            global_last_ts = stats["last_ts"]
        all_models.update(stats["models"])

    total_input = sum(s["input_tokens"] for s in file_results)
    total_output = sum(s["output_tokens"] for s in file_results)
    total_cached = sum(s["cached_tokens"] for s in file_results)
    total_calls = sum(s["llm_calls"] for s in file_results)

    global_per_model: dict[str, dict] = {}
    for stats in file_results:
        for model, tokens in stats.get("per_model", {}).items():
            if model not in global_per_model:
                global_per_model[model] = {"input": 0, "output": 0, "cached": 0, "calls": 0}
            global_per_model[model]["input"] += tokens["input"]
            global_per_model[model]["output"] += tokens["output"]
            global_per_model[model]["cached"] += tokens["cached"]
            global_per_model[model]["calls"] += tokens["calls"]

    subagents: list[dict] = []
    total_usd = 0.0

    first_llm_ts: int | None = None
    last_llm_ts: int | None = None

    for stats in file_results:
        if stats.get("first_llm_ts") is not None and (
            first_llm_ts is None or stats["first_llm_ts"] < first_llm_ts
        ):
            first_llm_ts = stats["first_llm_ts"]
        if stats.get("last_llm_ts") is not None and (
            last_llm_ts is None or stats["last_llm_ts"] > last_llm_ts
        ):
            last_llm_ts = stats["last_llm_ts"]

        per_model = stats.get("per_model", {})
        dominant = _dominant_model(per_model)
        name, subagent_id = _resolve_subagent_name(stats["file"], subagent_names)
        usd = estimate_cost_for_file(per_model, pricing)
        total_usd += usd
        subagents.append(
            {
                "file": stats["file"],
                "name": name,
                "subagent_id": subagent_id or None,
                "model": dominant,
                "input_tokens": stats["input_tokens"],
                "output_tokens": stats["output_tokens"],
                "cached_tokens": stats["cached_tokens"],
                "llm_calls": stats["llm_calls"],
                "estimated_usd": round(usd, 6),
            }
        )

    duration_s = None
    if global_first_ts is not None and global_last_ts is not None:
        duration_s = round((global_last_ts - global_first_ts) / 1000.0)

    active_duration_s = None
    if first_llm_ts is not None and last_llm_ts is not None:
        active_duration_s = round((last_llm_ts - first_llm_ts) / 1000.0)

    cache_ratio = round(total_cached / total_input, 3) if total_input > 0 else 0.0

    model_breakdown = sorted(
        [
            {
                "model": model,
                "input_tokens": v["input"],
                "output_tokens": v["output"],
                "cached_tokens": v["cached"],
                "llm_calls": v["calls"],
                "estimated_usd": round(
                    estimate_cost(v["input"], v["output"], v["cached"], model, pricing), 6
                ),
            }
            for model, v in global_per_model.items()
        ],
        key=lambda x: x["estimated_usd"],
        reverse=True,
    )

    fallback_pricing_models = sorted(
        model for model in global_per_model if model_uses_fallback_pricing(model, pricing)
    )

    return {
        "session_id": session_id,
        "session_dir": str(session_dir),
        "title": None,
        "started_at": ts_to_iso(global_first_ts),
        "ended_at": ts_to_iso(global_last_ts),
        "duration_seconds": duration_s,
        "active_duration_seconds": active_duration_s,
        "total": {
            "input_tokens": total_input,
            "output_tokens": total_output,
            "cached_tokens": total_cached,
            "llm_calls": total_calls,
            "estimated_usd": round(total_usd, 4),
            "cache_ratio": cache_ratio,
        },
        "models": [m["model"] for m in model_breakdown] or sorted(all_models),
        "fallback_pricing_models": fallback_pricing_models,
        "model_breakdown": model_breakdown,
        "subagents": subagents,
        "pricing_note": (
            "Cost estimates are approximations. Update rates in data/models-and-pricing.yml. "
            "Models listed in fallback_pricing_models were priced with the generic "
            "'default' rate and may be inaccurate. "
            "Custom pricing for non-Copilot models can be added to data/custom-models-pricing.yml."
        ),
    }


# ─── Output shaping (detail levels) ───────────────────────────────────────────

DETAIL_LEVELS: tuple[str, ...] = ("minimal", "compact", "full")


def shape_session(data: dict, detail: str) -> dict:
    """Shape a single-session report to the requested detail level.

    - ``minimal``: identity, timing, and the ``total`` block only.
    - ``compact``: minimal + ``models`` list, ``fallback_pricing_models``, and
      ``pricing_note``. No per-model or per-subagent breakdown.
    - ``full``: everything, including ``model_breakdown`` and ``subagents``.
    """
    if detail == "full":
        return data

    shaped = {
        "session_id": data.get("session_id"),
        "title": data.get("title"),
        "started_at": data.get("started_at"),
        "ended_at": data.get("ended_at"),
        "duration_seconds": data.get("duration_seconds"),
        "active_duration_seconds": data.get("active_duration_seconds"),
        "models": data.get("models"),
        "total": data.get("total"),
    }
    if detail == "minimal":
        return shaped

    shaped["fallback_pricing_models"] = data.get("fallback_pricing_models", [])
    shaped["pricing_note"] = data.get("pricing_note")
    return shaped


def shape_batch(results: list[dict], detail: str) -> dict:
    """Aggregate multiple full session reports into {summary, sessions}.

    ``summary`` is always a pre-computed aggregate across every session so
    callers never need to iterate and sum themselves. ``sessions`` is the
    per-session array, each shaped by ``detail``.
    """
    total_input = total_output = total_cached = total_calls = 0
    total_usd = 0.0
    total_dur = total_active = 0
    cache_ratios: list[float] = []
    fallback_models: set[str] = set()
    sessions: list[dict] = []

    for r in results:
        t = r.get("total", {})
        total_input += t.get("input_tokens", 0)
        total_output += t.get("output_tokens", 0)
        total_cached += t.get("cached_tokens", 0)
        total_calls += t.get("llm_calls", 0)
        total_usd += t.get("estimated_usd", 0.0)
        total_dur += r.get("duration_seconds") or 0
        total_active += r.get("active_duration_seconds") or 0
        cache_ratios.append(t.get("cache_ratio", 0.0))
        fallback_models.update(r.get("fallback_pricing_models") or [])
        sessions.append(shape_session(r, detail))

    avg_cache = round(sum(cache_ratios) / len(cache_ratios), 3) if cache_ratios else 0.0

    return {
        "summary": {
            "session_count": len(results),
            "total_input_tokens": total_input,
            "total_output_tokens": total_output,
            "total_cached_tokens": total_cached,
            "total_llm_calls": total_calls,
            "total_estimated_usd": round(total_usd, 4),
            "avg_cache_ratio": avg_cache,
            "total_duration_seconds": total_dur,
            "total_active_duration_seconds": total_active,
            "fallback_pricing_models": sorted(fallback_models),
        },
        "sessions": sessions,
    }


def parse_since_to_ms(since: str) -> int | None:
    """Parse a date/datetime string to epoch milliseconds (UTC)."""
    for fmt in ("%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
        try:
            dt = datetime.strptime(since, fmt).replace(tzinfo=timezone.utc)
            return int(dt.timestamp() * 1000)
        except ValueError:
            continue
    return None


# ─── Rendering ─────────────────────────────────────────────────────────────────


def _col_width(header: str, values: list[str], cap: int | None = None, floor: int = 0) -> int:
    """Compute a column width that fits its widest value (and header), up to `cap`."""
    width = max([len(header), floor, *(len(v) for v in values)])
    return min(width, cap) if cap else width


def _render_columns(
    headers: tuple[str, ...],
    rows: Sequence[tuple[str, ...]],
    left_cols: set[int],
    indent: str = "  ",
    gutter: str = "  ",
) -> list[str]:
    """Render a small table with per-column widths computed from actual cell strings."""
    widths = [
        max(len(headers[i]), max((len(r[i]) for r in rows), default=0)) for i in range(len(headers))
    ]

    def _fmt_row(cells: tuple[str, ...]) -> str:
        parts = [
            cell.ljust(widths[i]) if i in left_cols else cell.rjust(widths[i])
            for i, cell in enumerate(cells)
        ]
        return indent + gutter.join(parts)

    lines = [_fmt_row(headers)]
    lines.append(indent + "-" * (sum(widths) + len(gutter) * (len(widths) - 1)))
    lines.extend(_fmt_row(r) for r in rows)
    return lines


def render_table_single(data: dict) -> str:
    """Render one session as a human-readable block, adapting to available fields."""
    lines: list[str] = []
    total = data.get("total") or {}
    usd = total.get("estimated_usd", 0)
    dur = data.get("duration_seconds")
    active = data.get("active_duration_seconds")
    dur_str = f"{dur}s" if dur is not None else "n/a"
    if active is not None and active != dur:
        dur_str += f"  (active: {active}s)"

    lines.append(f"Session:   {data.get('session_id')}")
    lines.append(f"Title:     {data.get('title') or '(unknown)'}")
    lines.append(f"Started:   {data.get('started_at')}")
    lines.append(f"Duration:  {dur_str}")
    if data.get("models") is not None:
        lines.append(f"Models:    {', '.join(data.get('models') or [])}")
    lines.append(f"Input:     {total.get('input_tokens', 0):,} tokens")
    lines.append(f"Output:    {total.get('output_tokens', 0):,} tokens")
    cache_pct = f"{total.get('cache_ratio', 0):.0%}"
    lines.append(f"Cached:    {total.get('cached_tokens', 0):,} ({cache_pct})")
    lines.append(f"LLM calls: {total.get('llm_calls', 0)}")
    lines.append(f"Est. cost: ${usd:.4f}")

    fallback = data.get("fallback_pricing_models")
    if fallback:
        lines.append(
            f"Warning:   fallback pricing used for {', '.join(fallback)} (may be inaccurate)"
        )

    model_breakdown = data.get("model_breakdown")
    if model_breakdown:
        headers = ("Model", "Input", "Cached", "Output", "Calls", "Cost")
        rows = [
            (
                m["model"],
                f"{m['input_tokens']:,}",
                f"{m['cached_tokens']:,}",
                f"{m['output_tokens']:,}",
                f"{m['llm_calls']:,}",
                f"${m['estimated_usd']:.2f}",
            )
            for m in model_breakdown
        ]
        lines.append("")
        lines.append("Per-Model Breakdown:")
        lines.extend(_render_columns(headers, rows, left_cols={0}))

    subs = data.get("subagents")
    if subs:
        headers = ("Name", "Model", "Input", "Cached", "Output", "Cost")
        rows = [
            (
                sub["name"],
                sub["model"],
                f"{sub['input_tokens']:,}",
                f"{sub['cached_tokens']:,}",
                f"{sub['output_tokens']:,}",
                f"${sub['estimated_usd']:.2f}",
            )
            for sub in subs
        ]
        lines.append("")
        lines.append("Subagents:")
        lines.extend(_render_columns(headers, rows, left_cols={0, 1}))

    return "\n".join(lines)


def render_table_list(items: list[dict], summary: dict | None = None) -> str:
    """Render a list of sessions as a table.

    Adapts to three shapes:

    - **Full detail**: each session rendered via ``render_table_single``.
    - **Analyzed, compact/minimal**: one row per session with a TOTAL footer.
    - **Metadata only** (from ``list``): one row per session.
    """
    if not items:
        return "(no sessions found)"

    if "model_breakdown" in items[0] or "subagents" in items[0]:
        return _render_full_detail_list(items, summary)

    if "total" in items[0]:
        return _render_analyzed_rows(items, summary)

    return _render_metadata_rows(items)


def _render_full_detail_list(items: list[dict], summary: dict | None) -> str:
    """Render each session in full, plus a footer."""
    blocks = [render_table_single(item) for item in items]
    divider = "\n\n" + "=" * 100 + "\n\n"
    text = divider.join(blocks)
    if summary is not None:
        text += divider + _render_summary_footer(summary)
    return text


def _render_summary_footer(summary: dict) -> str:
    """Render the batch ``summary`` aggregate as a short human-readable block."""
    lines = [f"Summary across {summary.get('session_count', 0)} sessions:"]
    lines.append(f"  Total input:   {summary.get('total_input_tokens', 0):,} tokens")
    lines.append(f"  Total output:  {summary.get('total_output_tokens', 0):,} tokens")
    lines.append(
        f"  Total cached:  {summary.get('total_cached_tokens', 0):,} tokens "
        f"(avg ratio {summary.get('avg_cache_ratio', 0):.0%})"
    )
    lines.append(f"  Total calls:   {summary.get('total_llm_calls', 0)}")
    lines.append(f"  Total cost:    ${summary.get('total_estimated_usd', 0):.4f}")
    fallback = summary.get("fallback_pricing_models")
    if fallback:
        lines.append(f"  Warning:       fallback pricing used for {', '.join(fallback)}")
    return "\n".join(lines)


def _render_analyzed_rows(items: list[dict], summary: dict | None = None) -> str:
    """One row per analyzed session."""
    rows = []
    for i, s in enumerate(items, 1):
        started = (s.get("started_at") or s.get("created_at") or "")[:16]
        title = s.get("title") or "(no title)"
        sid = s.get("session_id") or ""
        models = s.get("models") or []
        model = models[0] if models else "unknown"
        t = s.get("total", {})
        rows.append(
            (i, started, title, sid, model, t.get("input_tokens", 0), t.get("estimated_usd", 0))
        )

    w_title = _col_width("Title", [r[2] for r in rows], cap=60)
    w_id = _col_width("ID", [r[3] for r in rows])
    w_model = _col_width("Model", [r[4] for r in rows], cap=30)

    lines = [
        f"{'#':<3} {'Date':<16} {'Title':<{w_title}} {'ID':<{w_id}} "
        f"{'Model':<{w_model}} {'Input':>10} {'Cost':>8}"
    ]
    total_width = 3 + 1 + 16 + 1 + w_title + 1 + w_id + 1 + w_model + 1 + 10 + 1 + 8
    lines.append("-" * total_width)

    total_input = 0
    total_usd = 0.0
    for i, started, title, sid, model, inp, usd in rows:
        total_input += inp
        total_usd += usd
        lines.append(
            f"{i:<3} {started:<16} {title[:w_title]:<{w_title}} {sid:<{w_id}} "
            f"{model[:w_model]:<{w_model}} {inp:>10,} ${usd:>7.2f}"
        )

    if summary is not None:
        total_input = summary.get("total_input_tokens", total_input)
        total_usd = summary.get("total_estimated_usd", total_usd)
    lines.append("-" * total_width)
    lines.append(
        f"{'TOTAL':<3} {'':<16} {'':<{w_title}} {'':<{w_id}} {'':<{w_model}} "
        f"{total_input:>10,} ${total_usd:>7.2f}"
    )
    return "\n".join(lines)


def _render_metadata_rows(items: list[dict]) -> str:
    """One row per session with metadata only (from `list`)."""
    w_title = _col_width("Title", [s.get("title") or "(no title)" for s in items], cap=60)
    w_id = _col_width("ID", [s.get("session_id") or "" for s in items])

    lines = [f"{'Created':<19} {'Logs':<4} {'Title':<{w_title}}  {'ID':<{w_id}}"]
    lines.append("-" * (19 + 1 + 4 + 1 + w_title + 2 + w_id))
    for s in items:
        created = (s.get("created_at") or "")[:19]
        has_logs = "y" if s.get("has_debug_logs") else "n"
        title = (s.get("title") or "(no title)")[:w_title]
        lines.append(
            f"{created:<19} {has_logs:<4} {title:<{w_title}}  {s.get('session_id', ''):<{w_id}}"
        )
    return "\n".join(lines)


def render(payload: object, fmt: str) -> str:
    """Render a payload (single session, list, or batch) as text."""
    if fmt == "json":
        return json.dumps(payload, indent=2, ensure_ascii=False)
    if isinstance(payload, list):
        return render_table_list(payload)
    if isinstance(payload, dict) and "summary" in payload and "sessions" in payload:
        return render_table_list(payload["sessions"], summary=payload["summary"])
    return render_table_single(payload)  # type: ignore[arg-type]


def emit(payload: object, fmt: str, output_path: Path | None = None) -> None:
    """Render and print (or save to file) a payload."""
    text = render(payload, fmt)
    if output_path is not None:
        output_path.write_text(text, encoding="utf-8")
        click.echo(f"Saved {len(text):,} bytes to {output_path}")
    else:
        click.echo(text)


# ─── Shared CLI options ────────────────────────────────────────────────────────

FORMAT_CHOICE = click.Choice(("json", "table", "detailed"))
DETAIL_CHOICE = click.Choice(DETAIL_LEVELS)


def normalize_format(format_: str) -> str:
    """Map the CLI-facing --format value to the internal renderer format."""
    return "table" if format_ in ("table", "detailed") else "json"


def resolve_detail(detail: str, format_: str) -> str:
    """Force detail to 'full' when --format detailed is requested."""
    return "full" if format_ == "detailed" else detail


def detail_option(f: Any) -> Any:
    return click.option(
        "--detail",
        type=DETAIL_CHOICE,
        default="compact",
        show_default=True,
        help=(
            "minimal (identity+total only), compact (+models list, default), "
            "or full (+per-model and per-subagent breakdown). Ignored (forced "
            "to full) when --format detailed is used."
        ),
    )(f)


def format_option(f: Any) -> Any:
    return click.option(
        "--format",
        "format_",
        type=FORMAT_CHOICE,
        default="json",
        show_default=True,
        help=(
            "json (machine-readable), table (human-readable), or detailed "
            "(table forced to full detail — same as --format table --detail full)."
        ),
    )(f)


def output_option(f: Any) -> Any:
    return click.option(
        "--output",
        "output_path",
        metavar="PATH",
        help="Write output to PATH instead of stdout.",
    )(f)


def analysis_options(f: Any) -> Any:
    """Combine --detail, --format, --output for single/batch analysis commands."""
    f = output_option(f)
    f = format_option(f)
    f = detail_option(f)
    return f
