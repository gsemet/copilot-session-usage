"""Copilot Session Usage — cost analytics for coding-agent session logs."""

from __future__ import annotations

try:
    from importlib.metadata import version

    __version__ = version("copilot-session-usage")
except Exception:  # pragma: no cover
    __version__ = "unknown"
