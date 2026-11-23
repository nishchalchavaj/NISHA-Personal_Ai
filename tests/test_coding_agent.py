import json
import sys

import pytest

from nisha.errors import NishaError


def configure_project(core, path, name="Sample", aliases=None):
    path.mkdir(parents=True, exist_ok=True)
    core.connections.save(
        json.dumps(
            {
                "projects": [
                    {
                        "name": name,
                        "aliases": aliases or [],
                        "folder": str(path.resolve()),
                    }
                ],
                "default_project": name,
            }
        )
    )


def test_project_inspection_limits_paths_and_omits_private_files(core, tmp_path):
    project = tmp_path / "project"
    configure_project(core, project, aliases=["demo"])
    (project / "src").mkdir()
    (project / "src" / "app.py").write_text(
        'VALUE = 1\nPASSWORD = "private-value"\n', encoding="utf-8"
    )
    (project / ".env").write_text("TOKEN=do-not-read", encoding="utf-8")
    (project / "credentials.json").write_text("{}", encoding="utf-8")
    (project / "src" / "app.py").with_suffix(".key").write_text("private", encoding="utf-8")

    assert core.coding.list_files("demo") == ["src\\app.py"]
    source = core.coding.read_file("Sample", "src/app.py")["content"]
    assert "VALUE = 1" in source and "private-value" not in source
    assert "[REDACTED]" in source
    assert core.coding.search("Sample", "PASSWORD")[0]["text"].endswith("[REDACTED]")
    assert core.coding.search("Sample", "VALUE")[0]["path"] == "src\\app.py"
    with pytest.raises(NishaError):
        core.coding.read_file("Sample", "../outside.py")
    with pytest.raises(NishaError):
        core.coding.read_file("Sample", ".env")


def test_coding_proposal_is_saved_for_review_and_never_applied(core, tmp_path):
    project = tmp_path / "project"
    configure_project(core, project)
    source = project / "app.py"
    source.write_text("VALUE = 1\n", encoding="utf-8")
    core.generate_content = lambda *_args, **_kwargs: (
        "--- a/app.py\n+++ b/app.py\n@@ -1 +1 @@\n-VALUE = 1\n+VALUE = 2"
    )
    result = core.coding.propose(
        "Change VALUE to 2", "Sample", ["app.py"], core, core.new_session()
    )
    assert result["status"] == "review_required"
    assert result["applied"] is False and result["tests_run"] is False
    assert source.read_text(encoding="utf-8") == "VALUE = 1\n"
    assert (tmp_path / "coding_candidates" / f"{result['candidate_id']}.patch").is_file()


def test_coding_proposal_rejects_unselected_or_sensitive_patch_paths(core, tmp_path):
    project = tmp_path / "project"
    configure_project(core, project)
    (project / "app.py").write_text("VALUE = 1\n", encoding="utf-8")
    core.generate_content = lambda *_args, **_kwargs: (
        "--- a/.env\n+++ b/.env\n@@ -1 +1 @@\n-TOKEN=x\n+TOKEN=y"
    )
    with pytest.raises(NishaError, match="safe project scope"):
        core.coding.propose(
            "Change config", "Sample", ["app.py"], core, core.new_session()
        )
    assert not list((tmp_path / "coding_candidates").glob("*.patch"))


def test_fixed_pytest_verification_emits_complete_bounded_receipt(core, tmp_path):
    project = tmp_path / "project"
    configure_project(core, project)
    tests = project / "tests"
    tests.mkdir()
    (tests / "test_sample.py").write_text("def test_ok():\n    assert 2 + 2 == 4\n", encoding="utf-8")

    receipt = core.coding.verify("Sample", "pytest")
    assert receipt["command"] == (sys.executable, "-m", "pytest", "-q")
    assert receipt["working_directory"] == str(project.resolve())
    assert receipt["start_time"] and receipt["end_time"]
    assert receipt["exit_code"] == 0 and not receipt["timed_out"]
    assert "1 passed" in receipt["stdout"]
    log = tmp_path / "reports" / "coding-commands.jsonl"
    event = json.loads(log.read_text(encoding="utf-8").splitlines()[-1])
    assert event["suite"] == "pytest" and event["exit_code"] == 0


def test_failed_pytest_is_reported_as_failure(core, tmp_path):
    project = tmp_path / "project"
    configure_project(core, project)
    tests = project / "tests"
    tests.mkdir()
    (tests / "test_failure.py").write_text(
        "def test_failure():\n    assert 1 == 2\n", encoding="utf-8"
    )
    receipt = core.coding.verify("Sample", "pytest")
    assert receipt["exit_code"] != 0
    assert not receipt["timed_out"]
    assert "1 failed" in receipt["stdout"]


def test_pytest_timeout_returns_a_failure_receipt(core, tmp_path):
    project = tmp_path / "project"
    configure_project(core, project)
    tests = project / "tests"
    tests.mkdir()
    (tests / "test_sample.py").write_text("def test_ok():\n    assert True\n", encoding="utf-8")
    core.coding.timeout = 0.001
    receipt = core.coding.verify("Sample", "pytest")
    assert receipt["timed_out"]
    assert receipt["exit_code"] != 0


def test_verification_suite_is_allowlisted(core, tmp_path):
    project = tmp_path / "project"
    configure_project(core, project)
    with pytest.raises(NishaError, match="supported"):
        core.coding.verify("Sample", "powershell -Command Remove-Item")


def test_project_commands_are_voice_routable_and_report_receipts(core, tmp_path):
    from nisha.responsiveness import action_request

    project = tmp_path / "project"
    configure_project(core, project)
    (project / "app.py").write_text("VALUE = 1\n", encoding="utf-8")
    receipt = {
        "timed_out": False,
        "exit_code": 0,
        "duration_seconds": 0.25,
        "stdout": "3 passed",
        "stderr": "",
    }
    calls = []
    core.coding.verify = lambda name, suite: calls.append((name, suite)) or receipt
    assert action_request("Nisha, run the tests")
    reply = core.handle_action("run the tests", core.new_session(), [], "local_fast")
    assert "Pytest passed for Sample" in reply and "3 passed" in reply
    assert calls == [("Sample", "pytest")]
    assert "app.py" in core.handle_action(
        "inspect project Sample", core.new_session(), [], "local_fast"
    )
    assert "VALUE = 1" in core.handle_action(
        "search project Sample for VALUE", core.new_session(), [], "local_fast"
    )
