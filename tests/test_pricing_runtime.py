"""Tests for runtime pricing refresh and cache selection."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from copilot_session_usage._internal import core

PRICING_YAML = """\
- model: GPT-5 mini
  provider: openai
  input: $0.25
  cached_input: $0.025
  output: $2.00
"""


def _metadata(*, captured: str, **extra: object) -> str:
    values = {
        "_captured": captured,
        "model_count": 1,
        "checksum": "old-checksum",
        **extra,
    }
    return json.dumps(values)


def test_refresh_writes_user_cache_and_skips_fresh_attempt(tmp_path, mocker):
    mocker.patch.object(core, "pricing_config_dir", return_value=tmp_path)
    fetch = mocker.patch.object(core, "_fetch_upstream_pricing", return_value=(PRICING_YAML, 1))

    first = core.refresh_pricing()
    second = core.refresh_pricing()

    assert first.status == "updated"
    assert first.updated is True
    assert second.status == "skipped"
    assert fetch.call_count == 1
    assert (tmp_path / "models-and-pricing.yml").read_text(encoding="utf-8") == PRICING_YAML
    metadata = json.loads((tmp_path / "models-and-pricing.lock").read_text(encoding="utf-8"))
    assert metadata["model_count"] == 1
    assert metadata["_last_attempt"]
    assert (tmp_path / "models-and-pricing.refresh.lock").exists()


def test_force_refresh_bypasses_daily_throttle(tmp_path, mocker):
    mocker.patch.object(core, "pricing_config_dir", return_value=tmp_path)
    fetch = mocker.patch.object(core, "_fetch_upstream_pricing", return_value=(PRICING_YAML, 1))

    core.refresh_pricing()
    result = core.refresh_pricing(force=True)

    assert result.status == "unchanged"
    assert result.forced is True
    assert fetch.call_count == 2


def test_failed_refresh_preserves_existing_cache_and_throttles_failure(tmp_path, mocker):
    mocker.patch.object(core, "pricing_config_dir", return_value=tmp_path)
    old_time = (datetime.now(timezone.utc) - timedelta(days=2)).isoformat()
    yaml_path = tmp_path / "models-and-pricing.yml"
    yaml_path.write_text(PRICING_YAML, encoding="utf-8")
    (tmp_path / "models-and-pricing.lock").write_text(
        _metadata(captured=old_time), encoding="utf-8"
    )
    fetch = mocker.patch.object(
        core, "_fetch_upstream_pricing", side_effect=RuntimeError("offline")
    )

    first = core.refresh_pricing()
    second = core.refresh_pricing()

    assert first.status == "failed"
    assert first.error == "offline"
    assert yaml_path.read_text(encoding="utf-8") == PRICING_YAML
    assert second.status == "skipped"
    assert fetch.call_count == 1
    metadata = json.loads((tmp_path / "models-and-pricing.lock").read_text(encoding="utf-8"))
    assert metadata["_last_error"] == "offline"


def test_load_pricing_uses_newest_valid_user_candidate(tmp_path, mocker):
    mocker.patch.object(core, "pricing_config_dir", return_value=tmp_path)
    mocker.patch.object(core, "_refresh_runtime_pricing")
    future = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()
    (tmp_path / "models-and-pricing.yml").write_text(PRICING_YAML, encoding="utf-8")
    (tmp_path / "models-and-pricing.lock").write_text(_metadata(captured=future), encoding="utf-8")

    pricing = core.load_pricing(auto_refresh=False)

    assert pricing["_source"] == str(tmp_path / "models-and-pricing.yml")
    assert "gpt-5-mini" in pricing["models"]


def test_load_pricing_auto_refresh_failure_falls_back_to_bundled(mocker):
    result = core.PricingRefreshResult(
        status="failed",
        updated=False,
        forced=False,
        source="upstream",
        path=None,
        lock_path=None,
        model_count=None,
        previous_count=None,
        checksum=None,
        attempted_at=datetime.now(timezone.utc),
        error="offline",
    )
    mocker.patch.object(core, "_refresh_runtime_pricing", return_value=result)

    pricing = core.load_pricing()

    assert pricing["models"]
    assert "default" in pricing["models"]


def test_upstream_validation_rejects_invalid_yaml(mocker):
    response = mocker.MagicMock()
    response.read.return_value = b"not: a pricing list"
    response.__enter__.return_value = response
    mocker.patch.object(core.urllib.request, "urlopen", return_value=response)

    with pytest.raises(RuntimeError, match="Failed to parse upstream YAML"):
        core._fetch_upstream_pricing()
