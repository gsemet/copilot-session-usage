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
import os
import re
import tempfile
import urllib.error
import urllib.request
from collections.abc import Iterable, Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Literal

import click
from platformdirs import user_config_dir

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

_PRICING_FILENAME = "models-and-pricing.yml"
_PRICING_LOCK_FILENAME = "models-and-pricing.lock"
_PRICING_REFRESH_LOCK_FILENAME = "models-and-pricing.refresh.lock"
_PRICING_APP_NAME = "copilot-session-usage"
_PRICING_REFRESH_INTERVAL = timedelta(days=1)


@dataclass(frozen=True)
class PricingRefreshResult:
    """Describe a runtime pricing refresh attempt."""

    status: Literal["updated", "unchanged", "skipped", "failed"]
    updated: bool
    forced: bool
    source: str
    path: Path | None
    lock_path: Path | None
    model_count: int | None
    previous_count: int | None
    checksum: str | None
    attempted_at: datetime
    captured_at: datetime | None = None
    error: str | None = None

    def as_dict(self) -> dict[str, Any]:
        """Return a JSON-friendly representation of the result."""
        return {
            "status": self.status,
            "updated": self.updated,
            "forced": self.forced,
            "source": self.source,
            "path": str(self.path) if self.path else None,
            "lock_path": str(self.lock_path) if self.lock_path else None,
            "model_count": self.model_count,
            "previous_count": self.previous_count,
            "checksum": self.checksum,
            "attempted_at": self.attempted_at.isoformat(),
            "captured_at": self.captured_at.isoformat() if self.captured_at else None,
            "error": self.error,
        }


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


# GitHub Copilot utility models power background features and are not billed as
# premium usage. Keep this list separate from pricing: these requests can still
# appear in local debug logs, but must not contribute to usage analytics.
# Source: https://docs.github.com/en/copilot/concepts/models/utility-models
_UTILITY_MODEL_PREFIXES: tuple[str, ...] = (
    "gpt-4o",
    "gpt-4.1",
    "gpt-5.4-nano",
)


def is_utility_model(model: str) -> bool:
    """Return whether a model belongs to GitHub Copilot's utility families."""
    normalized = _normalize_model_name(model)
    return any(
        normalized == prefix or normalized.startswith(f"{prefix}-")
        for prefix in _UTILITY_MODEL_PREFIXES
    )


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


def _parse_threshold(threshold: str | None) -> tuple[int, int | None]:
    """Parse current pricing comparisons into inclusive integer-token bounds."""
    if threshold is None:
        return 0, None
    if not isinstance(threshold, str):
        raise ValueError(f"unsupported pricing threshold: {threshold!r}")
    if threshold.strip().lower() in ("not applicable", "n/a", ""):
        return 0, None
    match = re.fullmatch(r"\s*(<=|≤|>=|≥|>)\s*([0-9]+)\s*([KM]?)\s*", threshold, re.IGNORECASE)
    if match is None:
        raise ValueError(f"unsupported pricing threshold: {threshold!r}")
    operator, amount, suffix = match.groups()
    tokens = int(amount) * {"K": 1_000, "M": 1_000_000}.get(suffix.upper(), 1)
    if operator in ("<=", "≤"):
        return 0, tokens
    return tokens + (operator == ">"), None


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


def _parse_pricing_entries(text: str, source: str) -> list[dict]:
    """Parse and validate a pricing YAML document."""
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
    return entries


