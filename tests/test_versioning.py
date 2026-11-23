import json
import subprocess
from pathlib import Path

import pytest

from nisha.errors import NishaError


def git(path, *args):
    return subprocess.run(
        ["git", "-C", str(path), *args],
        check=True,
        capture_output=True,
        text=True,
        shell=False,
    ).stdout.strip()


def git_project(core, tmp_path, name="Sample", test_content=None):
    root = tmp_path / "project"
    root.mkdir()
    git(root, "init", "-q")
    git(root, "config", "user.name", "NISHA tests")
    git(root, "config", "user.email", "nisha-tests@localhost")
    (root / "app.py").write_text("VALUE = 1\n", encoding="utf-8")
    (root / "tests").mkdir()
    (root / "tests" / "test_app.py").write_text(
        test_content or "from app import VALUE\n\n\ndef test_value():\n    assert VALUE == 2\n", encoding="utf-8"
    )
    git(root, "add", ".")
    git(root, "commit", "-qm", "stable baseline")
    core.connections.save(
        json.dumps(
            {
                "projects": [{"name": name, "folder": str(root.resolve())}],
                "default_project": name,
            }
        )
    )
    core.generate_content = lambda *_args, **_kwargs: (
        "--- a/app.py\n+++ b/app.py\n@@ -1 +1 @@\n-VALUE = 1\n+VALUE = 2"
    )
    proposal = core.coding.propose(
        "Make test pass", name, ["app.py"], core, core.new_session()
    )
    return root, proposal


def test_candidate_is_applied_and_verified_in_separate_worktree(core, tmp_path):
    stable, proposal = git_project(core, tmp_path)
    stable_commit = git(stable, "rev-parse", "HEAD")

    candidate = core.candidates.create(proposal["candidate_id"])

    assert candidate["status"] == "candidate_applied"
    assert candidate["base_commit"] == stable_commit
    assert (stable / "app.py").read_text(encoding="utf-8") == "VALUE = 1\n"
    assert (tmp_path / "experiments" / "worktrees" / candidate["experiment_id"] / "app.py").read_text(encoding="utf-8") == "VALUE = 2\n"

    result = core.candidates.verify(candidate["experiment_id"], "pytest")
    assert result["status"] == "verification_passed"
    assert result["baseline"]["exit_code"] != 0
    assert result["candidate"]["exit_code"] == 0
    assert core.candidates.list()[0]["tests"]["pytest"]["candidate"]["exit_code"] == 0
    assert git(stable, "rev-parse", "HEAD") == stable_commit


def test_candidate_refuses_tracked_dirty_worktree(core, tmp_path):
    stable, proposal = git_project(core, tmp_path)
    (stable / "app.py").write_text("VALUE = 999\n", encoding="utf-8")

    with pytest.raises(NishaError, match="tracked working changes"):
        core.candidates.create(proposal["candidate_id"])
    assert not (tmp_path / "experiments" / "worktrees" / proposal["candidate_id"]).exists()


def test_candidate_cannot_modify_tests_or_validation_configuration(core, tmp_path):
    _stable, _ = git_project(core, tmp_path)
    core.generate_content = lambda *_args, **_kwargs: (
        "--- a/tests/test_app.py\n+++ b/tests/test_app.py\n@@ -4 +4 @@\n-    assert VALUE == 2\n+    assert True"
    )
    proposal = core.coding.propose(
        "Disable the failing assertion", "Sample", ["tests/test_app.py"], core, core.new_session()
    )

    with pytest.raises(NishaError, match="cannot modify test suites"):
        core.candidates.create(proposal["candidate_id"])


def test_candidate_keeps_disjoint_untracked_user_data_out_of_patch(core, tmp_path):
    stable, proposal = git_project(core, tmp_path)
    private = stable / "trader"
    private.mkdir()
    (private / "keep.json").write_text("user data", encoding="utf-8")

    candidate = core.candidates.create(proposal["candidate_id"])

    assert (private / "keep.json").read_text(encoding="utf-8") == "user data"
    assert not (Path(candidate["worktree"]) / "trader").exists()


def test_reject_requires_reason_and_preserves_candidate_worktree(core, tmp_path):
    _stable, proposal = git_project(core, tmp_path)
    candidate = core.candidates.create(proposal["candidate_id"])
    with pytest.raises(NishaError, match="rejection reason"):
        core.candidates.reject(candidate["experiment_id"], " ")

    rejected = core.candidates.reject(candidate["experiment_id"], "Test requirement misunderstood")

    assert rejected["status"] == "rejected"
    assert Path(rejected["worktree"]).is_dir()


