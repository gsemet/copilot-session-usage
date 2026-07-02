#!/usr/bin/env python3
"""Refresh bundled pricing data from upstream."""

from copilot_session_usage._internal.core import refresh_pricing

result = refresh_pricing()
print(f"Updated {result['path']}")
print(f"Models: {result['previous_count']} → {result['model_count']}")
print(f"Lock:   {result['lock_path']}")