def _read_lock_metadata(lock_path: Path) -> dict[str, Any]:
    """Read pricing lock metadata, returning an empty dict when unavailable."""
    try:
        data = json.loads(lock_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _parse_timestamp(value: object) -> datetime | None:
    """Parse an ISO timestamp stored in pricing metadata."""
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _file_timestamp(path: Path) -> datetime:
    """Return a file modification timestamp as UTC, or the minimum timestamp."""
    try:
        return datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
    except OSError:
        return datetime.min.replace(tzinfo=timezone.utc)


def _candidate_timestamp(path: Path, metadata: dict[str, Any]) -> datetime:
    """Return the capture timestamp for a pricing candidate."""
    return _parse_timestamp(metadata.get("_captured")) or _file_timestamp(path)


def _load_pricing_candidate(
    yaml_path: Path, metadata: dict[str, Any], custom_ref_dir: Path | None
) -> tuple[dict, datetime] | None:
    """Load one pricing candidate, ignoring invalid optional candidates."""
    try:
        text = yaml_path.read_text(encoding="utf-8")
        entries = _parse_pricing_entries(text, str(yaml_path))
    except (OSError, ValueError):
        return None

    pricing = _build_pricing_from_yaml(entries, str(yaml_path))
    custom_models = _load_custom_pricing(custom_ref_dir)
    if custom_models:
        pricing.setdefault("models", {}).update(custom_models)
    return pricing, _candidate_timestamp(yaml_path, metadata)


def pricing_config_dir() -> Path:
    """Return the platform-specific user configuration directory for pricing."""
    return Path(user_config_dir(_PRICING_APP_NAME))


def load_pricing(ref_dir: Path | None = None, *, auto_refresh: bool = False) -> dict:
    """Load pricing from models-and-pricing.yml, merge custom-models-pricing.yml.

    Loading is offline by default: the price table is only a fallback for
    calls that carry no billed cost, so normal analysis never touches the
    network. Use :func:`refresh_pricing` (``pricing refresh``) to update it.

    Raises:
        FileNotFoundError: If ``models-and-pricing.yml`` is missing or unreadable.
        ValueError: If the YAML cannot be parsed or has an unexpected shape.

    Args:
        ref_dir: Directory containing models-and-pricing.yml and
            custom-models-pricing.yml. If None, uses the newest valid user
            snapshot or the bundled data shipped with the package.
        auto_refresh: Opt-in. If true and ``ref_dir`` is None, attempt at most
            one runtime refresh every 24 hours. Failed refreshes use local data.
    """
    source = "bundled models-and-pricing.yml"
    if ref_dir is not None:
        yaml_path = ref_dir / _PRICING_FILENAME
        if yaml_path.exists():
            source = str(yaml_path)
        else:
            msg = f"pricing file not found: {yaml_path}"
            raise FileNotFoundError(msg)
        text = yaml_path.read_text(encoding="utf-8")
        entries = _parse_pricing_entries(text, source)
        pricing = _build_pricing_from_yaml(entries, source)
        custom_models = _load_custom_pricing(ref_dir)
        if custom_models:
            pricing.setdefault("models", {}).update(custom_models)
        return pricing

    if auto_refresh:
        _refresh_runtime_pricing()

    candidates: list[tuple[dict, datetime]] = []
    cache_dir = pricing_config_dir()
    user_candidate = _load_pricing_candidate(
        cache_dir / _PRICING_FILENAME,
        _read_lock_metadata(cache_dir / _PRICING_LOCK_FILENAME),
        None,
    )
    if user_candidate:
        candidates.append(user_candidate)

    bundled_text = _read_data_file(_PRICING_FILENAME)
    if bundled_text is not None:
        bundled_path = Path(f"bundled:{_PRICING_FILENAME}")
        try:
            bundled_entries = _parse_pricing_entries(bundled_text, source)
        except ValueError:
            bundled_entries = []
        if bundled_entries:
            bundled_pricing = _build_pricing_from_yaml(bundled_entries, source)
            custom_models = _load_custom_pricing()
            if custom_models:
                bundled_pricing.setdefault("models", {}).update(custom_models)
            bundled_metadata_text = _read_data_file(_PRICING_LOCK_FILENAME)
            bundled_metadata: dict[str, Any] = {}
            if bundled_metadata_text:
                with contextlib.suppress(ValueError):
                    parsed_metadata = json.loads(bundled_metadata_text)
                    if isinstance(parsed_metadata, dict):
                        bundled_metadata = parsed_metadata
            candidates.append(
                (bundled_pricing, _candidate_timestamp(bundled_path, bundled_metadata))
            )

    if not candidates:
        msg = "bundled models-and-pricing.yml not found or invalid"
        raise FileNotFoundError(msg)
    return max(candidates, key=lambda candidate: candidate[1])[0]


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
        lower, upper = _parse_threshold(entry.get("threshold", ""))
        tier = {
            "input_per_m": _parse_price(entry.get("input", "0")),
            "output_per_m": _parse_price(entry.get("output", "0")),
            "cache_per_m": _parse_price(entry.get("cached_input", "0")),
            "cache_write_per_m": _parse_price(entry.get("cache_write", "0")),
            "tier": entry.get("tier", "Default"),
            "threshold_tokens": upper,
            "min_threshold_tokens": lower,
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
        _atomic_write_text(path, content)
        return path
    except Exception as exc:
        msg = f"Cannot write bundled data file {name}: {exc}"
        raise RuntimeError(msg) from exc


def _atomic_write_text(path: Path, content: str) -> None:
    """Write text through a temporary file and atomically replace the target."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{path.name}.", dir=path.parent, text=True
        )
        temporary_path = Path(temporary_name)
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary_path, path)
    except OSError as exc:
        msg = f"Cannot atomically write {path}: {exc}"
        raise RuntimeError(msg) from exc
    finally:
        if temporary_path is not None:
            with contextlib.suppress(OSError):
                temporary_path.unlink()


@contextmanager
def _pricing_refresh_lock(lock_path: Path) -> Iterator[None]:
    """Serialize refresh writers across processes on Unix and Windows."""
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    lock_path.touch(exist_ok=True)
    with lock_path.open("r+b") as stream:
        if os.name == "nt":
            msvcrt = __import__("msvcrt")

            stream.seek(0, os.SEEK_END)
            if stream.tell() == 0:
                stream.write(b"0")
                stream.flush()
            stream.seek(0)
            msvcrt.locking(stream.fileno(), msvcrt.LK_LOCK, 1)
            try:
                yield
            finally:
                stream.seek(0)
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            fcntl = __import__("fcntl")

            fcntl.flock(stream.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


def _refresh_due(cache_dir: Path, metadata: dict[str, Any], now: datetime) -> bool:
    """Return whether a runtime refresh attempt is due."""
    last_attempt = _parse_timestamp(metadata.get("_last_attempt"))
    if last_attempt is None:
        last_attempt = _parse_timestamp(metadata.get("_captured"))
    if last_attempt is None:
        yaml_path = cache_dir / _PRICING_FILENAME
        if yaml_path.exists():
            last_attempt = _file_timestamp(yaml_path)
    return last_attempt is None or now - last_attempt >= _PRICING_REFRESH_INTERVAL


def _model_count(text: str) -> int:
    """Count named model entries in a validated pricing YAML document."""
    try:
        entries = _parse_pricing_entries(text, "pricing")
    except ValueError:
        return 0
    return sum(1 for entry in entries if isinstance(entry, dict) and entry.get("model"))


def _fetch_upstream_pricing() -> tuple[str, int]:
    """Fetch, parse, and validate the upstream pricing YAML."""
    try:
        with urllib.request.urlopen(_PRICING_URL, timeout=30) as response:  # noqa: S310
            yaml_text: str = response.read().decode("utf-8")
    except (urllib.error.URLError, OSError, TimeoutError) as exc:
        msg = f"Failed to fetch pricing from {_PRICING_URL}: {exc}"
        raise RuntimeError(msg) from exc

    if not yaml_text.strip():
        msg = "No YAML input received from upstream. Check connectivity and re-run."
        raise RuntimeError(msg)

    try:
        model_count = _model_count(yaml_text)
        if model_count == 0:
            raise ValueError("no named models found")
    except ValueError as exc:
        msg = f"Failed to parse upstream YAML: {exc}"
        raise RuntimeError(msg) from exc
    return yaml_text, model_count


def _write_pricing_lock(
    lock_path: Path,
    *,
    captured_at: datetime,
    attempted_at: datetime,
    checksum: str,
    model_count: int,
    source: str,
    error: str | None = None,
) -> None:
    """Write pricing provenance and refresh-attempt metadata."""
    lock = {
        "_captured": captured_at.isoformat(),
        "_last_attempt": attempted_at.isoformat(),
        "_source": source,
        "_yaml_path": str(lock_path.with_name(_PRICING_FILENAME)),
        "model_count": model_count,
        "checksum": checksum,
    }
    if error:
        lock["_last_error"] = error
    _atomic_write_text(lock_path, json.dumps(lock, indent=2) + "\n")


def refresh_pricing(force: bool = False) -> PricingRefreshResult:
    """Refresh the user pricing snapshot from GitHub.

    The normal refresh is throttled to one attempt per rolling 24-hour period.
    Pass ``force=True`` to bypass that limit. Network and validation failures
    are returned as a failed result so automatic callers can keep using local
    pricing data.
    """
    cache_dir = pricing_config_dir()
    yaml_path = cache_dir / _PRICING_FILENAME
    lock_path = cache_dir / _PRICING_LOCK_FILENAME
    refresh_lock_path = cache_dir / _PRICING_REFRESH_LOCK_FILENAME
    attempted_at = datetime.now(timezone.utc)

    try:
        with _pricing_refresh_lock(refresh_lock_path):
            metadata = _read_lock_metadata(lock_path)
            if not force and not _refresh_due(cache_dir, metadata, attempted_at):
                return PricingRefreshResult(
                    status="skipped",
                    updated=False,
                    forced=False,
                    source=str(yaml_path),
                    path=yaml_path if yaml_path.exists() else None,
                    lock_path=lock_path if lock_path.exists() else None,
                    model_count=metadata.get("model_count"),
                    previous_count=metadata.get("model_count"),
                    checksum=metadata.get("checksum"),
                    attempted_at=attempted_at,
                    captured_at=_parse_timestamp(metadata.get("_captured")),
                )

            previous_text = None
            with contextlib.suppress(OSError):
                previous_text = yaml_path.read_text(encoding="utf-8")
            previous_count = _model_count(previous_text) if previous_text else None
            attempt_metadata = dict(metadata)
            attempt_metadata["_last_attempt"] = attempted_at.isoformat()
            attempt_metadata.pop("_last_error", None)
            _atomic_write_text(lock_path, json.dumps(attempt_metadata, indent=2) + "\n")

            try:
                yaml_text, model_count = _fetch_upstream_pricing()
                checksum = hashlib.sha256(yaml_text.encode("utf-8")).hexdigest()[:16]
                old_checksum = metadata.get("checksum")
                updated = not yaml_path.exists() or old_checksum != checksum
                _atomic_write_text(yaml_path, yaml_text)
                captured_at = datetime.now(timezone.utc)
                _write_pricing_lock(
                    lock_path,
                    captured_at=captured_at,
                    attempted_at=attempted_at,
                    checksum=checksum,
                    model_count=model_count,
                    source=_PRICING_URL,
                )
                return PricingRefreshResult(
                    status="updated" if updated else "unchanged",
                    updated=updated,
                    forced=force,
                    source=_PRICING_URL,
                    path=yaml_path,
                    lock_path=lock_path,
                    model_count=model_count,
                    previous_count=previous_count,
                    checksum=checksum,
                    attempted_at=attempted_at,
                    captured_at=captured_at,
                )
            except RuntimeError as exc:
                error = str(exc)
                failed_metadata = dict(metadata)
                failed_metadata["_last_attempt"] = attempted_at.isoformat()
                failed_metadata["_last_error"] = error
                with contextlib.suppress(RuntimeError):
                    _atomic_write_text(lock_path, json.dumps(failed_metadata, indent=2) + "\n")
                return PricingRefreshResult(
                    status="failed",
                    updated=False,
                    forced=force,
                    source=_PRICING_URL,
                    path=yaml_path if yaml_path.exists() else None,
                    lock_path=lock_path if lock_path.exists() else None,
                    model_count=metadata.get("model_count"),
                    previous_count=previous_count,
                    checksum=metadata.get("checksum"),
                    attempted_at=attempted_at,
                    captured_at=_parse_timestamp(metadata.get("_captured")),
                    error=error,
                )
    except (OSError, RuntimeError) as exc:
        return PricingRefreshResult(
            status="failed",
            updated=False,
            forced=force,
            source=_PRICING_URL,
            path=yaml_path if yaml_path.exists() else None,
            lock_path=lock_path if lock_path.exists() else None,
            model_count=None,
            previous_count=None,
            checksum=None,
            attempted_at=attempted_at,
            error=str(exc),
        )


def _refresh_runtime_pricing() -> PricingRefreshResult:
    """Attempt a throttled runtime refresh and leave failures to the fallback."""
    return refresh_pricing(force=False)


def refresh_bundled_pricing() -> PricingRefreshResult:
    """Refresh the package-owned fallback pricing used by release automation."""
    attempted_at = datetime.now(timezone.utc)
    yaml_text, model_count = _fetch_upstream_pricing()
    current_text = _read_data_file(_PRICING_FILENAME)
    previous_count = _model_count(current_text) if current_text else None
    checksum = hashlib.sha256(yaml_text.encode("utf-8")).hexdigest()[:16]
    yaml_path = _write_data_file(_PRICING_FILENAME, yaml_text)
    lock_path = _write_data_file(
        _PRICING_LOCK_FILENAME,
        json.dumps(
            {
                "_captured": attempted_at.isoformat(),
                "_source": _PRICING_URL,
                "_yaml_path": str(yaml_path),
                "model_count": model_count,
                "checksum": checksum,
            },
            indent=2,
        )
        + "\n",
    )

    return PricingRefreshResult(
        status="updated",
        updated=True,
        forced=True,
        source=_PRICING_URL,
        path=yaml_path,
        lock_path=lock_path,
        model_count=model_count,
        previous_count=previous_count,
        checksum=checksum,
        attempted_at=attempted_at,
        captured_at=attempted_at,
    )


def pricing_status() -> dict[str, Any]:
    """Return local runtime pricing cache and fallback metadata."""
    cache_dir = pricing_config_dir()
    metadata = _read_lock_metadata(cache_dir / _PRICING_LOCK_FILENAME)
    return {
        "cache_dir": str(cache_dir),
        "yaml_path": str(cache_dir / _PRICING_FILENAME),
        "lock_path": str(cache_dir / _PRICING_LOCK_FILENAME),
        "refresh_lock_path": str(cache_dir / _PRICING_REFRESH_LOCK_FILENAME),
        "cached": (cache_dir / _PRICING_FILENAME).is_file(),
        "last_attempt": metadata.get("_last_attempt"),
        "captured": metadata.get("_captured"),
        "checksum": metadata.get("checksum"),
        "model_count": metadata.get("model_count"),
        "last_error": metadata.get("_last_error"),
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
        matching_key = max(
            (key for key in models if key != "default" and model.startswith(key)),
            key=len,
            default="",
        )
        tiers = models.get(matching_key)
    if tiers is None:
        tiers = models.get("default", [{}])

    matches = [
        tier
        for tier in tiers
        if input_tok >= tier.get("min_threshold_tokens", 0)
        and (tier.get("threshold_tokens") is None or input_tok <= tier["threshold_tokens"])
    ]
    if not matches:
        raise ValueError(f"no pricing tier for {model} at {input_tok} input tokens")
    return min(  # type: ignore[no-any-return]
        matches,
        key=lambda tier: (
            tier.get("threshold_tokens") is None,
            tier.get("threshold_tokens") or 0,
            -tier.get("min_threshold_tokens", 0),
        ),
    )


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
        if is_utility_model(model):
            continue
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
    input_tok: int,
    output_tok: int,
    cached_tok: int,
    model: str,
    pricing: dict[str, Any],
    *,
    cache_write_tok: int | None = None,
    tier_input_tok: int | None = None,
) -> float:
    """Compute estimated USD cost.

    Threshold-aware: the correct pricing tier is selected automatically based
    on ``input_tok`` so long-context requests use the higher rate.

    For any model with a ``cache_write_per_m`` premium, the
    incremental cache-creation cost is approximated as::

        fresh_input * (cache_write_per_m - input_per_m) / 1_000_000

    VS Code debug logs do not expose ``cacheCreationTokens`` directly; fresh
    input (``inputTokens - cachedTokens``) is used as a proxy.  For typical
    Anthropic sessions the full context prefix is cached, so this closely
    matches the billed amount. This also applies to GPT-5.6 and later
    OpenAI families. Models without ``cache_write`` have no premium.
    Without billed telemetry or exact cache-creation counts, this remains
    an estimate, not a guarantee of parity with VS Code billing.

    When ``cache_write_tok`` is known exactly (Copilot CLI/App), ``input_tok``
    is treated as fresh + cache-read + cache-write tokens and only the
    reported cache-write tokens are charged at ``cache_write_per_m`` (or the
    input rate when the model has no cache-write price).
    ``tier_input_tok`` overrides the token count used to select the pricing
    tier; aggregate-only usage should pass a per-request-sized value rather
    than the session sum.
    """
    rates = _get_model_rates(
        model, input_tok if tier_input_tok is None else tier_input_tok, pricing
    )
    if cache_write_tok is not None:
        fresh = max(0, input_tok - cached_tok - cache_write_tok)
        write_rate = rates.get("cache_write_per_m") or rates.get("input_per_m", 0.0)
        return (  # type: ignore[no-any-return]
            fresh * rates.get("input_per_m", 0.0)
            + cached_tok * rates.get("cache_per_m", 0.0)
            + cache_write_tok * write_rate
            + output_tok * rates.get("output_per_m", 0.0)
        ) / 1_000_000
    billable_input = max(0, input_tok - cached_tok)
    cost = (
        billable_input * rates.get("input_per_m", 0.0) / 1_000_000
        + cached_tok * rates.get("cache_per_m", 0.0) / 1_000_000
        + output_tok * rates.get("output_per_m", 0.0) / 1_000_000
    )
    cache_write_per_m = rates.get("cache_write_per_m", 0.0)
    input_per_m = rates.get("input_per_m", 0.0)
    if cache_write_per_m > input_per_m:
        cost += billable_input * (cache_write_per_m - input_per_m) / 1_000_000
    return cost  # type: ignore[no-any-return]


# ─── Per-call pricing and aggregation (shared by every provider) ──────────────
#
# Both providers are normalized into a list of *call records*. Every total,
# model/subagent/skill/initiator breakdown, reconciliation block and the
# ``calls`` export is aggregated from those records by the code below, so a
# number is computed exactly one way regardless of where the log came from.
#
# Call record fields::
#
#     ts_ms        epoch milliseconds (int | None)
#     model        model identifier (str)
#     input        total prompt tokens INCLUDING cached and cache-written tokens
#     cached       cache-read tokens
#     cache_write  cache-write tokens (None when the provider does not log it)
#     output       completion tokens
#     nano_aiu     billed cost in nanoAiu (1 nanoAiu = 1e-11 USD) or None
#     agent        None for the main agent, else the subagent display name
#     agent_id     provider agent identifier (None for the main agent)
#     initiator    "user" | "agent" | "sub-agent" | "compaction" | None
#     kind         "request" | "compaction"
#     skill        active skill at ``ts_ms`` or "unknown"
#     llm_calls    number of billed LLM calls this record stands for (default 1)

SCHEMA_VERSION = 2

#: 1 nanoAiu = 1e-9 AIC = 1e-11 USD.
NANO_AIU_PER_USD = 1e11

#: Decimal places used for every USD figure in JSON output.
USD_DECIMALS = 6

CALL_KIND_REQUEST = "request"
CALL_KIND_COMPACTION = "compaction"

COST_SOURCE_BILLED = "billed"
COST_SOURCE_ESTIMATED = "estimated"
COST_SOURCE_MIXED = "mixed"


def make_call(
    *,
    ts_ms: int | None,
    model: str,
    input_tokens: int,
    cached_tokens: int,
    output_tokens: int,
    cache_write_tokens: int | None = None,
    nano_aiu: int | float | None = None,
    agent: str | None = None,
    agent_id: str | None = None,
    initiator: str | None = None,
    kind: str = CALL_KIND_REQUEST,
    skill: str = "unknown",
    llm_calls: int = 1,
    premium_requests: int | float | None = None,
) -> dict[str, Any]:
    """Build a normalized call record (see the section comment for field semantics)."""
    return {
        "ts_ms": ts_ms,
        "model": model,
        "input": input_tokens,
        "cached": cached_tokens,
        "cache_write": cache_write_tokens,
        "output": output_tokens,
        "nano_aiu": nano_aiu,
        "agent": agent,
        "agent_id": agent_id,
        "initiator": initiator,
        "kind": kind,
        "skill": skill,
        "llm_calls": llm_calls,
        "premium_requests": premium_requests,
    }


def _uncached_input(call: dict[str, Any]) -> int:
    """Return prompt tokens that were neither cache reads nor cache writes."""
    return int(max(0, call["input"] - call["cached"] - (call.get("cache_write") or 0)))


def estimate_call_usd(call: dict[str, Any], pricing: dict[str, Any]) -> float:
    """Price one call from its tokens with the bundled price table (fallback path).

    The pricing tier is chosen from this call's own input size (per request,
    divided by ``llm_calls`` for records that stand for several requests).
    """
    requests = max(1, call.get("llm_calls") or 1)
    return estimate_cost(
        call["input"],
        call["output"],
        call["cached"],
        call["model"],
        pricing,
        cache_write_tok=call.get("cache_write"),
        tier_input_tok=call["input"] // requests,
    )


def price_calls(calls: list[dict[str, Any]], pricing: dict[str, Any]) -> list[dict[str, Any]]:
    """Return copies of ``calls`` annotated with cost fields.

    Added fields: ``uncached_input``, ``usd`` (billed when ``nano_aiu`` is
    present — including zero — else estimated), ``cost_source``, and
    ``token_estimate_usd`` (the price table applied to the call's tokens,
    always computed so billing can be reconciled against it).
    """
    priced: list[dict[str, Any]] = []
    for call in calls:
        estimate = estimate_call_usd(call, pricing)
        nano = call.get("nano_aiu")
        billed = nano is not None
        priced.append(
            {
                **call,
                "uncached_input": _uncached_input(call),
                "usd": (nano / NANO_AIU_PER_USD) if nano is not None else estimate,
                "cost_source": COST_SOURCE_BILLED if billed else COST_SOURCE_ESTIMATED,
                "token_estimate_usd": estimate,
            }
        )
    return priced


def _merge_cost_source(sources: Iterable[str | None]) -> str | None:
    """Collapse per-call/row cost sources to ``billed``/``estimated``/``mixed``."""
    distinct = {s for s in sources if s}
    if not distinct:
        return None
    if len(distinct) == 1:
        return next(iter(distinct))
    return COST_SOURCE_MIXED


def _sum_optional(values: Iterable[int | None]) -> int | None:
    """Sum the non-``None`` values; ``None`` when no value was reported."""
    present = [v for v in values if v is not None]
    return sum(present) if present else None


def _token_row(priced: list[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate priced calls into the explicit token/cost fields used everywhere."""
    return {
        "input_tokens": sum(c["input"] for c in priced),
        "cached_tokens": sum(c["cached"] for c in priced),
        "cache_write_tokens": _sum_optional(c["cache_write"] for c in priced),
        "uncached_input_tokens": sum(c["uncached_input"] for c in priced),
        "output_tokens": sum(c["output"] for c in priced),
        "llm_calls": sum(c.get("llm_calls") or 1 for c in priced),
        "estimated_usd": round(sum(c["usd"] for c in priced), USD_DECIMALS),
        "cost_source": _merge_cost_source(c["cost_source"] for c in priced),
    }


def _group_by(priced: list[dict[str, Any]], key: Any) -> dict[Any, list[dict[str, Any]]]:
    groups: dict[Any, list[dict[str, Any]]] = {}
    for call in priced:
        groups.setdefault(key(call), []).append(call)
    return groups


def _dominant_model(priced: list[dict[str, Any]]) -> str:
    """Return the model with the most input tokens (deterministic tie-break by name)."""
    by_model: dict[str, int] = {}
    for call in priced:
        by_model[call["model"]] = by_model.get(call["model"], 0) + call["input"]
    if not by_model:
        return "unknown"
    return min(by_model, key=lambda m: (-by_model[m], m))


def build_reconciliation(priced: list[dict[str, Any]]) -> dict[str, Any]:
    """Build the self-verification block for a set of priced calls.

    ``billed_usd`` is the sum of the provider-billed cost over calls that
    carry one. ``estimated_from_tokens_usd`` applies the price table to the
    same billed calls (cache-write aware), so ``delta_pct`` measures how well
    the token formula reproduces billing. ``calls_without_billing`` counts
    calls that had to be estimated.
    """
    billed_calls = [c for c in priced if c["cost_source"] == COST_SOURCE_BILLED]
    billed = sum(c["usd"] for c in billed_calls)
    estimated = sum(c["token_estimate_usd"] for c in billed_calls)
    return {
        "billed_usd": round(billed, USD_DECIMALS),
        "estimated_from_tokens_usd": round(estimated, USD_DECIMALS),
        "delta_pct": round((estimated - billed) / billed * 100, 2) if billed > 0 else None,
        "calls_without_billing": sum(
            c.get("llm_calls") or 1 for c in priced if c["cost_source"] != COST_SOURCE_BILLED
        ),
    }


def summarize_calls(calls: list[dict[str, Any]], pricing: dict[str, Any]) -> dict[str, Any]:
    """Aggregate call records into every per-session breakdown.

    Returns ``total``, ``model_breakdown``, ``subagents``, ``skill_breakdown``,
    ``initiator_breakdown``, ``reconciliation``, ``models`` and
    ``fallback_pricing_models``. The session total is the sum of the rounded
    per-model rows, so per-model USD always adds up to the total exactly.
    """
    priced = price_calls(calls, pricing)

    model_breakdown = [
        {"model": model, **_token_row(items)}
        for model, items in _group_by(priced, _model_key).items()
    ]
    model_breakdown.sort(key=lambda r: (-r["estimated_usd"], r["model"]))

    total = _token_row(priced)
    total["estimated_usd"] = round(sum(r["estimated_usd"] for r in model_breakdown), USD_DECIMALS)
    total["cache_ratio"] = (
        round(total["cached_tokens"] / total["input_tokens"], 3) if total["input_tokens"] else 0.0
    )
    compaction = [c for c in priced if c["kind"] == CALL_KIND_COMPACTION]
    total["compaction"] = {
        "calls": sum(c.get("llm_calls") or 1 for c in compaction),
        "estimated_usd": round(sum(c["usd"] for c in compaction), USD_DECIMALS),
    }

    subagents = []
    for (agent_id, name), items in _group_by(priced, lambda c: (c["agent_id"], c["agent"])).items():
        subagents.append(
            {
                "name": name or "main",
                "subagent_id": agent_id,
                "model": _dominant_model(items),
                **_token_row(items),
            }
        )
    subagents.sort(key=lambda r: (r["name"] != "main", -r["estimated_usd"], r["name"]))

    skill_breakdown = [
        {**{"skill": skill, **_token_row(items)}, "reconciliation": build_reconciliation(items)}
        for skill, items in _group_by(priced, lambda c: c["skill"] or "unknown").items()
    ]
    skill_breakdown.sort(key=lambda r: (-r["estimated_usd"], r["skill"]))

    initiator_breakdown: list[dict[str, Any]] = []
    if any(c["initiator"] is not None for c in priced):
        initiator_breakdown = [
            {
                "initiator": initiator,
                "llm_calls": sum(c.get("llm_calls") or 1 for c in items),
                "estimated_usd": round(sum(c["usd"] for c in items), USD_DECIMALS),
            }
            for initiator, items in _group_by(priced, lambda c: c["initiator"]).items()
        ]
        initiator_breakdown.sort(key=lambda r: (-r["estimated_usd"], str(r["initiator"])))

    models = [r["model"] for r in model_breakdown]
    return {
        "total": total,
        "models": models,
        "model_breakdown": model_breakdown,
        "subagents": subagents,
        "skill_breakdown": skill_breakdown,
        "initiator_breakdown": initiator_breakdown,
        "reconciliation": build_reconciliation(priced),
        "fallback_pricing_models": sorted(
            model for model in models if model_uses_fallback_pricing(model, pricing)
        ),
    }


def _model_key(call: dict[str, Any]) -> str:
    return str(call["model"])


def empty_total() -> dict[str, Any]:
    """Return a ``total`` block for a session with no usage evidence at all."""
    return {
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
    }


def filter_calls_by_window(
    calls: list[dict[str, Any]], since_ms: int | None = None, until_ms: int | None = None
) -> list[dict[str, Any]]:
    """Keep calls whose timestamp falls in ``[since_ms, until_ms]``.

    Calls without a timestamp cannot be placed in a window and are dropped
    whenever a bound is given (never assumed to be inside it).
    """
    if since_ms is None and until_ms is None:
        return calls
    kept = []
    for call in calls:
        ts = call.get("ts_ms")
        if ts is None:
            continue
        if since_ms is not None and ts < since_ms:
            continue
        if until_ms is not None and ts > until_ms:
            continue
        kept.append(call)
    return kept


def export_call(
    priced: dict[str, Any], *, session_id: str | None = None, provider: str | None = None
) -> dict[str, Any]:
    """Shape one priced call as the public JSON object emitted by ``calls``."""
    return {
        "session_id": session_id,
        "provider": provider,
        "ts_ms": priced["ts_ms"],
        "ts": ts_to_iso(priced["ts_ms"]),
        "model": priced["model"],
        "input_tokens": priced["input"],
        "cached_tokens": priced["cached"],
        "cache_write_tokens": priced["cache_write"],
        "uncached_input_tokens": priced["uncached_input"],
        "output_tokens": priced["output"],
        "llm_calls": priced.get("llm_calls") or 1,
        "nano_aiu": priced["nano_aiu"],
        "estimated_usd": round(priced["usd"], USD_DECIMALS),
        "cost_source": priced["cost_source"],
        "agent": priced["agent"],
        "agent_id": priced["agent_id"],
        "initiator": priced["initiator"],
        "kind": priced["kind"],
        "skill": priced["skill"],
    }


def session_calls_for_export(
    calls: list[dict[str, Any]],
    pricing: dict[str, Any],
    *,
    session_id: str | None,
    provider: str | None,
) -> list[dict[str, Any]]:
    """Price and export a session's (already windowed) calls in timestamp order."""
    ordered = sorted(
        enumerate(price_calls(calls, pricing)),
        key=lambda pair: (pair[1]["ts_ms"] is None, pair[1]["ts_ms"] or 0, pair[0]),
    )
    return [export_call(c, session_id=session_id, provider=provider) for _, c in ordered]


# ─── VS Code JSONL parsing ────────────────────────────────────────────────────

_VSCODE_COMPACTION_DEBUG_PREFIX = "summarizeConversationHistory"


def parse_vscode_calls(
    path: Path,
    *,
    agent: str | None,
    agent_id: str | None,
    skill_timeline: list[tuple[int, str]] | None = None,
) -> dict[str, Any]:
    """Parse one VS Code ``.jsonl`` file into normalized call records.

    Only successful ``llm_request`` events that carry token fields are calls:
    failed requests (``attrs.error``) and requests without token counts are
    skipped. Utility models are excluded. Non-LLM timestamps still count
    toward the wall-clock ``first_ts``/``last_ts``.
    """
    calls: list[dict[str, Any]] = []
    first_ts: int | None = None
    last_ts: int | None = None
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
                if not isinstance(obj, dict):
                    continue
                ts: int | None = obj.get("ts")
                if ts is not None:
                    first_ts = ts if first_ts is None or ts < first_ts else first_ts
                    last_ts = ts if last_ts is None or ts > last_ts else last_ts
                if obj.get("type") != "llm_request":
                    continue
                attrs = obj.get("attrs") or {}
                if attrs.get("error"):
                    continue
                if "inputTokens" not in attrs and "outputTokens" not in attrs:
                    continue
                model: str = attrs.get("model", "") or "unknown"
                if is_utility_model(model):
                    continue
                skill = (
                    (active_skill_at_ts(ts, skill_timeline) or "unknown")
                    if skill_timeline and ts is not None
                    else "unknown"
                )
                debug_name = attrs.get("debugName") or ""
                compaction = isinstance(debug_name, str) and debug_name.startswith(
                    _VSCODE_COMPACTION_DEBUG_PREFIX
                )
                calls.append(
                    make_call(
                        ts_ms=ts,
                        model=model,
                        input_tokens=attrs.get("inputTokens") or 0,
                        cached_tokens=attrs.get("cachedTokens") or 0,
                        output_tokens=attrs.get("outputTokens") or 0,
                        cache_write_tokens=None,
                        nano_aiu=attrs.get("copilotUsageNanoAiu"),
                        agent=agent,
                        agent_id=agent_id,
                        kind=CALL_KIND_COMPACTION if compaction else CALL_KIND_REQUEST,
                        skill=skill,
                    )
                )
    except OSError:
        pass
    return {"calls": calls, "first_ts": first_ts, "last_ts": last_ts}


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


def _iter_json_text(value: Any, depth: int = 0) -> Iterator[str]:
    """Yield text values from nested JSON or JSON-encoded string payloads."""
    if isinstance(value, str):
        yield value
        if depth < 3:
            try:
                decoded = json.loads(value)
            except (json.JSONDecodeError, TypeError):
                return
            if decoded != value:
                yield from _iter_json_text(decoded, depth + 1)
    elif isinstance(value, dict):
        for child in value.values():
            yield from _iter_json_text(child, depth)
    elif isinstance(value, list):
        for child in value:
            yield from _iter_json_text(child, depth)


def _load_json_artifact(path: Path) -> Any | None:
    """Load an optional session artifact, returning ``None`` on malformed input."""
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _extract_skills_from_system_prompt(path: Path) -> list[str]:
    """Extract skill names from ``system_prompt_*.json`` skill blocks."""
    payload = _load_json_artifact(path)
    if payload is None:
        return []
    text = "\n".join(_iter_json_text(payload))
    skills: list[str] = []
    for block in re.findall(r"<skill\b[^>]*>(.*?)</skill>", text, re.IGNORECASE | re.DOTALL):
        match = re.search(r"<name>\s*([^<]+?)\s*</name>", block, re.IGNORECASE | re.DOTALL)
        if match:
            skill = match.group(1).strip()
            if skill:
                skills.append(skill)
    return skills


def _extract_skills_from_tool_definition(path: Path) -> list[str]:
    """Extract skill names and slash commands from a ``tools_*.json`` artifact."""
    payload = _load_json_artifact(path)
    if payload is None:
        return []

    skills: list[str] = []

    def collect_named_values(value: Any) -> None:
        if isinstance(value, dict):
            for key, child in value.items():
                if key.lower() in {"skill", "skills", "skill_name", "skillname"}:
                    skills.extend(item for item in _iter_json_text(child) if item.strip())
                collect_named_values(child)
        elif isinstance(value, list):
            for child in value:
                collect_named_values(child)

    for value in _iter_json_text(payload):
        try:
            decoded = json.loads(value)
        except (json.JSONDecodeError, TypeError):
            continue
        if decoded != value:
            payload = decoded

    def iter_objects(value: Any) -> Iterator[dict[str, Any]]:
        if isinstance(value, dict):
            yield value
            for child in value.values():
                yield from iter_objects(child)
        elif isinstance(value, list):
            for child in value:
                yield from iter_objects(child)

    for definition in iter_objects(payload):
        name = definition.get("name")
        if not isinstance(name, str) or "skill" not in name.lower():
            continue
        collect_named_values(definition)
        for value in _iter_json_text(definition):
            for match in re.finditer(r"(?<![\w/])(/[A-Za-z0-9_.-]+(?:\s+[A-Za-z0-9_.-]+)?)", value):
                skills.append(match.group(1).rstrip(".,:;)]}"))
    return skills


def detect_session_skills(session_dir: Path) -> dict[str, list[str]]:
    """Detect skills available in a session from multiple sources.

    Sources (in order of preference):
    - ``user_message`` events containing slash commands
    - ``discovery`` events of type ``Skill Discovery``
    - ``generic`` events named ``Custom Instructions`` with on-demand skill lists
    - ``system_prompt_*.json`` skill blocks
    - ``tools_*.json`` skill definitions and slash commands
    """
    detected: set[str] = set()
    for artifact in sorted(session_dir.glob("system_prompt_*.json")):
        detected.update(
            _normalize_skill_name(skill) for skill in _extract_skills_from_system_prompt(artifact)
        )
    for artifact in sorted(session_dir.glob("tools_*.json")):
        detected.update(
            _normalize_skill_name(skill) for skill in _extract_skills_from_tool_definition(artifact)
        )
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


def analyze_session(
    session_dir: Path,
    pricing: dict,
    since_ms: int | None = None,
    until_ms: int | None = None,
) -> dict:
    """Analyze all JSONL files in a session directory.

    Reads every *.jsonl file to capture usage from both the parent agent
    (main.jsonl) and all subagents (runSubagent-*.jsonl). Each ``llm_request``
    becomes a normalized call record (see :func:`collect_vscode_session_calls`)
    and every figure in the result is aggregated from those records.

    When ``since_ms``/``until_ms`` are given, only calls whose timestamp is in
    that window are counted.
    """
    session_dir = Path(session_dir)
    session_id = session_dir.name
    skill_timeline = build_skill_timeline(session_dir)
    detected_skills = detect_session_skills(session_dir)

    collected = collect_vscode_session_calls(session_dir, skill_timeline)
    all_calls = collected["calls"]
    calls = filter_calls_by_window(all_calls, since_ms, until_ms)
    summary = summarize_calls(calls, pricing)
    diagnostics: list[str] = []
    if not all_calls:
        # No telemetry at all: unavailable, not a measured zero.
        summary["total"] = empty_total()
        summary["reconciliation"] = None
        diagnostics.append(
            "no llm_request events with token usage were found in this session; "
            "usage totals and cost are unavailable."
        )

    global_first_ts = collected["first_ts"]
    global_last_ts = collected["last_ts"]
    llm_ts = [c["ts_ms"] for c in all_calls if c["ts_ms"] is not None]
    duration_s = None
    if global_first_ts is not None and global_last_ts is not None:
        duration_s = round((global_last_ts - global_first_ts) / 1000.0)
    active_duration_s = None
    if llm_ts:
        active_duration_s = round((max(llm_ts) - min(llm_ts)) / 1000.0)

    tool_calls = parse_tool_calls(session_dir, skill_timeline)
    tool_breakdown = aggregate_tool_calls(tool_calls)

    active_skill = skill_timeline[-1][1] if skill_timeline else None

    return {
        "schema_version": SCHEMA_VERSION,
        "session_id": session_id,
        "session_dir": str(session_dir),
        "provider": "vscode",
        "source": str(session_dir),
        "title": None,
        "started_at": ts_to_iso(global_first_ts),
        "ended_at": ts_to_iso(global_last_ts),
        "duration_seconds": duration_s,
        "active_duration_seconds": active_duration_s,
        "total": summary["total"],
        "models": summary["models"],
        "fallback_pricing_models": summary["fallback_pricing_models"],
        "model_breakdown": summary["model_breakdown"],
        "subagents": summary["subagents"],
        "initiator_breakdown": summary["initiator_breakdown"],
        "reconciliation": summary["reconciliation"],
        "diagnostics": diagnostics,
        "skills": {
            "detected": detected_skills["detected"],
            "active": active_skill,
            "breakdown": summary["skill_breakdown"],
            "tool_breakdown": tool_breakdown,
        },
        "pricing_note": (
            "Calls with copilotUsageNanoAiu use VS Code's billed cost, including zero "
            "(cost_source 'billed'). Calls without billing telemetry are estimated from "
            "the price table using their own input size (cost_source 'estimated'); the "
            "VS Code log has no cache-write count, so fresh input is used as the "
            "cache-write proxy. Failed requests are not counted. "
            "Models listed in fallback_pricing_models were priced with the generic "
            "'default' rate and may be inaccurate. "
            "Custom pricing for non-Copilot models can be added to data/custom-models-pricing.yml."
        ),
    }


def collect_vscode_session_calls(
    session_dir: Path, skill_timeline: list[tuple[int, str]] | None = None
) -> dict[str, Any]:
    """Collect normalized call records from every ``*.jsonl`` file of a session.

    Returns ``calls`` (all files merged, sorted by timestamp), plus the
    wall-clock ``first_ts``/``last_ts`` of the files that contain at least
    one counted call.
    """
    subagent_names = get_subagent_names(session_dir / "main.jsonl")
    calls: list[dict[str, Any]] = []
    first_ts: int | None = None
    last_ts: int | None = None
    for jsonl_file in sorted(session_dir.glob("*.jsonl")):
        name, subagent_id = _resolve_subagent_name(jsonl_file.name, subagent_names)
        parsed = parse_vscode_calls(
            jsonl_file,
            agent=None if name == "main" else name,
            agent_id=subagent_id or None,
            skill_timeline=skill_timeline,
        )
        if not parsed["calls"]:
            continue
        calls.extend(parsed["calls"])
        if parsed["first_ts"] is not None and (first_ts is None or parsed["first_ts"] < first_ts):
            first_ts = parsed["first_ts"]
        if parsed["last_ts"] is not None and (last_ts is None or parsed["last_ts"] > last_ts):
            last_ts = parsed["last_ts"]
    calls.sort(key=lambda c: (c["ts_ms"] is None, c["ts_ms"] or 0))
    return {"calls": calls, "first_ts": first_ts, "last_ts": last_ts}


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
        "schema_version": data.get("schema_version", SCHEMA_VERSION),
        "session_id": data.get("session_id"),
        "provider": data.get("provider", "vscode"),
        "title": data.get("title"),
        "started_at": data.get("started_at"),
        "ended_at": data.get("ended_at"),
        "duration_seconds": data.get("duration_seconds"),
        "active_duration_seconds": data.get("active_duration_seconds"),
        "models": data.get("models"),
        "total": data.get("total"),
        "reconciliation": data.get("reconciliation"),
    }
    if detail == "minimal":
        return shaped

    shaped["fallback_pricing_models"] = data.get("fallback_pricing_models", [])
    shaped["pricing_note"] = data.get("pricing_note")
    shaped["skills"] = data.get("skills", {})
    if data.get("diagnostics"):
        shaped["diagnostics"] = data["diagnostics"]
    return shaped


