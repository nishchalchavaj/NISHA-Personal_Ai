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


def test_python_command_requires_one_use_approval_and_runs_in_job_object(core, tmp_path):
    project = tmp_path / "project"
    configure_project(core, project)
    prepared = core.terminal.prepare(
        "python", "Terminal fixture", args=["-c", "print('terminal-ok')"]
    )

    assert prepared["status"] == "approval_required"
    assert prepared["requires_confirmation"] is True
    assert prepared["risk"] == "level_2_code"
    assert prepared["working_directory"] == str(project.resolve())
    assert prepared["limits"]["process_memory_bytes"] > 0
    result = core.terminal.execute(prepared["approval_id"], True)

    assert result["exit_code"] == 0
    assert "terminal-ok" in result["stdout"]
    assert result["process_job_limits"]["enabled"] is True
    assert result["process_job_limits"]["filesystem_or_network_restriction"] is False
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


def test_terminal_timeout_kills_approved_process_job(core, tmp_path):
    project = tmp_path / "project"
    configure_project(core, project)
    core.terminal.timeout = 1
    prepared = core.terminal.prepare(
        "python", "Terminal fixture", args=["-c", "import time; time.sleep(10)"]
    )

    result = core.terminal.execute(prepared["approval_id"], True)

    assert result["timed_out"] is True
    assert result["exit_code"] == 124
    assert result["process_job_limits"]["kill_process_tree_on_timeout_or_close"] is True
