"""Isolated Git candidates with durable manifests and no automatic promotion."""

import hashlib
import json
import re
import subprocess
from datetime import UTC, datetime
from functools import wraps
from pathlib import Path
from threading import RLock
from time import monotonic

from nisha.errors import NishaError

ID_PATTERN = re.compile(r"^[0-9a-f]{32}$")
VALIDATION_FILES = {
    "pyproject.toml",
    "pytest.ini",
    "tox.ini",
    "setup.cfg",
    "noxfile.py",
    "ruff.toml",
    ".ruff.toml",
}


def serialized(method):
    @wraps(method)
    def invoke(self, *args, **kwargs):
        with self._lock:
            return method(self, *args, **kwargs)

    return invoke


class CandidateManager:
    def __init__(self, coding, data_dir, store=None):
        self.coding = coding
        self.data_dir = Path(data_dir).resolve()
        self.store = store
        self._lock = RLock()
        self.experiments_dir = self.data_dir / "experiments"
        self.worktrees_dir = self.experiments_dir / "worktrees"
        self.experiments_dir.mkdir(parents=True, exist_ok=True)

    def _git(self, root, *args, check=True):
        try:
            result = subprocess.run(
                ["git", "-C", str(root), *args],
                stdin=subprocess.DEVNULL,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=30,
                shell=False,
                check=False,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise NishaError("Git couldn't complete the candidate operation.") from exc
        if check and result.returncode:
            raise NishaError("Git rejected the candidate operation: " + result.stderr[-1000:].strip())
        return result

    def _metadata(self, candidate_id):
        if not isinstance(candidate_id, str) or not ID_PATTERN.fullmatch(candidate_id):
            raise NishaError("That candidate ID is invalid.")
        path = self.coding.data_dir / "coding_candidates" / f"{candidate_id}.json"
        patch = path.with_suffix(".patch")
        try:
            metadata = json.loads(path.read_text(encoding="utf-8"))
            patch_text = patch.read_text(encoding="utf-8")
        except (OSError, ValueError) as exc:
            raise NishaError("The saved coding proposal is unavailable or invalid.") from exc
        if metadata.get("candidate_id") != candidate_id or metadata.get("status") != "review_required":
            raise NishaError("That coding proposal is not available for candidate creation.")
        return metadata, patch_text

    def _write(self, manifest):
        path = self.experiments_dir / f"{manifest['experiment_id']}.json"
        temporary = path.with_suffix(".json.tmp")
        temporary.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        temporary.replace(path)
        return path

    def _load(self, experiment_id):
        if not isinstance(experiment_id, str) or not ID_PATTERN.fullmatch(experiment_id):
            raise NishaError("That experiment ID is invalid.")
        path = self.experiments_dir / f"{experiment_id}.json"
        try:
            manifest = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise NishaError("The experiment record is unavailable or invalid.") from exc
        if manifest.get("experiment_id") != experiment_id:
            raise NishaError("The experiment record is invalid.")
        return manifest

    def version_state_path(self, root):
        key = hashlib.sha256(str(Path(root).resolve()).casefold().encode("utf-8")).hexdigest()[:20]
        return self.experiments_dir / f"version_state_{key}.json"

    def _version_state(self, root):
        try:
            return json.loads(self.version_state_path(root).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    def _save_version_state(self, root, state):
        path = self.version_state_path(root)
        temporary = path.with_suffix(".json.tmp")
        temporary.write_text(json.dumps(state, indent=2), encoding="utf-8")
        temporary.replace(path)

    @staticmethod
    def _validate_candidate_files(files):
        for relative in files:
            path = Path(relative)
            parts = {part.casefold() for part in path.parts}
            name = path.name.casefold()
            if (
                parts.intersection({"test", "tests", "__tests__", ".github"})
                or name in VALIDATION_FILES
                or name.startswith("test_")
                or name.endswith("_test.py")
                or (".github" in parts and "workflows" in parts)
            ):
                raise NishaError(
                    "Candidates cannot modify test suites or test/lint configuration; "
                    "keep evaluation controls independent of the proposed patch."
                )

    @serialized
    def create(self, proposal_id):
        metadata, patch = self._metadata(proposal_id)
        project_root = Path(metadata["project_root"]).resolve()
        if not project_root.is_dir():
            raise NishaError("The proposal's configured project folder is unavailable.")
        top = Path(self._git(project_root, "rev-parse", "--show-toplevel").stdout.strip()).resolve()
        if not project_root.is_relative_to(top):
            raise NishaError("The configured project isn't inside its Git repository.")
        project_prefix = project_root.relative_to(top).as_posix()
        selected = set(metadata.get("files", []))
        self._validate_candidate_files(selected)
        self.coding._validate_patch_paths(patch, selected, project_root)

        dirty = self._git(top, "diff", "--quiet", check=False).returncode
        staged = self._git(top, "diff", "--cached", "--quiet", check=False).returncode
        if dirty or staged:
            raise NishaError("Commit or discard tracked working changes before creating a candidate.")
        status = self._git(top, "status", "--porcelain", "-z").stdout
        for record in status.split("\0"):
            if not record or record[:2] != "??":
                continue
            user_path = (top / record[3:]).resolve()
            if any((project_root / relative).resolve().is_relative_to(user_path) for relative in selected):
                raise NishaError("A selected proposal path overlaps an untracked file or directory.")

        for relative in selected:
            repo_relative = (Path(project_prefix) / relative).as_posix() if project_prefix != "." else relative
            tracked = self._git(top, "ls-files", "--error-unmatch", "--", repo_relative, check=False)
            proposed_path = project_root / relative
            if tracked.returncode and proposed_path.exists():
                raise NishaError("A proposal cannot replace an existing untracked project file.")

        base = self._git(top, "rev-parse", "HEAD").stdout.strip()
        branch = self._git(top, "branch", "--show-current").stdout.strip()
        if not self.version_state_path(top).exists():
            self._save_version_state(top, {
                "repository_root": str(top),
                "stable_branch": branch,
                "current_stable_version": base,
                "last_known_good_version": base,
                "current_experiment": None,
                "updated_at": datetime.now(UTC).isoformat(),
            })
        experiment_id = proposal_id
        worktree = (self.worktrees_dir / experiment_id).resolve()
        if worktree.exists():
            raise NishaError("A worktree already exists for this experiment.")
        self.worktrees_dir.mkdir(parents=True, exist_ok=True)
        candidate_branch = f"codex/experiment-{experiment_id[:12]}"
        manifest = {
            "experiment_id": experiment_id,
            "proposal_id": proposal_id,
            "project": metadata["project"],
            "project_root": str(project_root),
            "repository_root": str(top),
            "base_commit": base,
            "base_branch": branch,
            "candidate_branch": candidate_branch,
            "worktree": str(worktree),
            "goal": metadata["goal"],
            "files": sorted(selected),
            "created_at": datetime.now(UTC).isoformat(),
            "status": "creating",
            "run_status": "active",
            "operation": "create",
            "tests": {},
            "benchmarks": {},
            "promotion": "human_approval_required",
        }
        self._write(manifest)
        try:
            self._git(top, "worktree", "add", "-b", candidate_branch, str(worktree), base)
        except NishaError:
            manifest["status"] = "creation_failed"
            manifest["run_status"] = "failed"
            self._write(manifest)
            raise
        apply_args = ["apply", "--check"]
        if project_prefix != ".":
            apply_args.append("--directory=" + project_prefix)
        check = subprocess.run(
            ["git", "-C", str(worktree), *apply_args],
            input=patch,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
            shell=False,
            check=False,
        )
        if check.returncode:
            self._git(top, "worktree", "remove", "--force", str(worktree), check=False)
            self._git(top, "branch", "-D", candidate_branch, check=False)
            manifest["status"] = "creation_failed"
            manifest["run_status"] = "failed"
            self._write(manifest)
            raise NishaError("The proposal doesn't apply cleanly to the recorded base commit.")
        apply_args = ["apply"] + apply_args[2:]
        applied = subprocess.run(
            ["git", "-C", str(worktree), *apply_args],
            input=patch,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
            shell=False,
            check=False,
        )
        if applied.returncode:
            self._git(top, "worktree", "remove", "--force", str(worktree), check=False)
            self._git(top, "branch", "-D", candidate_branch, check=False)
            manifest["status"] = "creation_failed"
            manifest["run_status"] = "failed"
            self._write(manifest)
            raise NishaError("Git couldn't apply the proposal in its isolated worktree.")

        manifest["status"] = "candidate_applied"
        manifest["run_status"] = "waiting_for_review"
        manifest["operation"] = "candidate"
        self._write(manifest)
        if self.store:
            self.store.audit("candidate_create", experiment_id)
        return manifest

    @serialized
    def list(self):
        result = []
        for path in sorted(self.experiments_dir.glob("[0-9a-f]" * 32 + ".json")):
            try:
                result.append(json.loads(path.read_text(encoding="utf-8")))
            except (OSError, ValueError):
                continue
        return result

    @serialized
    def verify(self, experiment_id, suite):
        manifest = self._load(experiment_id)
        if manifest["status"] not in {"candidate_applied", "verification_failed", "verification_passed"}:
            raise NishaError("This experiment isn't available for verification.")
        candidate_project_root = Path(manifest["worktree"]) / Path(manifest["project_root"]).relative_to(
            Path(manifest["repository_root"])
        )
        manifest["run_status"] = "active"
        manifest["operation"] = "verify_" + suite
        self._write(manifest)
        baseline_receipt = self.coding.verify(manifest["project"], suite)
        candidate_receipt = self.coding.verify_at(candidate_project_root, suite)
        manifest.setdefault("tests", {})[suite] = {
            "baseline": baseline_receipt,
            "candidate": candidate_receipt,
        }
        candidate_ok = candidate_receipt["exit_code"] == 0 and not candidate_receipt["timed_out"]
        manifest["status"] = "verification_passed" if candidate_ok else "verification_failed"
        manifest["updated_at"] = datetime.now(UTC).isoformat()
        manifest["run_status"] = "waiting_for_review"
        self._write(manifest)
        if self.store:
            self.store.audit("candidate_verify_" + suite, manifest["status"])
        return {
            "experiment_id": experiment_id,
            "status": manifest["status"],
            "baseline": baseline_receipt,
            "candidate": candidate_receipt,
        }

    @serialized
    def reject(self, experiment_id, reason):
        if not isinstance(reason, str) or not 1 <= len(reason.strip()) <= 1000:
            raise NishaError("Give a rejection reason in 1–1000 characters.")
        manifest = self._load(experiment_id)
        if manifest["status"] == "promoted":
            raise NishaError("A promoted candidate must be rolled back through the stable-version workflow.")
        manifest["status"] = "rejected"
        manifest["run_status"] = "archived"
        manifest["rejection_reason"] = reason.strip()
        manifest["updated_at"] = datetime.now(UTC).isoformat()
        self._write(manifest)
        if self.store:
            self.store.audit("candidate_reject", experiment_id)
        return manifest

    @serialized
    def benchmark(self, experiment_id):
        """Compare fixed test and lint suites on baseline and candidate revisions."""
        manifest = self._load(experiment_id)
        if manifest["status"] not in {"candidate_applied", "verification_failed", "verification_passed", "benchmark_complete"}:
            raise NishaError("This experiment isn't available for benchmarking.")
        candidate_project_root = Path(manifest["worktree"]) / Path(manifest["project_root"]).relative_to(
            Path(manifest["repository_root"])
        )
        manifest["run_status"] = "active"
        manifest["operation"] = "benchmark"
        self._write(manifest)
        results = {}
        for suite in ("pytest", "ruff"):
            timings = {}
            receipts = {}
            for label in ("baseline", "candidate"):
                def run(selected_suite=suite, selected_label=label):
                    if selected_label == "baseline":
                        return self.coding.verify(manifest["project"], selected_suite)
                    return self.coding.verify_at(candidate_project_root, selected_suite)

                started = monotonic()
                receipt = run()
                timings[label] = round(monotonic() - started, 3)
                receipts[label] = {
                    **receipt,
                    "passed": receipt["exit_code"] == 0 and not receipt["timed_out"],
                    "measured_seconds": timings[label],
                }
            results[suite] = receipts
        baseline_quality = all(results[suite]["baseline"]["passed"] for suite in results)
        candidate_quality = all(results[suite]["candidate"]["passed"] for suite in results)
        baseline_seconds = sum(results[suite]["baseline"]["measured_seconds"] for suite in results)
        candidate_seconds = sum(results[suite]["candidate"]["measured_seconds"] for suite in results)
        performance_delta_pct = (
            round((candidate_seconds - baseline_seconds) / baseline_seconds * 100, 2)
            if baseline_seconds else None
        )
        per_suite_delta = {}
        per_suite_guard_applied = {}
        for suite, receipts in results.items():
            baseline_time = receipts["baseline"]["measured_seconds"]
            candidate_time = receipts["candidate"]["measured_seconds"]
            per_suite_delta[suite] = (
                round((candidate_time - baseline_time) / baseline_time * 100, 2)
                if baseline_time else None
            )
            per_suite_guard_applied[suite] = (
                receipts["baseline"]["passed"] and baseline_time >= 1.0
            )
        no_material_slowdown = all(
            not per_suite_guard_applied[suite] or delta is None or delta <= 10
            for suite, delta in per_suite_delta.items()
        )
        # Sub-second suites are dominated by process-launch noise, so report but don't gate their timing.
        ready = candidate_quality and (not baseline_quality or no_material_slowdown)
        benchmark = {
            "completed_at": datetime.now(UTC).isoformat(),
            "baseline_quality_passed": baseline_quality,
            "candidate_quality_passed": candidate_quality,
            "baseline_seconds": round(baseline_seconds, 3),
            "candidate_seconds": round(candidate_seconds, 3),
            "performance_delta_pct": performance_delta_pct,
            "per_suite_performance_delta_pct": per_suite_delta,
            "per_suite_latency_guard_applied": per_suite_guard_applied,
            "performance_threshold_pct": 10,
            "minimum_timing_sample_seconds": 1.0,
            "ready_for_human_review": ready,
            "suites": results,
        }
        manifest.setdefault("benchmarks", {})["fixed_suites"] = benchmark
        manifest["status"] = "benchmark_complete"
        manifest["run_status"] = "waiting_for_review"
        manifest["updated_at"] = datetime.now(UTC).isoformat()
        self._write(manifest)
        if self.store:
            self.store.audit("candidate_benchmark", "ready" if ready else "not_ready")
        return {"experiment_id": experiment_id, "status": manifest["status"], **benchmark}

    @serialized
    def promote(self, experiment_id, approved, confirmation):
        if approved is not True or confirmation != "PROMOTE":
            raise NishaError("Promotion requires explicit approval and the exact confirmation PROMOTE.")
        manifest = self._load(experiment_id)
        benchmark = manifest.get("benchmarks", {}).get("fixed_suites", {})
        if manifest["status"] != "benchmark_complete" or not benchmark.get("ready_for_human_review"):
            raise NishaError("Only a candidate that passed benchmark review can be promoted.")
        root = Path(manifest["repository_root"])
        branch = self._git(root, "branch", "--show-current").stdout.strip()
        head = self._git(root, "rev-parse", "HEAD").stdout.strip()
        if branch != manifest["base_branch"] or head != manifest["base_commit"]:
            raise NishaError("The stable branch moved since this experiment began; create a fresh candidate.")
        if self._git(root, "diff", "--quiet", check=False).returncode or self._git(
            root, "diff", "--cached", "--quiet", check=False
        ).returncode:
            raise NishaError("Commit or discard tracked working changes before promotion.")
        manifest["run_status"] = "active"
        manifest["operation"] = "promoting"
        self._write(manifest)
        candidate_root = Path(manifest["worktree"])
        project_prefix = Path(manifest["project_root"]).relative_to(root).as_posix()
        paths = [
            (Path(project_prefix) / relative).as_posix() if project_prefix != "." else relative
            for relative in manifest["files"]
        ]
        self._git(candidate_root, "add", "--", *paths)
        if self._git(candidate_root, "diff", "--cached", "--quiet", check=False).returncode == 0:
            raise NishaError("The candidate contains no change to promote.")
        self._git(
            candidate_root,
            "-c", "user.name=NISHA Candidate Review",
            "-c", "user.email=nisha-candidate@localhost",
            "commit", "-m", f"Promote NISHA candidate {experiment_id[:12]}",
        )
        promotion_commit = self._git(candidate_root, "rev-parse", "HEAD").stdout.strip()
        self._git(root, "merge", "--ff-only", manifest["candidate_branch"])
        state = {
            "repository_root": str(root),
            "stable_branch": branch,
            "current_stable_version": promotion_commit,
            "last_known_good_version": promotion_commit,
            "previous_stable_version": manifest["base_commit"],
            "current_experiment": experiment_id,
            "updated_at": datetime.now(UTC).isoformat(),
        }
        self._save_version_state(root, state)
        manifest["status"] = "promoted"
        manifest["promotion_commit"] = promotion_commit
        manifest["promoted_at"] = datetime.now(UTC).isoformat()
        manifest["promotion_approved"] = True
        manifest["run_status"] = "waiting_for_review"
        manifest["operation"] = "promote"
        self._write(manifest)
        if self.store:
            self.store.audit("candidate_promote", experiment_id)
        return {"experiment_id": experiment_id, "status": "promoted", "version_state": state}

    @serialized
    def rollback(self, experiment_id, approved, confirmation):
        if approved is not True or confirmation != "ROLLBACK":
            raise NishaError("Rollback requires explicit approval and the exact confirmation ROLLBACK.")
        manifest = self._load(experiment_id)
        if manifest["status"] != "promoted":
            raise NishaError("Only a promoted candidate can be rolled back.")
        root = Path(manifest["repository_root"])
        current = self._git(root, "rev-parse", "HEAD").stdout.strip()
        if current != manifest.get("promotion_commit"):
            raise NishaError("The stable branch has moved since promotion; automatic rollback is unsafe.")
        if self._git(root, "diff", "--quiet", check=False).returncode or self._git(
            root, "diff", "--cached", "--quiet", check=False
        ).returncode:
            raise NishaError("Commit or discard tracked working changes before rollback.")
        manifest["run_status"] = "active"
        manifest["operation"] = "rolling_back"
        self._write(manifest)
        reverted = self._git(
            root,
            "-c", "user.name=NISHA Candidate Review",
            "-c", "user.email=nisha-candidate@localhost",
            "revert", "--no-edit", current,
        )
        rollback_commit = self._git(root, "rev-parse", "HEAD").stdout.strip()
        state = self._version_state(root)
        state.update({
            "current_stable_version": rollback_commit,
            "last_known_good_version": rollback_commit,
            "rolled_back_experiment": experiment_id,
            "rollback_commit": rollback_commit,
            "updated_at": datetime.now(UTC).isoformat(),
        })
        self._save_version_state(root, state)
        manifest["status"] = "rolled_back"
        manifest["run_status"] = "archived"
        manifest["operation"] = "rollback"
        manifest["rollback_commit"] = rollback_commit
        manifest["rollback_output"] = reverted.stdout.strip()[-1000:]
        manifest["rolled_back_at"] = datetime.now(UTC).isoformat()
        self._write(manifest)
        if self.store:
            self.store.audit("candidate_rollback", experiment_id)
        return {"experiment_id": experiment_id, "status": "rolled_back", "version_state": state}

    @serialized
    def recover_interrupted(self):
        """Reconcile interrupted lifecycle operations without rewriting source files."""
        recovered = []
        for path in self.experiments_dir.glob("[0-9a-f]" * 32 + ".json"):
            try:
                manifest = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if manifest.get("run_status") != "active":
                continue
            root = Path(manifest.get("repository_root", ""))
            if not root.is_dir():
                manifest["status"] = "interrupted"
                manifest["recovery"] = "Repository unavailable; no automatic source changes attempted."
            else:
                head = self._git(root, "rev-parse", "HEAD", check=False).stdout.strip()
                candidate_head = self._git(
                    root, "rev-parse", "refs/heads/" + manifest.get("candidate_branch", ""), check=False
                ).stdout.strip()
                operation = manifest.get("operation")
                if operation == "promoting" and head and head == candidate_head:
                    manifest["status"] = "promoted"
                    manifest["promotion_commit"] = head
                    manifest["promotion_approved"] = True
                    manifest["promoted_at"] = datetime.now(UTC).isoformat()
                    state = self._version_state(root)
                    state.update({
                        "repository_root": str(root),
                        "stable_branch": manifest.get("base_branch"),
                        "current_stable_version": head,
                        "last_known_good_version": head,
                        "previous_stable_version": manifest.get("base_commit"),
                        "current_experiment": manifest.get("experiment_id"),
                        "updated_at": datetime.now(UTC).isoformat(),
                    })
                    self._save_version_state(root, state)
                    manifest["recovery"] = "Completed promotion metadata after the Git fast-forward."
                elif operation == "rolling_back" and head:
                    subject = self._git(root, "log", "-1", "--format=%s", check=False).stdout.strip()
                    if subject.startswith("Revert \"Promote NISHA candidate"):
                        manifest["status"] = "rolled_back"
                        manifest["rollback_commit"] = head
                        manifest["rolled_back_at"] = datetime.now(UTC).isoformat()
                        manifest["recovery"] = "Completed rollback metadata after the Git revert."
                        state = self._version_state(root)
                        state.update({
                            "repository_root": str(root),
                            "current_stable_version": head,
                            "last_known_good_version": head,
                            "rolled_back_experiment": manifest.get("experiment_id"),
                            "rollback_commit": head,
                            "updated_at": datetime.now(UTC).isoformat(),
                        })
                        self._save_version_state(root, state)
                    else:
                        manifest["status"] = "interrupted"
                        manifest["recovery"] = "Rollback was interrupted before a confirmed revert commit."
                else:
                    manifest["status"] = "interrupted"
                    manifest["recovery"] = (
                        "Candidate work remains isolated; stable HEAD is "
                        + ("unchanged." if head == manifest.get("base_commit") else "different from its recorded base.")
                    )
            manifest["run_status"] = "recovered"
            manifest["updated_at"] = datetime.now(UTC).isoformat()
            self._write(manifest)
            recovered.append(manifest["experiment_id"])
            if self.store:
                self.store.audit("candidate_recovery", manifest["status"])
        return recovered