def shape_session_skill_breakdown(data: dict) -> dict:
    """Shape a session report to only its per-skill cost breakdown."""
    return {
        "schema_version": data.get("schema_version", SCHEMA_VERSION),
        "session_id": data.get("session_id"),
        "title": data.get("title"),
        "reconciliation": data.get("reconciliation"),
        "skill_breakdown": data.get("skills", {}).get("breakdown", []),
    }


def shape_session_tool_breakdown(data: dict) -> dict:
    """Shape a session report to only its per-skill/per-subagent tool breakdown."""
    return {
        "schema_version": data.get("schema_version", SCHEMA_VERSION),
        "session_id": data.get("session_id"),
        "title": data.get("title"),
        "reconciliation": data.get("reconciliation"),
        "tool_breakdown": data.get("skills", {}).get("tool_breakdown", []),
    }


def shape_session_minimal_skill(data: dict, skill_name: str) -> dict | None:
    """Return a minimal, stable JSON object for a single skill's cost.

    Returns ``None`` if the skill is not present in the session.
    """
    for skill in data.get("skills", {}).get("breakdown", []):
        if skill["skill"] == skill_name:
            return {
                "schema_version": data.get("schema_version", SCHEMA_VERSION),
                "skill": skill_name,
                "cost_usd": skill["estimated_usd"],
                "input_tokens": skill["input_tokens"],
                "cached_tokens": skill["cached_tokens"],
                "cache_write_tokens": skill.get("cache_write_tokens"),
                "uncached_input_tokens": skill.get("uncached_input_tokens"),
                "output_tokens": skill["output_tokens"],
                "llm_calls": skill["llm_calls"],
                "cost_source": skill.get("cost_source"),
                "reconciliation": skill.get("reconciliation"),
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
                    "cached_tokens": 0,
                    "cache_write_tokens": None,
                    "uncached_input_tokens": 0,
                    "output_tokens": 0,
                    "llm_calls": 0,
                    "estimated_usd": 0.0,
                    "sources": [],
                }
            bucket = per_skill[name]
            bucket["sessions"] += 1
            bucket["input_tokens"] += _measured(skill.get("input_tokens"))
            bucket["cached_tokens"] += _measured(skill.get("cached_tokens"))
            bucket["uncached_input_tokens"] += _measured(skill.get("uncached_input_tokens"))
            bucket["output_tokens"] += _measured(skill.get("output_tokens"))
            bucket["llm_calls"] += _measured(skill.get("llm_calls"))
            bucket["estimated_usd"] += _measured(skill.get("estimated_usd"))
            bucket["cache_write_tokens"] = _sum_optional(
                [bucket["cache_write_tokens"], skill.get("cache_write_tokens")]
            )
            bucket["sources"].append(skill.get("cost_source"))

    skills = sorted(
        [
            {
                "skill": v["skill"],
                "sessions": v["sessions"],
                "input_tokens": v["input_tokens"],
                "cached_tokens": v["cached_tokens"],
                "cache_write_tokens": v["cache_write_tokens"],
                "uncached_input_tokens": v["uncached_input_tokens"],
                "output_tokens": v["output_tokens"],
                "llm_calls": v["llm_calls"],
                "estimated_usd": round(v["estimated_usd"], USD_DECIMALS),
                "cost_source": _merge_cost_source(v["sources"]),
            }
            for v in per_skill.values()
        ],
        key=lambda x: (-x["estimated_usd"], x["skill"]),
    )
    return {"schema_version": SCHEMA_VERSION, "session_count": len(results), "skills": skills}


