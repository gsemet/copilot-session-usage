"""Tests for the release-note generation command."""

import runpy
import subprocess
from pathlib import Path
from typing import Any

import pytest
from _pytest.monkeypatch import MonkeyPatch

SCRIPT = (
    Path(__file__).parents[1]
    / ".github"
    / "skills"
    / "gh-release-notes"
    / "scripts"
    / "generate_release_notes.py"
)
MODULE: dict[str, Any] = runpy.run_path(str(SCRIPT))
build_copilot_command = MODULE["build_copilot_command"]
build_parser = MODULE["build_parser"]
build_git_context = MODULE["build_git_context"]
build_prompt = MODULE["build_prompt"]
resolve_path = MODULE["resolve_path"]
require_copilot_token = MODULE["require_copilot_token"]
validate_output = MODULE["validate_output"]


def test_build_copilot_command_uses_explicit_model_when_provided() -> None:
    """Include the model flag when a model identifier is requested."""
    command = build_copilot_command("release prompt", "gpt-5.5")

    assert command[:3] == ["gh", "copilot", "--"]
    assert command[command.index("--model") + 1] == "gpt-5.5"
    assert "--prompt" in command
    assert "release prompt" in command


def test_build_copilot_command_leaves_model_selection_to_cli_when_unset() -> None:
    """Do not force a model when the caller requests the CLI default."""
    command = build_copilot_command("release prompt", None)

    assert "--model" not in command


def test_parser_uses_generic_git_ref_arguments() -> None:
    """Expose from-ref/to-ref rather than incorrectly limiting inputs to tags."""
    args = build_parser().parse_args(["--from-ref", "main", "--to-ref", "HEAD"])

    assert args.from_ref == "main"
    assert args.to_ref == "HEAD"


def test_build_prompt_contains_generic_execution_contract() -> None:
    """Keep the prompt as orchestration and leave release-note policy to the skill."""
    prompt = build_prompt("v0.6.7", "v0.6.8", Path("/tmp/project"), Path("/tmp/notes.md"))

    assert "v0.6.7..v0.6.8" in prompt
    assert "Use the /gh-release-notes skill" in prompt
    assert "skill is authoritative" in prompt
    assert str(Path("/tmp/notes.md")) in prompt
    assert "See the [pricing reference for details]" in prompt
    assert "never as a bare URL" in prompt
    assert "omit Maintenance" in prompt
    assert len(prompt) < 1_000


def test_build_prompt_includes_precomputed_git_evidence() -> None:
    """Give sandboxed Copilot execution the local range evidence it cannot discover."""
    prompt = build_prompt(
        "v0.6.8",
        "v0.7.0",
        Path("/tmp/project"),
        Path("/tmp/notes.md"),
        "Commit log\nabc123 feat: useful change\n\nUser-facing diff\n+new behavior",
    )

    assert "<git-evidence>" in prompt
    assert "abc123 feat: useful change" in prompt
    assert "authoritative input" in prompt
    assert "starting ref is excluded" in prompt


def test_resolve_path_keeps_absolute_paths_and_resolves_relative_paths() -> None:
    """Resolve output files relative to the selected repository."""
    repo = Path("/tmp/project")

    assert resolve_path(Path("notes.md"), repo) == repo / "notes.md"
    assert resolve_path(Path("/tmp/notes.md"), repo) == Path("/tmp/notes.md")


def test_build_git_context_collects_log_and_user_facing_diff(monkeypatch: MonkeyPatch) -> None:
    """Build the Copilot context from the exact requested range and exclusions."""
    calls: list[tuple[str, ...]] = []

    def fake_subprocess_run(
        command: list[str],
        *,
        cwd: Path,
        check: bool,
        capture_output: bool,
        text: bool,
    ) -> subprocess.CompletedProcess[str]:
        del cwd, check, capture_output, text
        arguments = tuple(command[1:])
        calls.append(arguments)
        if arguments[0] == "log":
            stdout = "abc123 feat: useful change\n"
        elif arguments[1] == "--stat":
            stdout = "src/example.py | 1 +\n"
        else:
            stdout = "diff --git a/src/example.py b/src/example.py\n+new behavior\n"
        return subprocess.CompletedProcess(command, 0, stdout, "")

    monkeypatch.setattr(MODULE["subprocess"], "run", fake_subprocess_run)

    context = build_git_context(Path("/tmp/project"), "v0.6.8", "v0.7.0")

    assert "abc123 feat: useful change" in context
    assert "+new behavior" in context
    assert calls[0][:3] == ("log", "--format=%h %s", "--no-merges")
    assert calls[1] == ("diff", "--stat", "--no-ext-diff", "v0.6.8..v0.7.0")
    assert calls[2] == ("diff", "--no-ext-diff", "--unified=3", "v0.6.8..v0.7.0")


def test_require_copilot_token_accepts_either_supported_environment_variable(
    monkeypatch: MonkeyPatch,
) -> None:
    """Allow both the CI-specific and standard GitHub token names."""
    monkeypatch.delenv("COPILOT_GITHUB_TOKEN", raising=False)
    monkeypatch.setenv("GH_TOKEN", "test-token")

    require_copilot_token()


def test_require_copilot_token_fails_without_authentication(monkeypatch: MonkeyPatch) -> None:
    """Explain how to configure authentication before invoking Copilot."""
    monkeypatch.delenv("COPILOT_GITHUB_TOKEN", raising=False)
    monkeypatch.delenv("GH_TOKEN", raising=False)

    with pytest.raises(RuntimeError, match="COPILOT_GITHUB_TOKEN or GH_TOKEN"):
        require_copilot_token()


def test_validate_output_preserves_skill_authored_markdown(tmp_path: Path) -> None:
    """Verify the output file without rewriting the skill's Markdown."""
    output = tmp_path / "release-notes.md"
    content = "preamble\n\n## Enhancements\n\nA useful change.\n"
    output.write_text(content, encoding="utf-8")

    validate_output(output)

    assert output.read_text(encoding="utf-8") == content


def test_validate_output_accepts_markdown_without_interpreting_it(tmp_path: Path) -> None:
    """Leave content decisions to the skill rather than rejecting unfamiliar headings."""
    output = tmp_path / "release-notes.md"
    output.write_text("Generated title\n\nNo release section.", encoding="utf-8")

    validate_output(output)


def test_validate_output_accepts_maintenance_release_notes(tmp_path: Path) -> None:
    """Verify maintenance output without special-casing it in the generator."""
    output = tmp_path / "release-notes.md"
    output.write_text(
        """## Maintenance
This release contains maintenance and internal improvements. No user-facing behavior changed.
""",
        encoding="utf-8",
    )

    validate_output(output)

    assert output.read_text(encoding="utf-8").startswith("## Maintenance\n")
