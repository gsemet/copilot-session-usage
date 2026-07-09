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
import hashlib
import json
import re
import urllib.error
import urllib.request
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


# ─── Pricing helpers ──────────────────────────────────────────────────────────


def _normalize_model_name(name: str) -> str:
    """Normalize a raw model name from the YAML to our internal key format.

    Strips footnote markers and release-status parentheticals such as
    ``(preview)``, but preserves functional variants like ``(fast mode)``
    so they remain distinct pricing entries.

    Examples:
        "GPT-5.4" → "gpt-5.4"
        "Claude Sonnet 4.6" → "claude-sonnet-4.6"
        "Claude Sonnet 5[^sonnet-5-promo]" → "claude-sonnet-5"
        "Claude Opus 4.8 (fast mode) (preview)" → "claude-opus-4.8-fast-mode"
    """
    cleaned = _clean_model_display_name(name)
    return re.sub(r"\s+", "-", cleaned.lower())


def _clean_model_display_name(name: str) -> str:
    """Return a presentable model name preserving original casing.

    Strips footnote markers and release-status parentheticals such as
    ``(preview)``, while keeping functional descriptors like ``(fast mode)``.

    Examples:
        "GPT-5.4" → "GPT-5.4"
        "Claude Sonnet 4.6" → "Claude Sonnet 4.6"
        "Claude Sonnet 5[^sonnet-5-promo]" → "Claude Sonnet 5"
        "Claude Opus 4.8 (fast mode) (preview)" → "Claude Opus 4.8 (fast mode)"
    """
    cleaned = re.sub(r"\[\^[^\]]+\]", "", name)
    # Strip release-status markers like (preview), (GA), etc., but keep
    # functional descriptors such as (fast mode).
    cleaned = re.sub(r"\s*\(\s*preview\s*\)", "", cleaned, flags=re.IGNORECASE)
    return cleaned.strip()


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
                "cache_write_per_m": _parse_price(entry.get("cache_write", "0")),
                "tier": entry.get("tier", "Default"),
                "threshold_tokens": None,
            }
            models[name] = [tier]
        return models if models else None
    except Exception:
        return None


def load_pricing(ref_dir: Path | None = None) -> dict:
    """Load pricing from models-and-pricing.yml, merge custom-models-pricing.yml.

    Raises:
        FileNotFoundError: If ``models-and-pricing.yml`` is missing or unreadable.
        ValueError: If the YAML cannot be parsed or has an unexpected shape.

    Args:
        ref_dir: Directory containing models-and-pricing.yml and
            custom-models-pricing.yml. If None, reads from the bundled data
            shipped with the package via importlib.resources.
    """
    text: str | None = None
    source = "bundled models-and-pricing.yml"
    if ref_dir is not None:
        yaml_path = ref_dir / "models-and-pricing.yml"
        if yaml_path.exists():
            text = yaml_path.read_text(encoding="utf-8")
            source = str(yaml_path)
        else:
            msg = f"pricing file not found: {yaml_path}"
            raise FileNotFoundError(msg)
    else:
        text = _read_data_file("models-and-pricing.yml")
        if text is None:
            msg = "bundled models-and-pricing.yml not found"
            raise FileNotFoundError(msg)

    try:
        from ruamel.yaml import YAML

        yaml = YAML(typ="safe")
        entries = yaml.load(text)
    except Exception as exc:
        msg = f"failed to parse {source}: {exc}"
        raise ValueError(msg) from exc

    if not isinstance(entries, list):
        msg = f"unexpected YAML structure in {source}: expected list, got {type(entries).__name__}"
        raise ValueError(msg)

    pricing = _build_pricing_from_yaml(entries, source)

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
        display_name = _clean_model_display_name(raw_name)
        tier = {
            "input_per_m": _parse_price(entry.get("input", "0")),
            "output_per_m": _parse_price(entry.get("output", "0")),
            "cache_per_m": _parse_price(entry.get("cached_input", "0")),
            "cache_write_per_m": _parse_price(entry.get("cache_write", "0")),
            "tier": entry.get("tier", "Default"),
            "threshold_tokens": _parse_threshold(entry.get("threshold", "")),
            "provider": entry.get("provider", "unknown"),
            "display_name": display_name,
        }
        models.setdefault(name, []).append(tier)

    for name, tiers in models.items():
        models[name] = sorted(
            tiers, key=lambda t: (t["threshold_tokens"] is None, t["threshold_tokens"] or 0)
        )

    if "default" not in models:
        models["default"] = [
            {
                "input_per_m": 0.30,
                "output_per_m": 1.50,
                "cache_per_m": 0.030,
                "cache_write_per_m": 0.0,
                "tier": "Default",
                "threshold_tokens": None,
                "provider": "unknown",
                "display_name": "unknown",
            }
        ]

    return {
        "_note": (
            "Per-token costs in USD per million tokens. Source: GitHub Copilot official pricing."
        ),
        "_source": source,
        "models": models,
    }


# ─── Pricing refresh ──────────────────────────────────────────────────────────

# URL for GitHub's canonical models-and-pricing YAML.
_PRICING_URL = (
    "https://raw.githubusercontent.com/github/docs/main/data/tables/copilot/models-and-pricing.yml"
)


def _write_data_file(name: str, content: str) -> Path:
    """Write a bundled data file in the package source tree.

    Returns the path written. Raises RuntimeError if the data directory
    cannot be found (e.g. the package is installed as a wheel).
    """
    try:
        from importlib.resources import files

        ref = files("copilot_session_usage.data") / name
        # In editable installs ref is a real Path; in wheels it may not be.
        path = Path(str(ref))
        if not path.parent.exists():
            msg = f"Data directory not found: {path.parent}"
            raise RuntimeError(msg)
        path.write_text(content, encoding="utf-8")
        return path
    except Exception as exc:
        msg = f"Cannot write bundled data file {name}: {exc}"
        raise RuntimeError(msg) from exc