def _measured(value: Any) -> Any:
    """Return ``value`` unless it's ``None`` (unavailable evidence), else 0.

    Used when summing per-session metrics into a cross-session total: a
    session with unavailable evidence (e.g. a CLI session with no
    ``session.shutdown``) contributes nothing to the sum, the same as if it
    were excluded, rather than being silently treated as a measured zero.
    """
    return value if value is not None else 0


def shape_batch(results: list[dict], detail: str) -> dict:
    """Aggregate multiple full session reports into {summary, sessions}.

    ``summary`` is always a pre-computed aggregate across every session so
    callers never need to iterate and sum themselves (see
    :func:`aggregate_sessions`; the same fields minus ``model_split``).
    ``sessions`` is the per-session array, each shaped by ``detail``.
    Sessions with unavailable evidence (``total`` fields are ``None``)
    contribute nothing to the sums; ``sessions_with_unavailable_cost``
    reports how many were excluded from ``estimated_usd``.
    """
    aggregate = aggregate_sessions(results)
    aggregate.pop("model_split", None)
    sessions = [_strip_schema(shape_session(r, detail)) for r in results]
    return {"schema_version": SCHEMA_VERSION, "summary": aggregate, "sessions": sessions}


def _strip_schema(row: dict) -> dict:
    """Return ``row`` without its per-session ``schema_version`` (set on the envelope)."""
    return {k: v for k, v in row.items() if k != "schema_version"}


