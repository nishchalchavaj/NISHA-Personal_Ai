import json

import pytest

from nisha.errors import NishaError


def configure_project(core, path):
    path.mkdir(parents=True, exist_ok=True)
    core.connections.save(
        json.dumps({
            "projects": [{"name": "Terminal fixture", "folder": str(path.resolve())}],
            "default_project": "Terminal fixture",
        })
    )


def test_python_command_requires_one_use_approval_and_uses_configured_sandbox_runner(core, tmp_path):
    project = tmp_path / "project"
    configure_project(core, project)
    prepared = core.terminal.prepare(
        "python", "Terminal fixture", args=["-c", "print('terminal-ok')"]
    )

    assert prepared["status"] == "approval_required"
    assert prepared["requires_confirmation"] is True
    assert prepared["risk"] == "level_2_code"
    assert prepared["working_directory"] == str(project.resolve())
    assert prepared["limits"]["sandbox_memory_bytes"] > 0
    assert prepared["limits"]["network"] == "disabled"
    result = core.terminal.execute(prepared["approval_id"], True)

    assert result["exit_code"] == 0
    assert "terminal-ok" in result["stdout"]
    assert result["isolation"]["sandbox"] == "test-only process double"
    assert result["isolation"]["network"] is False
    with pytest.raises(NishaError, match="expired or was already used"):
        core.terminal.execute(prepared["approval_id"], True)


@pytest.mark.parametrize(
    ("shell", "script", "expected"),
    [
        ("powershell", "Write-Output 'powershell-ok'", "powershell-ok"),
        ("cmd", "echo cmd-ok", "cmd-ok"),
    ],
)
def test_approved_powershell_and_cmd_scripts_execute(core, tmp_path, shell, script, expected):
    project = tmp_path / shell
    configure_project(core, project)
    prepared = core.terminal.prepare(shell, "Terminal fixture", script=script)
    result = core.terminal.execute(prepared["approval_id"], True)

    assert result["exit_code"] == 0
    assert expected in result["stdout"]
    assert result["approved"] is True


def test_terminal_blocks_destructive_commands_and_secret_literals(core, tmp_path):
    project = tmp_path / "project"
    configure_project(core, project)
    with pytest.raises(NishaError, match="destructive or policy-bypass"):
        core.terminal.prepare(
            "powershell", "Terminal fixture", script="Format-Volume -DriveLetter C"
        )
    with pytest.raises(NishaError, match="credentials"):
        core.terminal.prepare(
            "cmd", "Terminal fixture", script="echo password=literal-secret"
        )


def test_terminal_commands_require_a_configured_project_and_single_command_form(core, tmp_path):
    project = tmp_path / "project"
    configure_project(core, project)
    with pytest.raises(NishaError, match="configured project"):
        core.terminal.prepare("python", "Unknown", args=["--version"])
    with pytest.raises(NishaError, match="either an argument list or a shell script"):
        core.terminal.prepare("python", "Terminal fixture", args=["--version"], script="echo")


def test_terminal_timeout_stops_approved_sandbox_command(core, tmp_path):
    project = tmp_path / "project"
    configure_project(core, project)
    core.terminal.timeout = 1
    prepared = core.terminal.prepare(
        "python", "Terminal fixture", args=["-c", "import time; time.sleep(10)"]
    )

    result = core.terminal.execute(prepared["approval_id"], True)

    assert result["timed_out"] is True
    assert result["exit_code"] == 124
    assert result["isolation"]["sandbox"] == "test-only process double"


def test_terminal_blocks_git_network_commands(core, tmp_path):
    configure_project(core, tmp_path / "project")
    with pytest.raises(NishaError, match="network commands are blocked"):
        core.terminal.prepare("git", "Terminal fixture", args=["push"])


def test_terminal_stop_and_patch_review_are_local_and_validated(core, tmp_path):
    patch_id = "a" * 32
    patch_dir = tmp_path / "reports" / "terminal-patches"
    patch_dir.mkdir(parents=True)
    (patch_dir / f"{patch_id}.patch").write_text(
        "diff --git a/file.py b/file.py\n+token=private-value\n", encoding="utf-8"
    )
    assert core.terminal.stop()["status"] == "no_active_sandbox_command"
    patch = core.terminal.read_patch(patch_id)
    assert patch["patch_id"] == patch_id
    assert "private-value" not in patch["patch"]
    with pytest.raises(NishaError, match="patch id is invalid"):
        core.terminal.read_patch("../secret")
