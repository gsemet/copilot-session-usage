"""Shared pytest fixtures for copilot-session-usage tests."""

from __future__ import annotations

import json
from pathlib import Path

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


@pytest.fixture(autouse=True)
def _patch_session_state_roots(request, tmp_path, mocker):
    """Ensure tests never depend on a real ``~/.copilot/session-state`` on the host.

    Skipped for the copilot_cli discovery tests, which exercise
    ``default_session_state_roots()`` directly against a patched home dir.
    """
    if "test_copilot_cli" in request.node.nodeid:
        yield
        return
    fake_root = tmp_path / "fake_session_state"
    fake_root.mkdir()
    mocker.patch(
        "copilot_session_usage._internal.copilot_cli.default_session_state_roots",
        return_value=[fake_root],
    )
    yield


def _write_cli_session(
    root: Path,
    session_id: str,
    *,
    events: list[dict] | None = None,
    workspace: dict | None = None,
) -> Path:
    """Write a minimal, representative Copilot CLI session directory under ``root``.

    Returns the created session directory. ``events`` defaults to a complete
    session (start, one skill invocation, one tool call, and a shutdown event
    with a per-model token breakdown) when not provided.
    """
    session_dir = root / session_id
    session_dir.mkdir(parents=True, exist_ok=True)

    if events is None:
        events = [
            {
                "type": "session.start",
                "data": {
                    "sessionId": session_id,
                    "version": 1,
                    "producer": "copilot-agent",
                    "copilotVersion": "1.0.0",
                    "startTime": "2026-01-01T00:00:00.000Z",
                    "selectedModel": "gpt-5.6-luna",
                    "reasoningEffort": "medium",
                    "context": {"cwd": "/proj"},
                },
                "id": "e1",
                "timestamp": "2026-01-01T00:00:00.000Z",
                "parentId": None,
            },
            {
                "type": "skill.invoked",
                "data": {"name": "my-skill", "path": "/skills/my-skill/SKILL.md"},
                "id": "e2",
                "timestamp": "2026-01-01T00:00:05.000Z",
                "parentId": "e1",
            },
            {
                "type": "tool.execution_start",
                "data": {
                    "toolCallId": "call1",
                    "toolName": "read_file",
                    "arguments": {},
                    "turnId": "0",
                    "model": "gpt-5.6-luna",
                },
                "id": "e3",
                "timestamp": "2026-01-01T00:00:06.000Z",
                "parentId": "e2",
            },
            {
                "type": "tool.execution_complete",
                "data": {
                    "toolCallId": "call1",
                    "model": "gpt-5.6-luna",
                    "success": True,
                    "result": {"content": "ok"},
                },
                "id": "e4",
                "timestamp": "2026-01-01T00:00:07.000Z",
                "parentId": "e3",
            },
            {
                "type": "session.shutdown",
                "data": {
                    "shutdownType": "routine",
                    "totalPremiumRequests": 0,
                    "totalNanoAiu": 100_000_000,
                    "totalApiDurationMs": 5_000,
                    "sessionStartTime": 1767225600000,
                    "modelMetrics": {
                        "gpt-5.6-luna": {
                            "requests": {"count": 1, "cost": 0},
                            "usage": {
                                "inputTokens": 1000,
                                "outputTokens": 100,
                                "cacheReadTokens": 0,
                                "cacheWriteTokens": 0,
                                "reasoningTokens": 0,
                            },
                            "totalNanoAiu": 100_000_000,
                        }
                    },
                    "currentModel": "gpt-5.6-luna",
                },
                "id": "e5",
                "timestamp": "2026-01-01T00:00:10.000Z",
                "parentId": "e4",
            },
        ]

    lines = [json.dumps(event) for event in events]
    (session_dir / "events.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")

    if workspace is None:
        workspace = {
            "id": session_id,
            "cwd": "/proj",
            "git_root": "/proj",
            "branch": "main",
            "client_name": "github/autopilot",
            "user_named": True,
            "name": "Test CLI Session",
            "summary_count": 1,
            "created_at": "2026-01-01T00:00:00.000Z",
            "updated_at": "2026-01-01T00:00:10.000Z",
        }
    if workspace:
        yaml_lines = []
        for key, value in workspace.items():
            if isinstance(value, str):
                yaml_lines.append(f'{key}: "{value}"')
            else:
                yaml_lines.append(f"{key}: {value}")
        (session_dir / "workspace.yaml").write_text("\n".join(yaml_lines) + "\n", encoding="utf-8")

    return session_dir


@pytest.fixture
def write_cli_session():
    """Expose the module-level session-writing helper as a fixture."""
    return _write_cli_session