def shape_span_report(
    results: list[dict],
    *,
    since: str | None = None,
    until: str | None = None,
    last: str | None = None,
) -> dict:
    """Shape a token-efficient date-span report.

    Unlike a full batch report, this deliberately omits skills, subagents,
    diagnostics, and pricing prose.  The result has a stable contract:
    ``total``, ``reconciliation``, ``models``, and compact ``sessions`` rows.
    Per-model USD always sums to ``total.estimated_usd``.
    """
    aggregate = aggregate_sessions(results)
    models = aggregate.pop("model_split")
    reconciliation = aggregate.pop("reconciliation")
    return {
        "schema_version": SCHEMA_VERSION,
        "report": "span",
        "period": {"since": since, "until": until, "last": last},
        "total": aggregate,
        "reconciliation": reconciliation,
        "models": models,
        "sessions": [_strip_schema(shape_session(result, "minimal")) for result in results],
    }


def parse_since_to_ms(since: Any) -> int | None:
    """Parse a date/datetime string to epoch milliseconds (UTC).

    Accepts ISO 8601 with timezone offsets (e.g. ``2026-07-01T00:00:00Z`` or
    ``2026-07-01T02:00:00+02:00``) as well as the legacy formats
    ``YYYY-MM-DDTHH:MM:SS`` and ``YYYY-MM-DD``.

    ``since`` is typed loosely (``Any``) because callers include JSON-parsed
    event evidence (e.g. Copilot CLI ``timestamp``/``startTime`` fields) whose
    shape is not guaranteed. A non-string value (or an unparseable string) is
    treated as an invalid/missing timestamp and returns ``None`` rather than
    raising, so a single malformed evidence field never crashes parsing.
    """
    if not isinstance(since, str):
        return None
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