def refresh_pricing() -> dict[str, Any]:
    """Fetch the latest pricing YAML from GitHub and update the bundled copy.

    Writes ``models-and-pricing.yml`` and ``models-and-pricing.lock``
    under ``src/copilot_session_usage/data/``.  Returns a dict with
    ``updated`` (bool), ``path`` (Path), ``model_count`` (int), and
    ``previous_count`` (int).

    Raises RuntimeError on network or write failures so callers can
    surface a clear message.
    """
    # Fetch upstream YAML
    try:
        with urllib.request.urlopen(_PRICING_URL, timeout=30) as response:  # noqa: S310
            yaml_text: str = response.read().decode("utf-8")
    except urllib.error.URLError as exc:
        msg = f"Failed to fetch pricing from {_PRICING_URL}: {exc}"
        raise RuntimeError(msg) from exc

    if not yaml_text.strip():
        msg = "No YAML input received from upstream. Check connectivity and re-run."
        raise RuntimeError(msg)

    # Parse to validate and count models
    try:
        from ruamel.yaml import YAML

        yaml = YAML(typ="safe")
        entries = yaml.load(yaml_text)
    except Exception as exc:
        msg = f"Failed to parse upstream YAML: {exc}"
        raise RuntimeError(msg) from exc

    if not isinstance(entries, list):
        msg = f"Unexpected YAML structure: expected list, got {type(entries).__name__}"
        raise RuntimeError(msg)

    model_count = sum(1 for e in entries if isinstance(e, dict) and e.get("model"))

    # Read current bundled file for comparison
    current_text = _read_data_file("models-and-pricing.yml")
    previous_count = 0
    if current_text:
        try:
            current_entries = yaml.load(current_text)
            if isinstance(current_entries, list):
                previous_count = sum(
                    1 for e in current_entries if isinstance(e, dict) and e.get("model")
                )
        except Exception:
            pass

    # Write the new YAML
    yaml_path = _write_data_file("models-and-pricing.yml", yaml_text)

    # Write lock file
    checksum = hashlib.sha256(yaml_text.encode("utf-8")).hexdigest()[:16]
    lock = {
        "_captured": datetime.now(timezone.utc).isoformat(),
        "_source": _PRICING_URL,
        "_yaml_path": str(yaml_path),
        "model_count": model_count,
        "checksum": checksum,
    }
    lock_path = _write_data_file("models-and-pricing.lock", json.dumps(lock, indent=2) + "\n")

    return {
        "updated": True,
        "path": yaml_path,
        "lock_path": lock_path,
        "model_count": model_count,
        "previous_count": previous_count,
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


def _model_provider(model: str, pricing: dict[str, Any]) -> str:
    """Return the provider name for a model from the pricing data.

    Falls back to the provider of the longest matching prefix key, then to
    ``"unknown"``. The returned value is the raw provider string from the
    YAML (e.g. ``openai``, ``anthropic``, ``moonshot_ai``).
    """
    models = pricing.get("models", {})
    tiers = models.get(model)
    if tiers is not None and tiers:
        return str(tiers[0].get("provider", "unknown"))

    best_key = ""
    best_tiers: list[dict] | None = None
    for key in models:
        if key == "default":
            continue
        if model.startswith(key) and len(key) > len(best_key):
            best_key = key
            best_tiers = models[key]

    if best_tiers:
        return str(best_tiers[0].get("provider", "unknown"))
    return "unknown"


# Human-readable provider names for the most common Copilot model vendors.
# Unknown providers fall back to the raw provider string from the YAML.
_PROVIDER_DISPLAY_NAMES: dict[str, str] = {
    "openai": "OpenAI",
    "anthropic": "Anthropic",
    "google": "Google",
    "microsoft": "Microsoft",
    "github": "GitHub",
    "moonshot_ai": "Moonshot AI",
}


def _format_millions(value: float, decimals: int = 2) -> str:
    """Format a token count as millions with at most ``decimals`` decimals.

    Examples (with the default 2 decimals):
        4_123_000   -> "4.12"
        1_213_000   -> "1.21"
        3_900_000   -> "3.9"
        0           -> "0"
    """
    millions = value / 1_000_000.0
    # Round to the requested decimals, then strip unnecessary trailing zeros.
    formatted = f"{millions:.{decimals}f}"
    if "." in formatted:
        formatted = formatted.rstrip("0").rstrip(".")
    return formatted or "0"


def _provider_display_name(provider: str) -> str:
    """Return a human-readable provider name, falling back to the raw key."""
    return _PROVIDER_DISPLAY_NAMES.get(provider, provider)


def _model_display_name(model: str, pricing: dict[str, Any]) -> str:
    """Return the canonical display name for a model from the pricing data.

    Falls back to the longest matching prefix key, then to the raw ``model``
    name (e.g. the value from the debug log) when no pricing entry exists.
    The returned name preserves the casing from the YAML, such as
    ``"Claude Sonnet 4.6"`` instead of ``"claude-sonnet-4.6"``.
    """
    models = pricing.get("models", {})
    tiers = models.get(model)
    if tiers is not None and tiers:
        display = tiers[0].get("display_name")
        if display:
            return str(display)

    best_key = ""
    best_tiers: list[dict] | None = None
    for key in models:
        if key == "default":
            continue
        if model.startswith(key) and len(key) > len(best_key):
            best_key = key
            best_tiers = models[key]

    if best_tiers:
        display = best_tiers[0].get("display_name")
        if display:
            return str(display)
    return model


def build_session_usage_acc_trailers(result: dict[str, Any], pricing: dict[str, Any]) -> list[str]:
    """Build ``Copilot-Session-Usage-Acc`` trailer lines from a session analysis.

    One line is emitted per model found in ``model_breakdown``. The model name
    is the raw name observed in the session logs; the vendor is derived from
    the bundled pricing data using both the internal normalized key and the
    original raw model name. Token counts are expressed in millions with two
    decimals; the estimated cost is appended as ``aic`` in AI credits
    (1 AIC = $0.01, so USD * 100).

    Format::

        Copilot-Session-Usage-Acc: <vendor>:<model-name>,in:4.12,out:1.21,cache:3.9,aic:42

    The model name keeps the casing from the bundled pricing YAML (for example
    ``"Claude Sonnet 4.6"``) rather than the lower-cased identifier used in
    the debug log.
    """
    trailers: list[str] = []
    for entry in result.get("model_breakdown", []):
        model = entry.get("model", "unknown")
        provider = _model_provider(model, pricing)
        if provider == "unknown":
            provider = _model_provider(_normalize_model_name(model), pricing)
        provider = _provider_display_name(provider)
        display_model = _model_display_name(model, pricing)
        input_m = _format_millions(entry.get("input_tokens", 0))
        output_m = _format_millions(entry.get("output_tokens", 0))
        cache_m = _format_millions(entry.get("cached_tokens", 0))
        aic = _format_aic(round(entry.get("estimated_usd", 0.0) * 100, 2))
        trailers.append(
            f"Copilot-Session-Usage-Acc: "
            f"{provider}:{display_model},in:{input_m},out:{output_m},cache:{cache_m},aic:{aic}"
        )
    return trailers


def _format_aic(value: float) -> str:
    """Format an AIC value with at most 2 decimals, dropping trailing zeros."""
    formatted = f"{value:.2f}"
    if "." in formatted:
        formatted = formatted.rstrip("0").rstrip(".")
    return formatted or "0"


def build_session_usage_aic_trailer(result: dict[str, Any]) -> str:
    """Build the ``Copilot-Session-Usage-AIC`` trailer with total AIC cost."""
    total_aic = round(result.get("total", {}).get("estimated_usd", 0.0) * 100, 2)
    return f"Copilot-Session-Usage-AIC: {_format_aic(total_aic)}"


def estimate_cost(
    input_tok: int, output_tok: int, cached_tok: int, model: str, pricing: dict[str, Any]
) -> float:
    """Compute estimated USD cost.

    Threshold-aware: the correct pricing tier is selected automatically based
    on ``input_tok`` so long-context requests use the higher rate.

    For models with a ``cache_write_per_m`` rate (Anthropic only), the
    incremental cache-creation cost is approximated as::

        fresh_input * (cache_write_per_m - input_per_m) / 1_000_000

    VS Code debug logs do not expose ``cacheCreationTokens`` directly; fresh
    input (``inputTokens - cachedTokens``) is used as a proxy.  For typical
    Anthropic sessions the full context prefix is cached, so this closely
    matches the billed amount.  Models without ``cache_write`` (OpenAI,
    Google) have ``cache_write_per_m == 0``, so the delta is zero for them.
    """
    rates = _get_model_rates(model, input_tok, pricing)
    billable_input = max(0, input_tok - cached_tok)
    cost = (
        billable_input * rates.get("input_per_m", 0.0) / 1_000_000
        + cached_tok * rates.get("cache_per_m", 0.0) / 1_000_000
        + output_tok * rates.get("output_per_m", 0.0) / 1_000_000
    )
    # Approximate incremental cache-creation cost for Anthropic models.
    # OTel DB (agent-traces.db) has the exact field but is not always present
    # and VS Code does not yet populate it; this proxy is accurate when the
    # full context prefix is cached, which is the common case.
    cache_write_per_m = rates.get("cache_write_per_m", 0.0)
    input_per_m = rates.get("input_per_m", 0.0)
    if cache_write_per_m > input_per_m:
        cost += billable_input * (cache_write_per_m - input_per_m) / 1_000_000
    return cost  # type: ignore[no-any-return]


def estimate_cost_for_file(per_model: dict[str, dict[str, int]], pricing: dict[str, Any]) -> float:
    """Sum costs per-model bucket.

    Prefers ``copilotUsageNanoAiu`` (VS Code's own billing figure, converted
    from nano-AIC to USD) when the field is populated.  Falls back to
    ``estimate_cost`` (token-based) for models that do not report it (e.g.
    Kimi, older VS Code versions).
    """
    total = 0.0
    for model, v in per_model.items():
        nano = v.get("nano_aiu", 0)
        if nano:
            # 1 nanoAiu = 1e-9 AIC = 1e-11 USD
            total += nano / 1e11
        else:
            total += estimate_cost(v["input"], v["output"], v["cached"], model, pricing)
    return total


def _dominant_model(per_model: dict[str, dict]) -> str:
    """Return the model with the most input tokens (representative label only)."""
    if not per_model:
        return "unknown"
    return max(per_model, key=lambda m: per_model[m]["input"])


# ─── JSONL parsing ────────────────────────────────────────────────────────────


def parse_jsonl_file(path: Path, skill_timeline: list[tuple[int, str]] | None = None) -> dict:
    """Parse a single .jsonl file and return aggregated token stats.

    Only ``llm_request`` events carry token data — every other event type
    is ignored for cost purposes, though non-LLM timestamps still count
    toward wall-clock ``first_ts``/``last_ts``.

    When ``skill_timeline`` is provided, each ``llm_request`` is attributed
    to the most recently invoked skill at that timestamp.
    """
    stats: dict = {
        "file": path.name,
        "input_tokens": 0,
        "output_tokens": 0,
        "cached_tokens": 0,
        "llm_calls": 0,
        "per_model": {},
        "per_skill": {},
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
                        model, {"input": 0, "output": 0, "cached": 0, "calls": 0, "nano_aiu": 0}
                    )
                    bucket["input"] += inp
                    bucket["output"] += out
                    bucket["cached"] += cch
                    bucket["calls"] += 1
                    bucket["nano_aiu"] += attrs.get("copilotUsageNanoAiu") or 0

                    if skill_timeline and ts is not None:
                        skill = active_skill_at_ts(ts, skill_timeline) or "unknown"
                    else:
                        skill = "unknown"
                    skill_bucket = stats["per_skill"].setdefault(
                        skill, {"input": 0, "output": 0, "cached": 0, "calls": 0, "per_model": {}}
                    )
                    skill_bucket["input"] += inp
                    skill_bucket["output"] += out
                    skill_bucket["cached"] += cch
                    skill_bucket["calls"] += 1
                    skill_model_bucket = skill_bucket["per_model"].setdefault(
                        model, {"input": 0, "output": 0, "cached": 0, "calls": 0}
                    )
                    skill_model_bucket["input"] += inp
                    skill_model_bucket["output"] += out
                    skill_model_bucket["cached"] += cch
                    skill_model_bucket["calls"] += 1

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


# ─── Skill detection and attribution ──────────────────────────────────────────


def _extract_slash_command_skill(content: str) -> str | None:
    """Extract a skill name from a slash-command user message.

    Supports both ``/skill`` and ``/namespace skill-name`` forms.

    Examples:
        "/compendium-generic get-session-costs" → "/compendium-generic get-session-costs"
        "/deploy" → "/deploy"
    """
    content = content.strip()
    if not content.startswith("/"):
        return None
    # Capture the first two whitespace-separated tokens after the leading slash.
    match = re.match(r"/([^\s]+)(?:\s+([^\s]+))?(?:\s+.*)?$", content)
    if not match:
        return None
    namespace = match.group(1)
    sub = match.group(2)
    if sub:
        return f"/{namespace} {sub}"
    return f"/{namespace}"


def _normalize_skill_name(name: str) -> str:
    """Normalize a skill name for matching.

    Maps colon-separated forms (``/namespace:skill``) to the slash-command
    form (``/namespace skill``) so the same skill invoked different ways
    is attributed consistently.
    """
    if name.startswith("/") and ":" in name.split()[0]:
        parts = name[1:].split(":", 1)
        return f"/{parts[0]} {parts[1]}".strip()
    return name


def _extract_skills_from_discovery(details: str) -> list[str]:
    """Extract skill names from a Skill Discovery ``details`` string.

    Pattern: ``loaded: [skill1, skill2, ...]``
    """
    match = re.search(r"loaded:\s*\[([^\]]+)\]", details)
    if not match:
        return []
    items = match.group(1).split(",")
    return [item.strip().strip("'\"") for item in items if item.strip()]


def _extract_skills_from_generic_details(details: str) -> list[str]:
    """Extract skill names from a Custom Instructions generic event details string.

    Pattern: ``skills: [N] skill1, skill2, ...`` followed by ``agents:`` or end.
    """
    match = re.search(r"skills:\s*\[[^\]]+\]\s+(.+?)(?:\n\s*\w+:|$)", details, re.DOTALL)
    if not match:
        return []
    items = match.group(1).split(",")
    return [item.strip().strip("'\"") for item in items if item.strip()]


def detect_session_skills(session_dir: Path) -> dict[str, list[str]]:
    """Detect skills available in a session from multiple sources.

    Sources (in order of preference):
    - ``user_message`` events containing slash commands
    - ``discovery`` events of type ``Skill Discovery``
    - ``generic`` events named ``Custom Instructions`` with on-demand skill lists
    """
    detected: set[str] = set()
    main = session_dir / "main.jsonl"
    if main.exists():
        try:
            with main.open(encoding="utf-8") as f:
                for raw in f:
                    line = raw.strip()
                    if not line:
                        continue
                    try:
                        obj = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    event_type = obj.get("type")
                    name = obj.get("name", "")
                    attrs = obj.get("attrs", {})
                    if event_type == "user_message":
                        skill = _extract_slash_command_skill(attrs.get("content", ""))
                        if skill:
                            detected.add(_normalize_skill_name(skill))
                    elif event_type == "discovery" and name == "Skill Discovery":
                        details = attrs.get("details", "")
                        discovered = _extract_skills_from_discovery(details)
                        detected.update(_normalize_skill_name(s) for s in discovered)
                    elif event_type == "generic" and "Custom Instructions" in name:
                        details = attrs.get("details", "")
                        discovered = _extract_skills_from_generic_details(details)
                        detected.update(_normalize_skill_name(s) for s in discovered)
        except OSError:
            pass
    return {"detected": sorted(detected)}


def build_skill_timeline(session_dir: Path) -> list[tuple[int, str]]:
    """Build a chronological timeline of skill invocations from user messages.

    Each entry is ``(timestamp_ms, skill_name)``. The active skill at any
    later timestamp is the most recent entry whose timestamp is <= that timestamp.
    """
    timeline: list[tuple[int, str]] = []
    main = session_dir / "main.jsonl"
    if not main.exists():
        return timeline
    try:
        with main.open(encoding="utf-8") as f:
            for raw in f:
                line = raw.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if obj.get("type") == "user_message":
                    skill = _extract_slash_command_skill(obj.get("attrs", {}).get("content", ""))
                    if skill:
                        timeline.append((obj.get("ts", 0), _normalize_skill_name(skill)))
    except OSError:
        pass
    timeline.sort(key=lambda x: x[0])
    return timeline


def active_skill_at_ts(ts: int | None, timeline: list[tuple[int, str]]) -> str | None:
    """Return the most recently invoked skill at or before ``ts``.

    Returns ``None`` if ``ts`` is None or no skill was invoked before it.
    """
    if ts is None or not timeline:
        return None
    active: str | None = None
    for t, skill in timeline:
        if t <= ts:
            active = skill
        else:
            break
    return active


def parse_tool_calls(
    session_dir: Path, skill_timeline: list[tuple[int, str]] | None = None
) -> list[dict]:
    """Parse all tool_call events across JSONL files and attribute them to skills.

    Each returned dict contains ``tool``, ``skill``, ``subagent``, and ``ts``.
    """
    calls: list[dict] = []
    subagent_names = get_subagent_names(session_dir / "main.jsonl")
    for jsonl_file in sorted(session_dir.glob("*.jsonl")):
        subagent_name, _ = _resolve_subagent_name(jsonl_file.name, subagent_names)
        try:
            with jsonl_file.open(encoding="utf-8") as f:
                for raw in f:
                    line = raw.strip()
                    if not line:
                        continue
                    try:
                        obj = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if obj.get("type") == "tool_call":
                        ts: int | None = obj.get("ts")
                        skill = active_skill_at_ts(ts, skill_timeline) if skill_timeline else None
                        calls.append(
                            {
                                "tool": obj.get("name", "unknown"),
                                "skill": skill or "unknown",
                                "subagent": subagent_name,
                                "ts": ts,
                            }
                        )
        except OSError:
            pass
    return calls


def aggregate_tool_calls(calls: list[dict]) -> list[dict]:
    """Aggregate tool_call events into per-tool/per-skill/per-subagent counts."""
    counts: dict[tuple[str, str, str], int] = {}
    for call in calls:
        key = (call["tool"], call["skill"], call["subagent"])
        counts[key] = counts.get(key, 0) + 1

    rows: list[dict] = [
        {
            "tool": tool,
            "calls": calls_count,
            "skill": skill,
            "subagent": subagent,
        }
        for (tool, skill, subagent), calls_count in counts.items()
    ]
    rows.sort(key=lambda x: (-x["calls"], x["tool"], x["skill"], x["subagent"]))
    return rows


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

    Also detects invoked skills from user messages and attributes LLM calls
    and tool calls to the active skill.
    """
    session_dir = Path(session_dir)
    session_id = session_dir.name
    subagent_names = get_subagent_names(session_dir / "main.jsonl")
    skill_timeline = build_skill_timeline(session_dir)
    detected_skills = detect_session_skills(session_dir)

    file_results: list[dict] = []
    global_first_ts: int | None = None
    global_last_ts: int | None = None
    all_models: set[str] = set()

    for jsonl_file in sorted(session_dir.glob("*.jsonl")):
        stats = parse_jsonl_file(jsonl_file, skill_timeline)
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
                global_per_model[model] = {
                    "input": 0,
                    "output": 0,
                    "cached": 0,
                    "calls": 0,
                    "nano_aiu": 0,
                }
            global_per_model[model]["input"] += tokens["input"]
            global_per_model[model]["output"] += tokens["output"]
            global_per_model[model]["cached"] += tokens["cached"]
            global_per_model[model]["calls"] += tokens["calls"]
            global_per_model[model]["nano_aiu"] += tokens.get("nano_aiu", 0)

    global_per_skill: dict[str, dict] = {}
    for stats in file_results:
        for skill, tokens in stats.get("per_skill", {}).items():
            if skill not in global_per_skill:
                global_per_skill[skill] = {
                    "input": 0,
                    "output": 0,
                    "cached": 0,
                    "calls": 0,
                    "per_model": {},
                }
            global_per_skill[skill]["input"] += tokens["input"]
            global_per_skill[skill]["output"] += tokens["output"]
            global_per_skill[skill]["cached"] += tokens["cached"]
            global_per_skill[skill]["calls"] += tokens["calls"]
            for model, mtokens in tokens.get("per_model", {}).items():
                skill_model = global_per_skill[skill]["per_model"].setdefault(
                    model, {"input": 0, "output": 0, "cached": 0, "calls": 0}
                )
                skill_model["input"] += mtokens["input"]
                skill_model["output"] += mtokens["output"]
                skill_model["cached"] += mtokens["cached"]
                skill_model["calls"] += mtokens["calls"]

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
                "estimated_usd": round(estimate_cost_for_file({model: v}, pricing), 6),
            }
            for model, v in global_per_model.items()
        ],
        key=lambda x: x["estimated_usd"],
        reverse=True,
    )

    fallback_pricing_models = sorted(
        model for model in global_per_model if model_uses_fallback_pricing(model, pricing)
    )

    skill_breakdown = sorted(
        [
            {
                "skill": skill,
                "input_tokens": v["input"],
                "output_tokens": v["output"],
                "cached_tokens": v["cached"],
                "llm_calls": v["calls"],
                "estimated_usd": round(
                    estimate_cost_for_file(v.get("per_model", {}), pricing),
                    6,
                ),
            }
            for skill, v in global_per_skill.items()
        ],
        key=lambda x: x["estimated_usd"],
        reverse=True,
    )

    tool_calls = parse_tool_calls(session_dir, skill_timeline)
    tool_breakdown = aggregate_tool_calls(tool_calls)

    active_skill = skill_timeline[-1][1] if skill_timeline else None

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
        "skills": {
            "detected": detected_skills["detected"],
            "active": active_skill,
            "breakdown": skill_breakdown,
            "tool_breakdown": tool_breakdown,
        },
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
    shaped["skills"] = data.get("skills", {})
    return shaped


def shape_session_skill_breakdown(data: dict) -> dict:
    """Shape a session report to only its per-skill cost breakdown."""
    return {
        "session_id": data.get("session_id"),
        "title": data.get("title"),
        "skill_breakdown": data.get("skills", {}).get("breakdown", []),
    }


def shape_session_tool_breakdown(data: dict) -> dict:
    """Shape a session report to only its per-skill/per-subagent tool breakdown."""
    return {
        "session_id": data.get("session_id"),
        "title": data.get("title"),
        "tool_breakdown": data.get("skills", {}).get("tool_breakdown", []),
    }


def shape_session_minimal_skill(data: dict, skill_name: str) -> dict | None:
    """Return a minimal, stable JSON object for a single skill's cost.

    Returns ``None`` if the skill is not present in the session.
    """
    for skill in data.get("skills", {}).get("breakdown", []):
        if skill["skill"] == skill_name:
            return {
                "skill": skill_name,
                "cost_usd": skill["estimated_usd"],
                "input_tokens": skill["input_tokens"],
                "output_tokens": skill["output_tokens"],
                "cached_tokens": skill["cached_tokens"],
                "llm_calls": skill["llm_calls"],
            }
    return None


def parse_last_window_to_ms(window: str) -> int | None:
    """Parse a relative duration like ``7d``, ``24h``, ``30m`` to epoch ms.

    Returns the timestamp ``window`` ago from now (UTC).
    """
    match = re.match(r"^(\d+)\s*([dhm])$", window.strip().lower())
    if not match:
        return None
    value = int(match.group(1))
    unit = match.group(2)
    delta_s = {"d": 86_400, "h": 3_600, "m": 60}.get(unit, 0) * value
    return int((datetime.now(timezone.utc).timestamp() - delta_s) * 1000)


def aggregate_skills(results: list[dict]) -> dict:
    """Aggregate per-skill breakdowns across multiple sessions.

    Returns a dict with ``skills`` (list of per-skill aggregates) and
    ``session_count``.
    """
    per_skill: dict[str, dict] = {}
    for r in results:
        for skill in r.get("skills", {}).get("breakdown", []):
            name = skill["skill"]
            if name not in per_skill:
                per_skill[name] = {
                    "skill": name,
                    "sessions": 0,
                    "input_tokens": 0,
                    "output_tokens": 0,
                    "cached_tokens": 0,
                    "llm_calls": 0,
                    "estimated_usd": 0.0,
                }
            bucket = per_skill[name]
            bucket["sessions"] += 1
            bucket["input_tokens"] += skill.get("input_tokens", 0)
            bucket["output_tokens"] += skill.get("output_tokens", 0)
            bucket["cached_tokens"] += skill.get("cached_tokens", 0)
            bucket["llm_calls"] += skill.get("llm_calls", 0)
            bucket["estimated_usd"] += skill.get("estimated_usd", 0.0)

    skills = sorted(
        [
            {
                "skill": v["skill"],
                "sessions": v["sessions"],
                "input_tokens": v["input_tokens"],
                "output_tokens": v["output_tokens"],
                "cached_tokens": v["cached_tokens"],
                "llm_calls": v["llm_calls"],
                "estimated_usd": round(v["estimated_usd"], 4),
            }
            for v in per_skill.values()
        ],
        key=lambda x: x["estimated_usd"],
        reverse=True,
    )
    return {"session_count": len(results), "skills": skills}


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
    """Parse a date/datetime string to epoch milliseconds (UTC).

    Accepts ISO 8601 with timezone offsets (e.g. ``2026-07-01T00:00:00Z`` or
    ``2026-07-01T02:00:00+02:00``) as well as the legacy formats
    ``YYYY-MM-DDTHH:MM:SS`` and ``YYYY-MM-DD``.
    """
    since = since.strip()
    if since.endswith("Z"):
        since = since[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(since)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return int(dt.timestamp() * 1000)
    except ValueError:
        pass
    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
        try:
            dt = datetime.strptime(since, fmt).replace(tzinfo=timezone.utc)
            return int(dt.timestamp() * 1000)
        except ValueError:
            continue
    return None


def filter_sessions_by_name(sessions: list[dict], pattern: str) -> list[dict]:
    """Return sessions whose title or session_id matches the regex pattern."""
    try:
        regex = re.compile(pattern, re.IGNORECASE)
    except re.error as exc:
        msg = f"Invalid name regex: {exc}"
        raise ValueError(msg) from exc
    return [
        s
        for s in sessions
        if regex.search(s.get("title") or "") or regex.search(s.get("session_id") or "")
    ]


def compute_efficiency_summary(result: dict) -> dict:
    """Compute a cost-efficiency summary for a single analyzed session."""
    total = result.get("total", {})
    input_tokens = total.get("input_tokens", 0)
    output_tokens = total.get("output_tokens", 0)
    cached_tokens = total.get("cached_tokens", 0)
    total_tokens = input_tokens + output_tokens + cached_tokens
    estimated_usd = total.get("estimated_usd", 0.0)

    summary: dict = {
        "session_id": result.get("session_id"),
        "title": result.get("title"),
        "cache_ratio": total.get("cache_ratio", 0.0),
        "total_input_tokens": input_tokens,
        "total_output_tokens": output_tokens,
        "total_cached_tokens": cached_tokens,
        "total_tokens": total_tokens,
        "llm_calls": total.get("llm_calls", 0),
        "estimated_usd": estimated_usd,
        "cost_per_1m_tokens": (
            round(estimated_usd / (total_tokens / 1_000_000), 4) if total_tokens > 0 else 0.0
        ),
        "model_split": [],
    }

    model_breakdown = result.get("model_breakdown", [])
    total_input_for_split = sum(m.get("input_tokens", 0) for m in model_breakdown)
    for m in sorted(model_breakdown, key=lambda x: x.get("estimated_usd", 0.0), reverse=True):
        model_input = m.get("input_tokens", 0)
        split_ratio = (
            round(model_input / total_input_for_split, 3) if total_input_for_split > 0 else 0.0
        )
        summary["model_split"].append(
            {
                "model": m["model"],
                "input_tokens": model_input,
                "output_tokens": m.get("output_tokens", 0),
                "cached_tokens": m.get("cached_tokens", 0),
                "llm_calls": m.get("llm_calls", 0),
                "estimated_usd": m.get("estimated_usd", 0.0),
                "split_ratio": split_ratio,
                "cost_per_1m_input_tokens": (
                    round(m.get("estimated_usd", 0.0) / (model_input / 1_000_000), 4)
                    if model_input > 0
                    else 0.0
                ),
            }
        )

    return summary


def merge_session_results(results: list[dict]) -> dict:
    """Merge multiple raw session analyses into one result-shaped dict.

    Totals and per-model breakdowns are summed across sessions. The returned
    dict has the same ``total`` / ``model_breakdown`` structure produced by
    ``analyze_session``, so it can be passed directly to the trailer builders.
    """
    if not results:
        return {"total": {}, "model_breakdown": []}

    total_input = total_output = total_cached = total_calls = 0
    total_usd = 0.0
    per_model: dict[str, dict] = {}

    for r in results:
        t = r.get("total", {})
        total_input += t.get("input_tokens", 0)
        total_output += t.get("output_tokens", 0)
        total_cached += t.get("cached_tokens", 0)
        total_calls += t.get("llm_calls", 0)
        total_usd += t.get("estimated_usd", 0.0)

        for m in r.get("model_breakdown", []):
            model = m["model"]
            if model not in per_model:
                per_model[model] = {
                    "model": model,
                    "input_tokens": 0,
                    "output_tokens": 0,
                    "cached_tokens": 0,
                    "llm_calls": 0,
                    "estimated_usd": 0.0,
                }
            per_model[model]["input_tokens"] += m.get("input_tokens", 0)
            per_model[model]["output_tokens"] += m.get("output_tokens", 0)
            per_model[model]["cached_tokens"] += m.get("cached_tokens", 0)
            per_model[model]["llm_calls"] += m.get("llm_calls", 0)
            per_model[model]["estimated_usd"] += m.get("estimated_usd", 0.0)

    cache_ratio = round(total_cached / total_input, 3) if total_input > 0 else 0.0
    model_breakdown = sorted(
        per_model.values(),
        key=lambda x: x["estimated_usd"],
        reverse=True,
    )

    return {
        "total": {
            "input_tokens": total_input,
            "output_tokens": total_output,
            "cached_tokens": total_cached,
            "llm_calls": total_calls,
            "estimated_usd": round(total_usd, 4),
            "cache_ratio": cache_ratio,
        },
        "model_breakdown": model_breakdown,
    }


def aggregate_sessions(results: list[dict]) -> dict:
    """Aggregate multiple session analyses into a single efficiency summary."""
    total_input = total_output = total_cached = total_calls = 0
    total_usd = 0.0
    total_dur = total_active = 0
    cache_ratios: list[float] = []
    fallback_models: set[str] = set()
    per_model_input: dict[str, int] = {}
    per_model_output: dict[str, int] = {}
    per_model_cached: dict[str, int] = {}
    per_model_calls: dict[str, int] = {}
    per_model_usd: dict[str, float] = {}

    for r in results:
        t = r.get("total", {})
        inp = t.get("input_tokens", 0)
        out = t.get("output_tokens", 0)
        cch = t.get("cached_tokens", 0)
        calls = t.get("llm_calls", 0)
        usd = t.get("estimated_usd", 0.0)

        total_input += inp
        total_output += out
        total_cached += cch
        total_calls += calls
        total_usd += usd
        total_dur += r.get("duration_seconds") or 0
        total_active += r.get("active_duration_seconds") or 0
        cache_ratios.append(t.get("cache_ratio", 0.0))
        fallback_models.update(r.get("fallback_pricing_models") or [])

        for m in r.get("model_breakdown", []):
            model = m["model"]
            per_model_input[model] = per_model_input.get(model, 0) + m.get("input_tokens", 0)
            per_model_output[model] = per_model_output.get(model, 0) + m.get("output_tokens", 0)
            per_model_cached[model] = per_model_cached.get(model, 0) + m.get("cached_tokens", 0)
            per_model_calls[model] = per_model_calls.get(model, 0) + m.get("llm_calls", 0)
            per_model_usd[model] = per_model_usd.get(model, 0.0) + m.get("estimated_usd", 0.0)

    total_tokens = total_input + total_output + total_cached
    avg_cache = round(sum(cache_ratios) / len(cache_ratios), 3) if cache_ratios else 0.0

    model_split = []
    for model in sorted(per_model_usd.keys(), key=lambda m: per_model_usd[m], reverse=True):
        inp = per_model_input[model]
        model_split.append(
            {
                "model": model,
                "input_tokens": inp,
                "output_tokens": per_model_output[model],
                "cached_tokens": per_model_cached[model],
                "llm_calls": per_model_calls[model],
                "estimated_usd": round(per_model_usd[model], 4),
                "split_ratio": round(inp / total_input, 3) if total_input > 0 else 0.0,
                "cost_per_1m_input_tokens": (
                    round(per_model_usd[model] / (inp / 1_000_000), 4) if inp > 0 else 0.0
                ),
            }
        )

    return {
        "session_count": len(results),
        "total_input_tokens": total_input,
        "total_output_tokens": total_output,
        "total_cached_tokens": total_cached,
        "total_tokens": total_tokens,
        "total_llm_calls": total_calls,
        "total_estimated_usd": round(total_usd, 4),
        "avg_cache_ratio": avg_cache,
        "cache_ratio": avg_cache,
        "cost_per_1m_tokens": (
            round(total_usd / (total_tokens / 1_000_000), 4) if total_tokens > 0 else 0.0
        ),
        "total_duration_seconds": total_dur,
        "total_active_duration_seconds": total_active,
        "fallback_pricing_models": sorted(fallback_models),
        "model_split": model_split,
    }


def query_json_path(data: dict, path: str) -> Any:
    """Extract a value from nested dicts/lists using a simple dot path.

    Supported syntax:

        .key.subkey       -> data["key"]["subkey"]
        .key[0]           -> data["key"][0]
        .key[*]           -> data["key"] (returns the whole list)
    """
    if path.startswith("."):
        path = path[1:]
    if not path:
        return data

    current: Any = data
    for part in path.split("."):
        array_match = re.match(r"^(.+)\[(\d+|\*)\]$", part)
        if array_match:
            key, idx = array_match.groups()
            if not isinstance(current, dict) or key not in current:
                return None
            current = current[key]
            if idx == "*":
                if not isinstance(current, list):
                    return None
                return current
            index = int(idx)
            if not isinstance(current, list) or index >= len(current):
                return None
            current = current[index]
        else:
            if not isinstance(current, dict) or part not in current:
                return None
            current = current[part]
    return current


def get_queryable_fields() -> dict[str, str]:
    """Return a reference of fields usable with --query."""
    return {
        "session_id": "Session UUID (string)",
        "title": "Session title, if known (string)",
        "started_at": "ISO 8601 start timestamp (string)",
        "ended_at": "ISO 8601 end timestamp (string)",
        "duration_seconds": "Wall-clock duration in seconds (number)",
        "active_duration_seconds": "Duration covered by LLM calls in seconds (number)",
        "models": "List of model names used (list[string])",
        "fallback_pricing_models": "Models priced with the generic default rate (list[string])",
        "total.input_tokens": "Total input tokens (number)",
        "total.output_tokens": "Total output tokens (number)",
        "total.cached_tokens": "Total cached tokens (number)",
        "total.llm_calls": "Total LLM calls (number)",
        "total.estimated_usd": "Estimated USD cost (number)",
        "total.cache_ratio": "Cached tokens / input tokens (number)",
        "model_breakdown": "Per-model token/cost breakdown (list[dict])",
        "model_breakdown[0].model": "Model name in first breakdown row (string)",
        "model_breakdown[0].input_tokens": "Input tokens for first model (number)",
        "model_breakdown[0].estimated_usd": "Estimated USD for first model (number)",
        "subagents": "Per-subagent/file attribution (list[dict])",
        "subagents[0].name": "Subagent name in first row (string)",
        "subagents[0].estimated_usd": "Estimated USD for first subagent (number)",
        "skills.detected": "Skills detected in the session (list[string])",
        "skills.active": "Most recently invoked skill (string)",
        "skills.breakdown": "Per-skill token/cost breakdown (list[dict])",
        "skills.breakdown[0].skill": "Skill name in first breakdown row (string)",
        "skills.breakdown[0].estimated_usd": "Estimated USD for first skill (number)",
        "skills.tool_breakdown": "Per-skill/per-subagent tool-call counts (list[dict])",
    }


def list_session_dirs(debug_logs_dir: Path) -> list[dict]:
    """List session directories under a debug-logs folder.

    Returns metadata dicts with session_id, title (fallback to session_id),
    debug_log_dir, and has_debug_logs.
    """
    debug_logs_dir = Path(debug_logs_dir)
    sessions: list[dict] = []
    if not debug_logs_dir.is_dir():
        return sessions
    for session_dir in sorted(debug_logs_dir.iterdir()):
        if not session_dir.is_dir():
            continue
        if not any(session_dir.glob("*.jsonl")):
            continue
        sessions.append(
            {
                "session_id": session_dir.name,
                "title": session_dir.name,
                "workspace_folder": "",
                "workspace_hash": "",
                "created_ms": None,
                "last_message_ms": None,
                "has_debug_logs": True,
                "debug_log_dir": str(session_dir),
            }
        )
    return sessions


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
        max(len(headers[i]), max((len(r[i] or "") for r in rows), default=0))
        for i in range(len(headers))
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


def render_skill_breakdown(data: dict) -> str:
    """Render a per-skill cost breakdown table."""
    breakdown = data.get("skill_breakdown") or data.get("skills", {}).get("breakdown", [])
    if not breakdown:
        return "No skill breakdown available."
    headers = ("Skill", "Input", "Cached", "Output", "Calls", "Cost")
    rows = [
        (
            s["skill"],
            f"{s['input_tokens']:,}",
            f"{s['cached_tokens']:,}",
            f"{s['output_tokens']:,}",
            f"{s['llm_calls']:,}",
            f"${s['estimated_usd']:.4f}",
        )
        for s in breakdown
    ]
    lines = ["Per-Skill Breakdown:"]
    lines.extend(_render_columns(headers, rows, left_cols={0}))
    return "\n".join(lines)


def render_skills_aggregate(data: dict) -> str:
    """Render the skills aggregate as a markdown table."""
    skills = data.get("skills", [])
    if not skills:
        return "No skills found."
    headers = ("Skill", "Sessions", "Input", "Output", "Cached", "Calls", "Cost")
    rows = [
        (
            s["skill"],
            f"{s['sessions']:,}",
            f"{s['input_tokens']:,}",
            f"{s['output_tokens']:,}",
            f"{s['cached_tokens']:,}",
            f"{s['llm_calls']:,}",
            f"${s['estimated_usd']:.4f}",
        )
        for s in skills
    ]
    lines = [f"Skills across {data.get('session_count', 0)} sessions:"]
    lines.extend(_render_columns(headers, rows, left_cols={0}))
    return "\n".join(lines)


def render_tool_breakdown(data: dict) -> str:
    """Render a per-tool/per-skill/per-subagent call-count table."""
    breakdown = data.get("tool_breakdown") or data.get("skills", {}).get("tool_breakdown", [])
    if not breakdown:
        return "No tool breakdown available."
    headers = ("Tool", "Calls", "Skill", "Subagent")
    rows = [
        (
            t["tool"],
            f"{t['calls']:,}",
            t["skill"],
            t["subagent"],
        )
        for t in breakdown
    ]
    lines = ["Tool Breakdown:"]
    lines.extend(_render_columns(headers, rows, left_cols={0, 2, 3}))
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


def render_summary(data: dict) -> str:
    """Render a single-session efficiency summary as a human-readable block."""
    lines = [
        f"Session:   {data.get('session_id') or '(unknown)'}",
        f"Title:     {data.get('title') or '(unknown)'}",
        f"Cache ratio: {data.get('cache_ratio', 0):.0%}",
        f"Total tokens: {data.get('total_tokens', 0):,}",
        f"Input tokens: {data.get('total_input_tokens', 0):,}",
        f"Output tokens: {data.get('total_output_tokens', 0):,}",
        f"Cached tokens: {data.get('total_cached_tokens', 0):,}",
        f"LLM calls: {data.get('llm_calls', 0)}",
        f"Est. cost: ${data.get('estimated_usd', 0):.4f}",
        f"Cost per 1M tokens: ${data.get('cost_per_1m_tokens', 0):.4f}",
    ]
    model_split = data.get("model_split", [])
    if model_split:
        lines.append("")
        lines.append("Model split:")
        headers = ("Model", "Input", "Split", "Cost", "$/1M input")
        rows = [
            (
                m["model"],
                f"{m['input_tokens']:,}",
                f"{m['split_ratio']:.0%}",
                f"${m['estimated_usd']:.2f}",
                f"${m['cost_per_1m_input_tokens']:.2f}",
            )
            for m in model_split
        ]
        lines.extend(_render_columns(headers, rows, left_cols={0}))
    return "\n".join(lines)


def render_aggregate(data: dict) -> str:
    """Render an aggregate summary across sessions as a human-readable block."""
    lines = [
        f"Aggregate across {data.get('session_count', 0)} sessions",
        f"Total tokens: {data.get('total_tokens', 0):,}",
        f"Input tokens: {data.get('total_input_tokens', 0):,}",
        f"Output tokens: {data.get('total_output_tokens', 0):,}",
        f"Cached tokens: {data.get('total_cached_tokens', 0):,} "
        f"(avg ratio {data.get('avg_cache_ratio', 0):.0%})",
        f"LLM calls: {data.get('total_llm_calls', 0)}",
        f"Est. cost: ${data.get('total_estimated_usd', 0):.4f}",
        f"Cost per 1M tokens: ${data.get('cost_per_1m_tokens', 0):.4f}",
    ]
    if data.get("total_duration_seconds"):
        lines.append(f"Duration: {data['total_duration_seconds']}s")
    model_split = data.get("model_split", [])
    if model_split:
        lines.append("")
        lines.append("Model split:")
        headers = ("Model", "Input", "Split", "Cost", "$/1M input")
        rows = [
            (
                m["model"],
                f"{m['input_tokens']:,}",
                f"{m['split_ratio']:.0%}",
                f"${m['estimated_usd']:.2f}",
                f"${m['cost_per_1m_input_tokens']:.2f}",
            )
            for m in model_split
        ]
        lines.extend(_render_columns(headers, rows, left_cols={0}))
    fallback = data.get("fallback_pricing_models")
    if fallback:
        lines.append(f"Warning: fallback pricing used for {', '.join(fallback)}")
    return "\n".join(lines)


def render_costed_list(items: list[dict]) -> str:
    """Render a list of sessions with cost columns."""
    if not items:
        return "(no sessions found)"
    rows = []
    for s in items:
        started = (s.get("started_at") or s.get("created_at") or "")[:19]
        title = s.get("title") or "(no title)"
        sid = s.get("session_id") or ""
        total = s.get("total", {})
        total_tokens = (
            total.get("input_tokens", 0)
            + total.get("output_tokens", 0)
            + total.get("cached_tokens", 0)
        )
        model_count = len(s.get("models") or [])
        rows.append(
            (started, title, sid, model_count, total_tokens, total.get("estimated_usd", 0.0))
        )

    w_title = _col_width("Title", [r[1] for r in rows], cap=60)
    w_id = _col_width("ID", [r[2] for r in rows])

    lines = [
        f"{'Started':<19} {'Title':<{w_title}} {'ID':<{w_id}} "
        f"{'Models':>6} {'Tokens':>10} {'Cost':>8}"
    ]
    total_width = 19 + 1 + w_title + 1 + w_id + 1 + 6 + 1 + 10 + 1 + 8
    lines.append("-" * total_width)

    total_tokens = 0
    total_usd = 0.0
    for started, title, sid, model_count, tokens, usd in rows:
        total_tokens += tokens
        total_usd += usd
        lines.append(
            f"{started:<19} {title[:w_title]:<{w_title}} {sid:<{w_id}} "
            f"{model_count:>6} {tokens:>10,} ${usd:>7.2f}"
        )

    lines.append("-" * total_width)
    lines.append(
        f"{'TOTAL':<19} {'':<{w_title}} {'':<{w_id}} {'':>6} {total_tokens:>10,} ${total_usd:>7.2f}"
    )
    return "\n".join(lines)


def _is_summary(item: dict) -> bool:
    """Return True if a dict is a per-session efficiency summary."""
    return "model_split" in item and "cost_per_1m_tokens" in item


def _render_summary_list(items: list[dict]) -> str:
    """Render multiple efficiency summaries separated by blank lines."""
    blocks = [render_summary(item) for item in items]
    return "\n\n".join(blocks)


def render(payload: object, fmt: str, costed_list: bool = False) -> str:
    """Render a payload (single session, list, batch, summary, or aggregate) as text."""
    if fmt == "json":
        return json.dumps(payload, indent=2, ensure_ascii=False)
    if costed_list:
        return render_costed_list(payload)  # type: ignore[arg-type]
    if isinstance(payload, list):
        if payload and _is_summary(payload[0]):
            return _render_summary_list(payload)
        return render_table_list(payload)
    if isinstance(payload, dict):
        if "summary" in payload and "sessions" in payload:
            return render_table_list(payload["sessions"], summary=payload["summary"])
        if "session_count" in payload and "model_split" in payload:
            return render_aggregate(payload)
        if "session_count" in payload and "skills" in payload:
            return render_skills_aggregate(payload)
        if "model_split" in payload:
            return render_summary(payload)
        if "skill_breakdown" in payload:
            return render_skill_breakdown(payload)
        if "tool_breakdown" in payload:
            return render_tool_breakdown(payload)
    return render_table_single(payload)  # type: ignore[arg-type]


def emit(
    payload: object, fmt: str, output_path: Path | None = None, costed_list: bool = False
) -> None:
    """Render and print (or save to file) a payload."""
    text = render(payload, fmt, costed_list=costed_list)
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


def skill_breakdown_option(f: Any) -> Any:
    return click.option(
        "--skill-breakdown",
        is_flag=True,
        help="Emit a per-skill cost breakdown instead of the default report.",
    )(f)


def tool_breakdown_option(f: Any) -> Any:
    return click.option(
        "--tool-breakdown",
        is_flag=True,
        help="Emit a per-skill/per-subagent tool-call count breakdown.",
    )(f)


def skill_filter_option(f: Any) -> Any:
    return click.option(
        "--skill",
        "skill_name",
        metavar="NAME",
        help="Filter the report to a single skill (exact or substring match).",
    )(f)


def title_filter_option(f: Any) -> Any:
    return click.option(
        "--title",
        "title_filter",
        metavar="SUBSTRING",
        help="Filter sessions by title substring (case-insensitive).",
    )(f)


def latest_option(f: Any) -> Any:
    return click.option(
        "--latest",
        is_flag=True,
        help="Analyze the most recent matching session instead of all matches.",
    )(f)


def analysis_options(f: Any) -> Any:
    """Combine --detail, --format, --output for single/batch analysis commands."""
    f = output_option(f)
    f = format_option(f)
    f = detail_option(f)
    return f
