"""Shared pytest fixtures for copilot-session-usage tests."""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _patch_workspace_storage_roots(request, tmp_path, mocker):
    """Ensure tests never depend on VS Code being installed on the host.

    Skipped for test_vscode_platform.py, which monkey-patches platform
    internals directly.
    """
    if "test_vscode_platform" in request.node.nodeid:
        yield
        return
    fake_root = tmp_path / "fake_workspaceStorage"
    fake_root.mkdir()
    mocker.patch(
        "copilot_session_usage._internal.vscode.default_workspace_storage_roots",
        return_value=[fake_root],
    )
    yield
