"""Tests for the release-note generation command."""

import json
import runpy
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
from _pytest.monkeypatch import MonkeyPatch
from ruamel.yaml import YAML

SCRIPT = (
    Path(__file__).parents[1]
    / ".github"
    / "skills"
    / "gh-release-notes"
    / "scripts"
    / "generate_release_notes.py"
)
MODULE: dict[str, Any] = runpy.run_path(str(SCRIPT))
DEFAULT_OUTPUT = Path("release-notes.md")
build_copilot_command = MODULE["build_copilot_command"]
build_parser = MODULE["build_parser"]
build_git_context = MODULE["build_git_context"]
build_prompt = MODULE["build_prompt"]
resolve_path = MODULE["resolve_path"]
require_copilot_token = MODULE["require_copilot_token"]
validate_output = MODULE["validate_output"]
run_copilot = MODULE["run_copilot"]
parse_copilot_response = MODULE["parse_copilot_response"]
generate_release_notes = MODULE["generate_release_notes"]


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
    assert "--available-tools=view,glob,grep,bash,skill" in command
    assert "--available-tools=read,create,edit,bash" not in command
    assert "--allow-tool=read" in command
    assert "--allow-tool=write" not in command
    assert command[command.index("--output-format") + 1] == "json"
    assert "--allow-tool=shell(git:*)" in command
    assert "--allow-all-tools" not in command
    assert not any(argument.startswith("--allow-url=") for argument in command)


def test_parser_uses_generic_git_ref_arguments() -> None:
    """Expose from-ref/to-ref rather than incorrectly limiting inputs to tags."""
    args = build_parser().parse_args(["--from-ref", "main", "--to-ref", "HEAD"])

    assert args.from_ref == "main"
    assert args.to_ref == "HEAD"
    assert args.maintenance_only is False


def test_parser_accepts_explicit_maintenance_only_mode() -> None:
    """Expose the deterministic mode used for forced internal-only releases."""
    args = build_parser().parse_args(
        ["--from-ref", "main", "--to-ref", "HEAD", "--maintenance-only"]
    )

    assert args.maintenance_only is True


def test_build_prompt_contains_generic_execution_contract() -> None:
    """Keep the prompt as orchestration and leave release-note policy to the skill."""
    prompt = build_prompt("v0.6.7", "v0.6.8", Path("/tmp/project"), Path("/tmp/notes.md"))

    assert "v0.6.7..v0.6.8" in prompt
    assert "Use the /gh-release-notes skill" in prompt
    assert "skill is authoritative" in prompt
    assert str(Path("/tmp/notes.md")) in prompt
    assert f"file {Path('/tmp/notes.md')}" in prompt
    assert "Return ONLY the complete" in prompt
    assert "structured final_answer" in prompt
    assert "Do not create or edit any files" in prompt
    assert "See the [pricing reference for details]" in prompt
    assert "never as a bare URL" in prompt
    assert "omit Maintenance" in prompt
    assert "closest verified documentation link" in prompt
    assert "do not repeat it" in prompt
    assert len(prompt) < 1_600


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
    """Keep all paths available because product boundaries differ across repositories."""
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
    assert "the skill determines user impact, not directory names" in context
    assert context.index("+new behavior") < context.index("Commit log:")


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


def test_run_copilot_returns_only_structured_final_answer(
    monkeypatch: MonkeyPatch, tmp_path: Path
) -> None:
    """Separate the final Markdown from the CLI's progress, tool, and usage events."""

    def fake_subprocess_run(*args: Any, **kwargs: Any) -> subprocess.CompletedProcess[str]:
        del args, kwargs
        return subprocess.CompletedProcess(
            ["gh", "copilot"],
            0,
            "\n".join(
                json.dumps(event)
                for event in [
                    {
                        "type": "assistant.message",
                        "data": {"phase": "commentary", "content": "Reading changes."},
                    },
                    {"type": "tool.execution_complete", "data": {"result": "not notes"}},
                    {"type": "assistant.message_delta", "data": {"deltaContent": "##"}},
                    {
                        "type": "assistant.message",
                        "data": {
                            "phase": "final_answer",
                            "content": "## Enhancements\n\n- Useful change.\n",
                            "toolRequests": [],
                        },
                    },
                    {"type": "result", "exitCode": 0},
                ]
            ),
            "",
        )

    monkeypatch.setattr(MODULE["subprocess"], "run", fake_subprocess_run)

    assert run_copilot(tmp_path, "release prompt", None) == (
        "## Enhancements\n\n- Useful change.\n"
    )