def test_promotion_requires_explicit_approval_and_rollback_reverts_by_commit(core, tmp_path):
    stable, proposal = git_project(
        core,
        tmp_path,
        test_content="def test_value():\n    assert 2 + 2 == 4\n",
    )
    candidate = core.candidates.create(proposal["candidate_id"])
    verification = core.candidates.verify(candidate["experiment_id"], "pytest")
    assert verification["status"] == "verification_passed"
    benchmark = core.candidates.benchmark(candidate["experiment_id"])
    assert benchmark["candidate_quality_passed"]
    assert benchmark["ready_for_human_review"]

    with pytest.raises(NishaError, match="explicit approval"):
        core.candidates.promote(candidate["experiment_id"], False, "PROMOTE")
    promoted = core.candidates.promote(candidate["experiment_id"], True, "PROMOTE")
    assert promoted["status"] == "promoted"
    assert (stable / "app.py").read_text(encoding="utf-8") == "VALUE = 2\n"

    rolled_back = core.candidates.rollback(candidate["experiment_id"], True, "ROLLBACK")
    assert rolled_back["status"] == "rolled_back"
    assert (stable / "app.py").read_text(encoding="utf-8") == "VALUE = 1\n"
    assert git(stable, "rev-parse", "HEAD") == rolled_back["version_state"]["current_stable_version"]


def test_restart_recovery_marks_isolated_interrupted_candidate_without_touching_stable(core, tmp_path):
    stable, proposal = git_project(core, tmp_path)
    base = git(stable, "rev-parse", "HEAD")
    candidate = core.candidates.create(proposal["candidate_id"])
    candidate["run_status"] = "active"
    candidate["operation"] = "candidate"
    core.candidates._write(candidate)

    recovered = core.candidates.recover_interrupted()

    assert recovered == [candidate["experiment_id"]]
    manifest = core.candidates._load(candidate["experiment_id"])
    assert manifest["status"] == "interrupted"
    assert "unchanged" in manifest["recovery"]
    assert git(stable, "rev-parse", "HEAD") == base


def test_restart_recovery_finishes_rollback_metadata_after_git_revert(core, tmp_path):
    stable, proposal = git_project(
        core,
        tmp_path,
        test_content="def test_value():\n    assert 2 + 2 == 4\n",
    )
    candidate = core.candidates.create(proposal["candidate_id"])
    core.candidates.verify(candidate["experiment_id"], "pytest")
    benchmark = core.candidates.benchmark(candidate["experiment_id"])
    assert benchmark["ready_for_human_review"]
    assert not benchmark["per_suite_latency_guard_applied"]["ruff"]
    core.candidates.promote(candidate["experiment_id"], True, "PROMOTE")
    manifest = core.candidates._load(candidate["experiment_id"])
    manifest["run_status"] = "active"
    manifest["operation"] = "rolling_back"
    core.candidates._write(manifest)
    git(
        stable,
        "-c", "user.name=Recovery Test",
        "-c", "user.email=recovery@localhost",
        "revert", "--no-edit", manifest["promotion_commit"],
    )

    assert core.candidates.recover_interrupted() == [candidate["experiment_id"]]

    recovered = core.candidates._load(candidate["experiment_id"])
    state_path = core.candidates.version_state_path(stable)
    state = json.loads(state_path.read_text(encoding="utf-8"))
    assert recovered["status"] == "rolled_back"
    assert state["current_stable_version"] == git(stable, "rev-parse", "HEAD")


def test_bounded_improvement_run_stops_at_human_review(core, tmp_path):
    git_project(core, tmp_path)

    result = core.improvement.run(
        "Make the test pass", "Sample", ["app.py"], core, core.new_session()
    )

    assert result["status"] == "ready_for_human_approval", result.get("benchmark")
    assert result["candidate"]["status"] == "benchmark_complete"
    assert result["candidate"]["promotion"] == "human_approval_required"
    assert result["benchmark"]["ready_for_human_review"]
    assert result["attempt_count"] == 1


def test_improvement_loop_retries_with_captured_failure_and_stops_on_pass(core, tmp_path):
    git_project(core, tmp_path)
    prompts = []
    patches = [
        "--- a/app.py\n+++ b/app.py\n@@ -1 +1 @@\n-VALUE = 1\n+VALUE = 3",
        "--- a/app.py\n+++ b/app.py\n@@ -1 +1 @@\n-VALUE = 1\n+VALUE = 2",
    ]

    def generated(prompt, *_args, **_kwargs):
        prompts.append(prompt)
        return patches.pop(0)

    core.generate_content = generated
    core.improvement.retry_limit = 2
    core.improvement.max_runtime_seconds = 90

    result = core.improvement.run(
        "Make the test pass", "Sample", ["app.py"], core, core.new_session()
    )

    assert result["status"] == "ready_for_human_approval"
    assert result["attempt_count"] == 2
    assert result["attempts"][0]["status"] == "rejected_verification"
    assert "Previous candidate failed" in prompts[1]
