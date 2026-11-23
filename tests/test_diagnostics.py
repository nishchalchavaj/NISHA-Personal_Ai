import json

from nisha.responsiveness import action_request


def test_local_research_returns_source_citations_not_unchecked_claims(core, tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    (project / "guide.md").write_text("The camera timeout is 12 seconds.\n", encoding="utf-8")
    core.connections.save(
        json.dumps({"projects": [{"name": "Camera", "folder": str(project.resolve())}]})
    )

    result = core.diagnostics.research("Camera", "camera timeout")

    assert result["scope"] == "configured project source and documentation only"
    assert result["evidence"]
    assert result["evidence"][0]["path"] == "guide.md"
    assert result["evidence"][0]["line"] == 1


def test_debug_and_self_analysis_report_receipts_and_redact_secrets(core, tmp_path):
    path = tmp_path / "reports" / "coding-commands.jsonl"
    path.parent.mkdir()
    event = json.dumps(
        {
                "suite": "pytest",
                "command": ["python", "-m", "pytest"],
                "working_directory": str(tmp_path),
                "start_time": "2026-11-24T00:00:00+00:00",
                "duration_seconds": 3.0,
                "exit_code": 1,
                "timed_out": False,
                "stdout": "PASSWORD=secret-value",
                "stderr": "AssertionError",
        }
    )
    path.write_text(event + "\n" + event + "\n", encoding="utf-8")

    debug = core.diagnostics.debug()
    analysis = core.diagnostics.analyze()

    assert debug["observations"][0]["observation"] == "pytest exited with code 1"
    assert "[REDACTED]" in debug["observations"][0]["evidence"]["stdout"]
    assert debug["hypotheses"] == []
    assert analysis["slow_commands_over_2_seconds"][0]["duration_seconds"] == 3.0
    assert analysis["repeated_failures"][0]["evidence_count"] == 2
    assert analysis["conclusions"] == []


def test_research_and_debug_actions_use_existing_action_routing(core, tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    (project / "readme.md").write_text("Memory retrieval uses SQLite.\n", encoding="utf-8")
    core.connections.save(
        json.dumps({"projects": [{"name": "Memory", "folder": str(project.resolve())}]})
    )

    assert action_request("Nisha, research project Memory for SQLite")
    answer = core.handle_action("research project Memory for SQLite", core.new_session(), [], "local_fast")
    assert "readme.md:1" in answer
    assert action_request("debug last failure")