def session_has_calls_in_window(
    session: dict, since_ms: int | None = None, until_ms: int | None = None
) -> bool:
    """Return whether a discovered session has at least one call in the window.

    Used by metadata-only listings so a session created long ago but active
    inside the window is listed, and one merely touched (mtime) but with no
    in-window call is not. With no bounds every session qualifies.
    """
    if since_ms is None and until_ms is None:
        return True
    from copilot_session_usage._internal import copilot_cli  # noqa: PLC0415

    session_dir = Path(session["debug_log_dir"])
    try:
        if session.get("provider") == "cli":
            calls = copilot_cli.collect_cli_calls(session_dir)
        else:
            calls = collect_vscode_session_calls(session_dir, build_skill_timeline(session_dir))[
                "calls"
            ]
    except (OSError, ValueError):
        return False
    return bool(filter_calls_by_window(calls, since_ms, until_ms))


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


def merge_provider_sessions(session_lists: list[list[dict]]) -> list[dict]:
    """Merge session-metadata lists from multiple providers, most-recent first.

    Deduplicates by canonical session UUID (``session_id``): a session that
    somehow appears in more than one list keeps the record from whichever
    list is passed first. This only runs when a caller explicitly opts into
    combined-provider discovery — it never mixes providers on its own.
    """
    merged: dict[str, dict] = {}
    for sessions in session_lists:
        for session in sessions:
            session_id = session.get("session_id")
            if not session_id or session_id in merged:
                continue
            merged[session_id] = session
    return sorted(merged.values(), key=lambda s: s.get("created_ms") or 0, reverse=True)


def compute_efficiency_summary(result: dict) -> dict:
    """Compute a cost-efficiency summary for a single analyzed session.

    Fields derived from unavailable evidence (``result["total"]`` entries
    that are ``None``) stay ``None`` here too, rather than being computed
    from a fabricated zero.
    """
    total = result.get("total", {})
    summary: dict = {
        "schema_version": result.get("schema_version", SCHEMA_VERSION),
        "session_id": result.get("session_id"),
        "title": result.get("title"),
        "reconciliation": result.get("reconciliation"),
        "cache_ratio": total.get("cache_ratio"),
        "input_tokens": total.get("input_tokens"),
        "cached_tokens": total.get("cached_tokens"),
        "cache_write_tokens": total.get("cache_write_tokens"),
        "uncached_input_tokens": total.get("uncached_input_tokens"),
        "output_tokens": total.get("output_tokens"),
        "llm_calls": total.get("llm_calls"),
        "estimated_usd": total.get("estimated_usd"),
        "cost_source": total.get("cost_source"),
        "model_split": [
            {
                "model": m["model"],
                "input_tokens": m.get("input_tokens"),
                "cached_tokens": m.get("cached_tokens"),
                "cache_write_tokens": m.get("cache_write_tokens"),
                "uncached_input_tokens": m.get("uncached_input_tokens"),
                "output_tokens": m.get("output_tokens"),
                "llm_calls": m.get("llm_calls"),
                "estimated_usd": m.get("estimated_usd"),
                "cost_source": m.get("cost_source"),
            }
            for m in sorted(
                result.get("model_breakdown", []),
                key=lambda x: _measured(x.get("estimated_usd")),
                reverse=True,
            )
        ],
    }
    return summary


def merge_session_results(results: list[dict]) -> dict:
    """Merge multiple raw session analyses into one result-shaped dict.

    Built on :func:`aggregate_sessions`, so it has the same ``total`` /
    ``model_breakdown`` structure produced by ``analyze_session`` and can be
    passed directly to the trailer builders. Unavailable (``None``) fields
    contribute nothing to sums.
    """
    if not results:
        return {"total": {}, "model_breakdown": []}
    agg = aggregate_sessions(results)
    total = {
        k: agg[k]
        for k in (
            "input_tokens",
            "cached_tokens",
            "cache_write_tokens",
            "uncached_input_tokens",
            "output_tokens",
            "llm_calls",
            "estimated_usd",
            "cost_source",
            "cache_ratio",
        )
    }
    return {"total": total, "model_breakdown": agg["model_split"]}


