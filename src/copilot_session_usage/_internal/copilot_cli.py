"""Stub for Copilot-CLI session discovery.

Planned support for Copilot-CLI v1 session logs. Not yet implemented.
"""

from __future__ import annotations

from pathlib import Path


def default_workspace_storage_roots() -> list[Path]:  # pragma: no cover
    """Raise NotImplementedError — Copilot-CLI support is planned for a future release."""
    raise NotImplementedError("Copilot-CLI session discovery is not yet implemented.")


def resolve_ws_roots(workspace_storage: str | None) -> list[Path]:  # pragma: no cover
    """Raise NotImplementedError — Copilot-CLI support is planned for a future release."""
    raise NotImplementedError("Copilot-CLI session discovery is not yet implemented.")