@pytest.mark.parametrize(
    "mode", ["response", "retry", "exhausted", "trace", "cli_error", "partial_file"]
)
def test_generate_release_notes_recovers_only_valid_output(
    monkeypatch: MonkeyPatch, tmp_path: Path, mode: str
) -> None:
    """Recover missing artifacts without publishing explanations or fabricated maintenance."""
    function_globals = generate_release_notes.__globals__
    monkeypatch.setitem(function_globals, "validate_range", lambda *args: None)
    monkeypatch.setitem(function_globals, "range_has_commits", lambda *args: True)
    monkeypatch.setitem(function_globals, "require_copilot_token", lambda: None)
    monkeypatch.setitem(function_globals, "run_skill_check", lambda *args: None)
    monkeypatch.setitem(function_globals, "build_git_context", lambda *args: "git evidence")
    calls: list[str] = []
    content = "## Bug Fixes\n\n- Fixed session discovery.\n"

    def fake_run_copilot(repo: Path, prompt: str, model: str | None) -> str:
        del model
        calls.append(prompt)
        output = repo / DEFAULT_OUTPUT
        assert output.read_text(encoding="utf-8") == ""
        if mode == "response":
            return content
        if mode == "cli_error" and len(calls) == 1:
            raise RuntimeError("temporary CLI failure")
        if mode == "partial_file" and len(calls) == 1:
            output.write_text("## New Features\n", encoding="utf-8")
            return "File written."
        if mode == "exhausted" or len(calls) == 1:
            return "## Bug Fixes\n\nto=bash.exec code" if mode == "trace" else "Done."
        assert "previous attempt failed validation" in prompt
        return content

    monkeypatch.setitem(function_globals, "run_copilot", fake_run_copilot)
    if mode == "exhausted":
        with pytest.raises(RuntimeError, match="failed after 3 attempts"):
            generate_release_notes(tmp_path, "v0.1.0", "v0.2.0", DEFAULT_OUTPUT, None)
        assert len(calls) == 3
        assert (tmp_path / DEFAULT_OUTPUT).read_text(encoding="utf-8") == ""
    else:
        generate_release_notes(tmp_path, "v0.1.0", "v0.2.0", DEFAULT_OUTPUT, None)
        assert len(calls) == (1 if mode == "response" else 2)
        assert (tmp_path / DEFAULT_OUTPUT).read_text(encoding="utf-8") == content


def test_generate_release_notes_persists_valid_final_answer(
    monkeypatch: MonkeyPatch, tmp_path: Path
) -> None:
    """Persist the validated final answer at the exact requested output path."""
    repo = tmp_path / "repo"
    repo.mkdir()
    function_globals = generate_release_notes.__globals__
    monkeypatch.setitem(function_globals, "validate_range", lambda *args: None)
    monkeypatch.setitem(function_globals, "range_has_commits", lambda *args: True)
    monkeypatch.setitem(function_globals, "require_copilot_token", lambda: None)
    monkeypatch.setitem(function_globals, "run_skill_check", lambda *args: None)
    monkeypatch.setitem(function_globals, "build_git_context", lambda *args: "git evidence")

    def fake_run_copilot(repo_arg: Path, prompt: str, model: str | None) -> str:
        del repo_arg, prompt, model
        return "## Enhancements\n\n- Useful change.\n"

    monkeypatch.setitem(function_globals, "run_copilot", fake_run_copilot)

    generate_release_notes(repo, "v0.1.0", "v0.2.0", Path("release-notes.md"), None)

    assert (repo / "release-notes.md").read_text(encoding="utf-8") == (
        "## Enhancements\n\n- Useful change.\n"
    )