def aggregate_sessions(results: list[dict]) -> dict:
    """Aggregate multiple session analyses into a single flat summary.

    Sessions with unavailable evidence (``total`` fields are ``None``, e.g. a
    CLI session with no usage records) contribute nothing to the sums rather
    than being counted as a measured zero. ``cache_ratio`` is weighted
    (``sum(cached) / sum(input)``). ``estimated_usd`` is the sum of the
    per-model ``model_split`` rows, so the models always add up to the total.
    """
    sums: dict[str, list[Any]] = {
        "input_tokens": [],
        "cached_tokens": [],
        "uncached_input_tokens": [],
        "output_tokens": [],
        "llm_calls": [],
        "estimated_usd": [],
        "cache_write_tokens": [],
    }
    fallback_models: set[str] = set()
    unavailable = 0
    sessions_without_split = 0
    compaction_calls: list[Any] = []
    compaction_usd: list[Any] = []
    billed = estimated = 0.0
    without_billing = 0
    have_reconciliation = False
    sources: list[str | None] = []
    per_model: dict[str, dict] = {}

    for r in results:
        t = r.get("total", {}) or {}
        if t.get("estimated_usd") is None:
            unavailable += 1
        for key, bucket_values in sums.items():
            bucket_values.append(t.get(key))
        if (t.get("estimated_usd") or t.get("llm_calls")) and not r.get("model_breakdown"):
            sessions_without_split += 1
        sources.append(t.get("cost_source"))
        comp = t.get("compaction") or {}
        compaction_calls.append(comp.get("calls"))
        compaction_usd.append(comp.get("estimated_usd"))
        fallback_models.update(r.get("fallback_pricing_models") or [])
        rec = r.get("reconciliation")
        if rec:
            have_reconciliation = True
            billed += _measured(rec.get("billed_usd"))
            estimated += _measured(rec.get("estimated_from_tokens_usd"))
            without_billing += _measured(rec.get("calls_without_billing"))

        seen_models: set[str] = set()
        for m in r.get("model_breakdown", []):
            model = m["model"]
            bucket = per_model.setdefault(
                model,
                {
                    "model": model,
                    "session_count": 0,
                    "input_tokens": 0,
                    "cached_tokens": 0,
                    "cache_write_tokens": None,
                    "uncached_input_tokens": 0,
                    "output_tokens": 0,
                    "llm_calls": 0,
                    "estimated_usd": 0.0,
                    "sources": [],
                },
            )
            if model not in seen_models:
                bucket["session_count"] += 1
                seen_models.add(model)
            for key in (
                "input_tokens",
                "cached_tokens",
                "uncached_input_tokens",
                "output_tokens",
                "llm_calls",
                "estimated_usd",
            ):
                bucket[key] += _measured(m.get(key))
            bucket["cache_write_tokens"] = _sum_optional(
                [bucket["cache_write_tokens"], m.get("cache_write_tokens")]
            )
            bucket["sources"].append(m.get("cost_source"))

    model_split = []
    for bucket in per_model.values():
        row = {k: v for k, v in bucket.items() if k != "sources"}
        row["estimated_usd"] = round(bucket["estimated_usd"], USD_DECIMALS)
        row["cost_source"] = _merge_cost_source(bucket["sources"])
        model_split.append(row)
    model_split.sort(key=lambda r: (-r["estimated_usd"], r["model"]))
    split_usd = round(sum(r["estimated_usd"] for r in model_split), USD_DECIMALS)

    reconciliation = None
    if have_reconciliation:
        reconciliation = {
            "billed_usd": round(billed, USD_DECIMALS),
            "estimated_from_tokens_usd": round(estimated, USD_DECIMALS),
            "delta_pct": round((estimated - billed) / billed * 100, 2) if billed > 0 else None,
            "calls_without_billing": without_billing,
        }

    def _total(key: str) -> Any:
        present = [v for v in sums[key] if v is not None]
        return sum(present) if present else None

    input_total = _total("input_tokens")
    cached_total = _total("cached_tokens")
    usd_total = _total("estimated_usd")
    if usd_total is not None:
        usd_total = round(usd_total, USD_DECIMALS)
    elif model_split:
        usd_total = split_usd
    has_compaction = any(v is not None for v in compaction_calls)

    out = {
        "session_count": len(results),
        "input_tokens": input_total,
        "cached_tokens": cached_total,
        "cache_write_tokens": _total("cache_write_tokens"),
        "uncached_input_tokens": _total("uncached_input_tokens"),
        "output_tokens": _total("output_tokens"),
        "llm_calls": _total("llm_calls"),
        "estimated_usd": usd_total,
        "cost_source": _merge_cost_source(sources),
        "cache_ratio": (
            None
            if input_total is None or cached_total is None
            else (round(cached_total / input_total, 3) if input_total else 0.0)
        ),
        "compaction": (
            {
                "calls": sum(v for v in compaction_calls if v is not None),
                "estimated_usd": round(
                    sum(v for v in compaction_usd if v is not None), USD_DECIMALS
                ),
            }
            if has_compaction
            else None
        ),
        "fallback_pricing_models": sorted(fallback_models),
        "sessions_with_unavailable_cost": unavailable,
        "reconciliation": reconciliation,
        "model_split": model_split,
    }
    if sessions_without_split:
        # Per-model rows are absent from compact/minimal session results, so the
        # model_split above does not cover those sessions' USD.
        out["sessions_without_model_split"] = sessions_without_split
    return out


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
        "schema_version": "Output schema version (number)",
        "session_id": "Session UUID (string)",
        "title": "Session title, if known (string)",
        "started_at": "ISO 8601 start timestamp (string)",
        "ended_at": "ISO 8601 end timestamp (string)",
        "duration_seconds": "Wall-clock duration in seconds (number)",
        "active_duration_seconds": "Duration covered by LLM calls in seconds (number)",
        "models": "List of model names used (list[string])",
        "fallback_pricing_models": "Models priced with the generic default rate (list[string])",
        "total.input_tokens": "Prompt tokens incl. cache reads and writes (number)",
        "total.cached_tokens": "Cache-read tokens, a subset of input (number)",
        "total.cache_write_tokens": "Cache-write tokens (subset of input); null on VS Code",
        "total.uncached_input_tokens": "Input minus cache reads and writes (number)",
        "total.output_tokens": "Total output tokens (number)",
        "total.llm_calls": "Total LLM calls (number)",
        "total.estimated_usd": "USD cost: billed where available (number)",
        "total.cost_source": "billed, estimated or mixed (string)",
        "total.cache_ratio": "Cached tokens / input tokens (number)",
        "total.compaction.calls": "Context-compaction calls (number)",
        "total.compaction.estimated_usd": "USD spent on context compaction (number)",
        "reconciliation.billed_usd": "Sum of provider-billed cost (number)",
        "reconciliation.estimated_from_tokens_usd": "Price table applied to billed calls (number)",
        "reconciliation.delta_pct": "Token-formula error versus billing in percent (number)",
        "reconciliation.calls_without_billing": "Calls that had to be estimated (number)",
        "model_breakdown": "Per-model token/cost breakdown (list[dict])",
        "model_breakdown[0].model": "Model name in first breakdown row (string)",
        "model_breakdown[0].input_tokens": "Input tokens for first model (number)",
        "model_breakdown[0].estimated_usd": "USD for first model (number)",
        "subagents": "Per-agent attribution (list[dict])",
        "subagents[0].name": "Agent name in first row (string)",
        "subagents[0].estimated_usd": "USD for first agent (number)",
        "initiator_breakdown": "Cost per call initiator (list[dict])",
        "skills.detected": "Skills detected in the session (list[string])",
        "skills.active": "Most recently invoked skill (string)",
        "skills.breakdown": "Per-skill token/cost breakdown (list[dict])",
        "skills.breakdown[0].skill": "Skill name in first breakdown row (string)",
        "skills.breakdown[0].estimated_usd": "USD for first skill (number)",
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