def test_generate_release_notes_clears_stale_output_before_generation(
    monkeypatch: MonkeyPatch, tmp_path: Path
) -> None:
    """Never mistake a stale artifact for successful generation."""
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "release-notes.md").write_text("old release notes", encoding="utf-8")
    function_globals = generate_release_notes.__globals__
    monkeypatch.setitem(function_globals, "validate_range", lambda *args: None)
    monkeypatch.setitem(function_globals, "range_has_commits", lambda *args: True)
    monkeypatch.setitem(function_globals, "require_copilot_token", lambda: None)
    monkeypatch.setitem(function_globals, "run_skill_check", lambda *args: None)
    monkeypatch.setitem(function_globals, "build_git_context", lambda *args: "git evidence")

    def fake_run_copilot(repo_arg: Path, prompt: str, model: str | None) -> str:
        del prompt, model
        assert (repo_arg / "release-notes.md").read_text(encoding="utf-8") == ""
        return "## Maintenance\n\nNo user-facing behavior changed.\n"

    monkeypatch.setitem(function_globals, "run_copilot", fake_run_copilot)

    generate_release_notes(repo, "v0.1.0", "v0.2.0", Path("release-notes.md"), None)


def test_generate_release_notes_writes_maintenance_notes_for_empty_range(
    monkeypatch: MonkeyPatch, tmp_path: Path
) -> None:
    """Handle forced maintenance releases without requiring a Copilot request."""
    repo = tmp_path / "repo"
    repo.mkdir()
    function_globals = generate_release_notes.__globals__
    monkeypatch.setitem(function_globals, "validate_range", lambda *args: None)
    monkeypatch.setitem(function_globals, "range_has_commits", lambda *args: False)
    monkeypatch.setitem(
        function_globals,
        "require_copilot_token",
        lambda: pytest.fail("empty release ranges should not require Copilot authentication"),
    )
    monkeypatch.setitem(
        function_globals,
        "run_copilot",
        lambda *args: pytest.fail("empty release ranges should not invoke Copilot"),
    )

    generate_release_notes(repo, "v0.1.0", "v0.1.1", Path("release-notes.md"), None)

    assert (repo / "release-notes.md").read_text(encoding="utf-8") == (
        "## Maintenance\n\n"
        "This release contains maintenance and internal improvements. "
        "No user-facing behavior changed.\n"
    )


def test_generate_release_notes_writes_maintenance_notes_when_requested(
    monkeypatch: MonkeyPatch, tmp_path: Path
) -> None:
    """Skip Copilot for a non-empty range explicitly classified as maintenance-only."""
    repo = tmp_path / "repo"
    repo.mkdir()
    function_globals = generate_release_notes.__globals__
    monkeypatch.setitem(function_globals, "validate_range", lambda *args: None)
    monkeypatch.setitem(function_globals, "range_has_commits", lambda *args: True)
    monkeypatch.setitem(
        function_globals,
        "require_copilot_token",
        lambda: pytest.fail("maintenance-only releases should not require Copilot authentication"),
    )
    monkeypatch.setitem(
        function_globals,
        "run_copilot",
        lambda *args: pytest.fail("maintenance-only releases should not invoke Copilot"),
    )

    generate_release_notes(
        repo,
        "v0.1.0",
        "v0.1.1",
        Path("release-notes.md"),
        None,
        maintenance_only=True,
    )

    assert (repo / "release-notes.md").read_text(encoding="utf-8") == (
        "## Maintenance\n\n"
        "This release contains maintenance and internal improvements. "
        "No user-facing behavior changed.\n"
    )


def test_validate_output_preserves_skill_authored_markdown(tmp_path: Path) -> None:
    """Verify the output file without rewriting the skill's Markdown."""
    output = tmp_path / "release-notes.md"
    content = "## Enhancements\n\n- A useful change.\n"
    output.write_text(content, encoding="utf-8")

    validate_output(output)

    assert output.read_text(encoding="utf-8") == content


def test_validate_output_accepts_markdown_without_interpreting_it(tmp_path: Path) -> None:
    """Reject output that does not start with a permitted release-note section."""
    output = tmp_path / "release-notes.md"
    output.write_text("Generated title\n\nNo release section.", encoding="utf-8")

    with pytest.raises(RuntimeError, match="permitted section headings"):
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