def _na(value: Any, fmt: str = "{}") -> str:
    """Format ``value`` with ``fmt``, or ``"n/a"`` when it is unavailable (``None``)."""
    return "n/a" if value is None else fmt.format(value)


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
    usd = total.get("estimated_usd")
    dur = data.get("duration_seconds")
    active = data.get("active_duration_seconds")
    dur_str = f"{dur}s" if dur is not None else "n/a"
    if active is not None and active != dur:
        dur_str += f"  (active: {active}s)"

    lines.append(f"Session:   {data.get('session_id')}")
    provider = data.get("provider")
    if provider and provider != "vscode":
        lines.append(f"Provider:  {provider}")
        if data.get("source"):
            lines.append(f"Source:    {data.get('source')}")
    lines.append(f"Title:     {data.get('title') or '(unknown)'}")
    lines.append(f"Started:   {data.get('started_at')}")
    lines.append(f"Duration:  {dur_str}")
    if data.get("models") is not None:
        lines.append(f"Models:    {', '.join(data.get('models') or [])}")
    lines.append(f"Input:     {_na(total.get('input_tokens'), '{:,} tokens')} (incl. cache)")
    lines.append(f"Output:    {_na(total.get('output_tokens'), '{:,} tokens')}")
    cache_ratio = total.get("cache_ratio")
    cache_pct = _na(cache_ratio, "{:.0%}")
    lines.append(f"Cached:    {_na(total.get('cached_tokens'), '{:,}')} ({cache_pct})")
    if total.get("cache_write_tokens") is not None:
        lines.append(f"Cache wr.: {total['cache_write_tokens']:,}")
    lines.append(f"Uncached:  {_na(total.get('uncached_input_tokens'), '{:,}')}")
    lines.append(f"LLM calls: {_na(total.get('llm_calls'))}")
    cost_source = total.get("cost_source")
    source_str = f" ({cost_source})" if cost_source else ""
    lines.append(f"Cost:      {_na(usd, '${:.4f}')}{source_str}")
    compaction = total.get("compaction")
    if compaction and compaction.get("calls"):
        lines.append(f"Compaction: {compaction['calls']} calls, ${compaction['estimated_usd']:.4f}")
    rec = data.get("reconciliation")
    if rec and rec.get("billed_usd"):
        delta = _na(rec.get("delta_pct"), "{:+.2f}%")
        lines.append(
            f"Reconcile: billed ${rec['billed_usd']:.4f} vs tokens "
            f"${rec['estimated_from_tokens_usd']:.4f} ({delta}); "
            f"{rec['calls_without_billing']} calls unbilled"
        )

    diagnostics = data.get("diagnostics")
    if diagnostics:
        lines.append("")
        lines.append("Diagnostics:")
        for note in diagnostics:
            lines.append(f"  - {note}")

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
                # A model row can carry a ``None`` field when the source
                # (e.g. a Copilot CLI session with partial modelMetrics)
                # only reported some of these; render "n/a" for that field
                # instead of crashing on `:,`/`:.2f` formatting of None.
                _na(m["input_tokens"], "{:,}"),
                _na(m["cached_tokens"], "{:,}"),
                _na(m["output_tokens"], "{:,}"),
                _na(m["llm_calls"], "{:,}"),
                _na(m["estimated_usd"], "${:.2f}"),
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
                sub["name"] or "",
                sub["model"] or "",
                _na(sub.get("input_tokens"), "{:,}"),
                _na(sub.get("cached_tokens"), "{:,}"),
                _na(sub.get("output_tokens"), "{:,}"),
                _na(sub.get("estimated_usd"), "${:.2f}"),
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
            _na(s.get("input_tokens"), "{:,}"),
            _na(s.get("cached_tokens"), "{:,}"),
            _na(s.get("output_tokens"), "{:,}"),
            _na(s.get("llm_calls"), "{:,}"),
            _na(s.get("estimated_usd"), "${:.4f}"),
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
    headers = ("Skill", "Sessions", "Input", "Cached", "Output", "Calls", "Cost")
    rows = [
        (
            s["skill"],
            f"{s['sessions']:,}",
            _na(s.get("input_tokens"), "{:,}"),
            _na(s.get("cached_tokens"), "{:,}"),
            _na(s.get("output_tokens"), "{:,}"),
            _na(s.get("llm_calls"), "{:,}"),
            _na(s.get("estimated_usd"), "${:.4f}"),
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
    lines.append(
        f"  Input:         {_na(summary.get('input_tokens'), '{:,}')} tokens (incl. cache)"
    )
    lines.append(
        f"  Cached:        {_na(summary.get('cached_tokens'), '{:,}')} tokens "
        f"({_na(summary.get('cache_ratio'), '{:.0%}')} of input)"
    )
    lines.append(f"  Output:        {_na(summary.get('output_tokens'), '{:,}')} tokens")
    lines.append(f"  Calls:         {_na(summary.get('llm_calls'))}")
    lines.append(f"  Cost:          {_na(summary.get('estimated_usd'), '${:.4f}')}")
    unavailable = summary.get("sessions_with_unavailable_cost")
    if unavailable:
        lines.append(
            f"  Note:          {unavailable} session(s) had no cost evidence and were "
            "excluded from Cost."
        )
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
        rows.append((i, started, title, sid, model, t.get("input_tokens"), t.get("estimated_usd")))

    w_title = _col_width("Title", [r[2] for r in rows], cap=60)
    w_id = _col_width("ID", [r[3] for r in rows])
    w_model = _col_width("Model", [r[4] for r in rows], cap=30)

    lines = [
        f"{'#':<3} {'Date':<16} {'Title':<{w_title}} {'ID':<{w_id}} "
        f"{'Model':<{w_model}} {'Input':>10} {'Cost':>8}"
    ]
    total_width = 3 + 1 + 16 + 1 + w_title + 1 + w_id + 1 + w_model + 1 + 10 + 1 + 8
    lines.append("-" * total_width)

    total_input = _sum_optional(r[5] for r in rows)
    usd_vals = [r[6] for r in rows if r[6] is not None]
    total_usd = sum(usd_vals) if usd_vals else None
    for i, started, title, sid, model, inp, usd in rows:
        inp_str = _na(inp, "{:,}")
        usd_str = _na(usd, "${:.2f}")
        lines.append(
            f"{i:<3} {started:<16} {title[:w_title]:<{w_title}} {sid:<{w_id}} "
            f"{model[:w_model]:<{w_model}} {inp_str:>10} {usd_str:>8}"
        )

    if summary is not None:
        total_input = summary.get("input_tokens", total_input)
        total_usd = summary.get("estimated_usd", total_usd)
    lines.append("-" * total_width)
    lines.append(
        f"{'TOTAL':<3} {'':<16} {'':<{w_title}} {'':<{w_id}} {'':<{w_model}} "
        f"{_na(total_input, '{:,}'):>10} {_na(total_usd, '${:.2f}'):>8}"
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
        f"Cache ratio: {_na(data.get('cache_ratio'), '{:.0%}')}",
        f"Input tokens: {_na(data.get('input_tokens'), '{:,}')} (incl. cache)",
        f"Cached tokens: {_na(data.get('cached_tokens'), '{:,}')}",
        f"Uncached input: {_na(data.get('uncached_input_tokens'), '{:,}')}",
        f"Output tokens: {_na(data.get('output_tokens'), '{:,}')}",
        f"LLM calls: {_na(data.get('llm_calls'))}",
        f"Cost: {_na(data.get('estimated_usd'), '${:.4f}')}",
    ]
    model_split = data.get("model_split", [])
    if model_split:
        lines.append("")
        lines.append("Model split:")
        headers = ("Model", "Input", "Cached", "Output", "Cost")
        rows = [
            (
                m["model"],
                # A model row may carry ``None`` fields; render "n/a".
                _na(m["input_tokens"], "{:,}"),
                _na(m["cached_tokens"], "{:,}"),
                _na(m["output_tokens"], "{:,}"),
                _na(m["estimated_usd"], "${:.2f}"),
            )
            for m in model_split
        ]
        lines.extend(_render_columns(headers, rows, left_cols={0}))
    return "\n".join(lines)


def render_aggregate(data: dict) -> str:
    """Render an aggregate summary across sessions as a human-readable block."""
    lines = [
        f"Aggregate across {data.get('session_count', 0)} sessions",
        f"Input tokens: {_na(data.get('input_tokens'), '{:,}')} (incl. cache)",
        f"Cached tokens: {_na(data.get('cached_tokens'), '{:,}')} "
        f"({_na(data.get('cache_ratio'), '{:.0%}')} of input)",
        f"Uncached input: {_na(data.get('uncached_input_tokens'), '{:,}')}",
        f"Output tokens: {_na(data.get('output_tokens'), '{:,}')}",
        f"LLM calls: {_na(data.get('llm_calls'))}",
        f"Cost: {_na(data.get('estimated_usd'), '${:.4f}')} ({data.get('cost_source') or 'n/a'})",
    ]
    model_split = data.get("model_split", [])
    if model_split:
        lines.append("")
        lines.append("Model split:")
        headers = ("Model", "Input", "Cached", "Output", "Cost")
        rows = [
            (
                m["model"],
                _na(m.get("input_tokens"), "{:,}"),
                _na(m.get("cached_tokens"), "{:,}"),
                _na(m.get("output_tokens"), "{:,}"),
                _na(m.get("estimated_usd"), "${:.2f}"),
            )
            for m in model_split
        ]
        lines.extend(_render_columns(headers, rows, left_cols={0}))
    fallback = data.get("fallback_pricing_models")
    if fallback:
        lines.append(f"Warning: fallback pricing used for {', '.join(fallback)}")
    return "\n".join(lines)


def render_span_report(data: dict) -> str:
    """Render the compact date-span report as total/model/session sections."""
    period = data.get("period", {})
    period_parts = []
    if period.get("since"):
        period_parts.append(f"since {period['since']}")
    if period.get("until"):
        period_parts.append(f"until {period['until']}")
    if period.get("last"):
        period_parts.append(f"last {period['last']}")
    period_text = ", ".join(period_parts) if period_parts else "all discovered sessions"

    total = data.get("total", {})
    lines = [f"Span report ({period_text})", "", "Total:"]
    lines.extend(
        [
            f"  Sessions:       {total.get('session_count', 0):,}",
            f"  Input:          {_na(total.get('input_tokens'), '{:,}')} tokens (incl. cache)",
            f"  Cached:         {_na(total.get('cached_tokens'), '{:,}')} tokens "
            f"({_na(total.get('cache_ratio'), '{:.0%}')} of input)",
            f"  Cache written:  {_na(total.get('cache_write_tokens'), '{:,}')}",
            f"  Uncached input: {_na(total.get('uncached_input_tokens'), '{:,}')} tokens",
            f"  Output:         {_na(total.get('output_tokens'), '{:,}')} tokens",
            f"  LLM calls:      {_na(total.get('llm_calls'), '{:,}')}",
            f"  Cost:           {_na(total.get('estimated_usd'), '${:.4f}')} "
            f"({total.get('cost_source') or 'n/a'})",
        ]
    )
    compaction = total.get("compaction") or {}
    if compaction.get("calls"):
        lines.append(
            f"  Compaction:     {compaction['calls']:,} calls, ${compaction['estimated_usd']:.4f}"
        )
    unavailable = total.get("sessions_with_unavailable_cost", 0)
    if unavailable:
        lines.append(
            f"  Unavailable:     {unavailable} session(s), excluded from estimated cost totals"
        )
    rec = data.get("reconciliation")
    if rec:
        lines.append(
            f"  Reconciliation: billed ${rec['billed_usd']:.4f}, tokens-formula "
            f"${rec['estimated_from_tokens_usd']:.4f} ({_na(rec.get('delta_pct'), '{:+.2f}%')}), "
            f"{rec['calls_without_billing']:,} unbilled calls"
        )

    model_rows = [
        (
            model["model"],
            str(model.get("session_count", 0)),
            _na(model.get("input_tokens"), "{:,}"),
            _na(model.get("cached_tokens"), "{:,}"),
            _na(model.get("output_tokens"), "{:,}"),
            _na(model.get("llm_calls"), "{:,}"),
            _na(model.get("estimated_usd"), "${:.4f}"),
        )
        for model in data.get("models", [])
    ]
    lines.extend(["", "Per model:"])
    if model_rows:
        lines.extend(
            _render_columns(
                ("Model", "Sessions", "Input", "Cached", "Output", "Calls", "Cost"),
                model_rows,
                left_cols={0},
            )
        )
    else:
        lines.append("  (no costed model evidence)")

    session_rows = []
    for session in data.get("sessions", []):
        total = session.get("total", {})
        session_rows.append(
            (
                session.get("title") or "(no title)",
                session.get("provider") or "vscode",
                (session.get("started_at") or session.get("created_at") or "")[:19],
                _na(session.get("duration_seconds")),
                _na(total.get("llm_calls"), "{:,}"),
                _na(total.get("input_tokens"), "{:,}"),
                _na(total.get("cached_tokens"), "{:,}"),
                _na(total.get("output_tokens"), "{:,}"),
                _na(total.get("estimated_usd"), "${:.4f}"),
            )
        )
    lines.extend(["", "Per session:"])
    if session_rows:
        lines.extend(
            _render_columns(
                (
                    "Session",
                    "Provider",
                    "Started",
                    "Duration",
                    "Calls",
                    "Input",
                    "Cached",
                    "Output",
                    "Cost",
                ),
                session_rows,
                left_cols={0, 1, 2},
            )
        )
    else:
        lines.append("  (no sessions found)")
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
        input_tokens = total.get("input_tokens")
        model_count = len(s.get("models") or [])
        rows.append((started, title, sid, model_count, input_tokens, total.get("estimated_usd")))

    w_title = _col_width("Title", [r[1] for r in rows], cap=60)
    w_id = _col_width("ID", [r[2] for r in rows])

    lines = [
        f"{'Started':<19} {'Title':<{w_title}} {'ID':<{w_id}} "
        f"{'Models':>6} {'Input':>10} {'Cost':>8}"
    ]
    total_width = 19 + 1 + w_title + 1 + w_id + 1 + 6 + 1 + 10 + 1 + 8
    lines.append("-" * total_width)

    total_input_sum = _sum_optional(r[4] for r in rows)
    total_usd_vals = [r[5] for r in rows if r[5] is not None]
    total_usd_sum = sum(total_usd_vals) if total_usd_vals else None
    for started, title, sid, model_count, tokens, usd in rows:
        tokens_str = _na(tokens, "{:,}")
        usd_str = _na(usd, "${:.2f}")
        lines.append(
            f"{started:<19} {title[:w_title]:<{w_title}} {sid:<{w_id}} "
            f"{model_count:>6} {tokens_str:>10} {usd_str:>8}"
        )

    lines.append("-" * total_width)
    lines.append(
        f"{'TOTAL':<19} {'':<{w_title}} {'':<{w_id}} {'':>6} "
        f"{_na(total_input_sum, '{:,}'):>10} {_na(total_usd_sum, '${:.2f}'):>8}"
    )
    return "\n".join(lines)


def _is_summary(item: dict) -> bool:
    """Return True if a dict is a per-session efficiency summary."""
    return "model_split" in item and "session_count" not in item


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
        if payload.get("report") == "span":
            return render_span_report(payload)
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
        help="Filter the report to a single skill (exact normalized match).",
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
    f = click.option(
        "--minimal",
        is_flag=True,
        help="Alias for --detail minimal.",
    )(f)
    f = output_option(f)
    f = format_option(f)
    f = detail_option(f)
    return f