def test_run_copilot_reports_bounded_timeout(monkeypatch: MonkeyPatch, tmp_path: Path) -> None:
    """Convert a hanging CLI into a retryable, actionable failure."""

    def fake_run(command: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        assert kwargs["timeout"] == 300
        raise subprocess.TimeoutExpired(command, 300)

    monkeypatch.setattr(MODULE["subprocess"], "run", fake_run)

    with pytest.raises(RuntimeError, match="timed out after 300 seconds"):
        run_copilot(tmp_path, "prompt", None)


@pytest.mark.parametrize(
    "events, message",
    [
        ("not JSON", "invalid JSONL"),
        ("[]", "non-object"),
        (json.dumps({"type": "result", "exitCode": 1}), "unsuccessful result"),
        (json.dumps({"type": "result", "exitCode": 0}), "no final-answer"),
        (
            json.dumps(
                {"type": "assistant.message", "data": {"phase": "final_answer", "content": "notes"}}
            ),
            "no successful result",
        ),
        (
            json.dumps(
                {"type": "assistant.message", "data": {"phase": "final_answer", "content": None}}
            ),
            "must be a string",
        ),
    ],
)
def test_parse_copilot_response_rejects_invalid_transport(events: str, message: str) -> None:
    """Reject malformed, incomplete, or failed streams rather than scraping them."""
    with pytest.raises(RuntimeError, match=message):
        parse_copilot_response(events)


def test_large_git_context_preserves_complete_summary(monkeypatch: MonkeyPatch) -> None:
    """Keep all changed paths discoverable when the product diff exceeds the prompt budget."""
    function_globals = build_git_context.__globals__
    monkeypatch.setitem(function_globals, "MAX_GIT_CONTEXT_LENGTH", 500)

    def fake_git_output(repo: Path, description: str, *args: str) -> str:
        del repo, args
        if description == "diff":
            return "feature evidence\n" * 100
        if description == "diff summary":
            return "src/first.py | 10 +\nsrc/last.py | 10 +"
        return "feat: add capabilities"

    monkeypatch.setitem(function_globals, "git_output", fake_git_output)

    context = build_git_context(Path("/tmp/project"), "v0.1.0", "v0.2.0")

    assert "feature evidence" in context
    assert "this excerpt is incomplete" in context
    assert "src/last.py" in context


@pytest.mark.parametrize("kind", ["empty", "maintenance", "fix", "docs", "feature"])
def test_generate_release_notes_with_real_git_ranges(
    monkeypatch: MonkeyPatch, tmp_path: Path, kind: str
) -> None:
    """Exercise real range validation and evidence collection for representative releases."""
    repo = tmp_path / "repo"
    repo.mkdir()

    def run_git(*arguments: str) -> None:
        subprocess.run(["git", *arguments], cwd=repo, check=True, capture_output=True, text=True)

    run_git("init")
    run_git("config", "user.name", "Release Test")
    run_git("config", "user.email", "release@example.com")
    run_git("config", "commit.gpgsign", "false")
    (repo / "product.txt").write_text("baseline\n", encoding="utf-8")
    run_git("add", ".")
    run_git("commit", "-m", "feat: baseline")
    run_git("tag", "v0.1.0")
    if kind != "empty":
        changed = repo / (".github/automation.txt" if kind == "maintenance" else "product.txt")
        changed.parent.mkdir(parents=True, exist_ok=True)
        changed.write_text(f"{kind} outcome\n", encoding="utf-8")
        run_git("add", ".")
        run_git("commit", "-m", f"{'docs' if kind == 'docs' else 'chore'}: {kind} update")
    run_git("tag", "v0.2.0")
    output = tmp_path / "nested" / "custom-notes.md"
    function_globals = generate_release_notes.__globals__
    calls: list[str] = []
    monkeypatch.setitem(function_globals, "require_copilot_token", lambda: None)
    monkeypatch.setitem(function_globals, "run_skill_check", lambda *args: None)

    def fake_copilot(repo_arg: Path, prompt: str, model: str | None) -> str:
        del model
        assert repo_arg == repo
        calls.append(prompt)
        assert str(output) in prompt
        assert "v0.1.0..v0.2.0" in prompt
        if kind == "maintenance":
            assert "automation.txt" in prompt
            assert "+maintenance outcome" in prompt
            return MODULE["MAINTENANCE_NOTES"]
        assert f"+{kind} outcome" in prompt
        heading = {"fix": "Bug Fixes", "docs": "Documentation", "feature": "New Features"}[kind]
        return f"## {heading}\n\n- {kind} outcome. [Guide](https://example.com/guide).\n"

    monkeypatch.setitem(function_globals, "run_copilot", fake_copilot)

    generate_release_notes(repo, "v0.1.0", "v0.2.0", output, None)

    validate_output(output)
    assert len(calls) == (0 if kind == "empty" else 1)
    assert not (repo / DEFAULT_OUTPUT).exists()


def test_skill_runs_from_an_independent_installation(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    """Run a copied skill with isolated Python and no source-project dependencies."""
    installation = tmp_path / "installed-skills" / "gh-release-notes"
    shutil.copytree(SCRIPT.parents[1], installation, ignore=shutil.ignore_patterns("__pycache__"))
    repo = tmp_path / "unrelated-project"
    repo.mkdir()
    output = repo / "announcement.md"
    output.write_text(
        "## New Features\n- Export reports as PDF. "
        "[Export guide](https://docs.other-project.example/export).\n",
        encoding="utf-8",
    )

    result = subprocess.run(
        [
            sys.executable,
            "-I",
            str(installation / "scripts/generate_release_notes.py"),
            "--repo",
            str(repo),
            "--validate",
            "announcement.md",
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    monkeypatch.delenv("COPILOT_GITHUB_TOKEN", raising=False)
    monkeypatch.delenv("GH_TOKEN", raising=False)
    for arguments in [
        ["init"],
        [
            "-c",
            "user.name=Portable Test",
            "-c",
            "user.email=test@example.com",
            "-c",
            "commit.gpgsign=false",
            "commit",
            "--allow-empty",
            "-m",
            "Initial state",
        ],
        ["branch", "baseline"],
        ["branch", "release-candidate"],
    ]:
        subprocess.run(["git", *arguments], cwd=repo, check=True, capture_output=True, text=True)
    result = subprocess.run(
        [
            sys.executable,
            "-I",
            str(installation / "scripts/generate_release_notes.py"),
            "--repo",
            str(repo),
            "--from-ref",
            "baseline",
            "--to-ref",
            "release-candidate",
            "--output",
            "release-body.md",
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert (repo / "release-body.md").read_text(encoding="utf-8") == MODULE["MAINTENANCE_NOTES"]
    for resource in [installation / "SKILL.md", installation / "scripts/generate_release_notes.py"]:
        assert "copilot-session-usage" not in resource.read_text(encoding="utf-8")


def test_release_workflows_use_validated_notes_before_publication() -> None:
    """Keep both release entry points on the same generator without inferring impact from CZ."""
    root = SCRIPT.parents[4]
    yaml = YAML(typ="safe")
    for workflow_name, job_name, publish_step in [
        ("release.yml", "release", "Create GitHub release"),
        ("release-notes.yml", "generate-release-notes", "Create draft GitHub release"),
    ]:
        workflow = yaml.load((root / ".github/workflows" / workflow_name).read_text())
        steps = workflow["jobs"][job_name]["steps"]
        generate_index = next(
            index for index, step in enumerate(steps) if step["name"] == "Generate release notes"
        )
        publish_index = next(
            index for index, step in enumerate(steps) if step["name"] == publish_step
        )
        assert generate_index < publish_index
        generation = steps[generate_index]["run"]
        assert "scripts/generate_release_notes.py" in generation
        assert "--output release-notes.md" in generation
        assert "--maintenance-only" not in generation
        assert "MAINTENANCE_ONLY" not in steps[generate_index]["env"]
        assert "--notes-file release-notes.md" in steps[publish_index]["run"]
