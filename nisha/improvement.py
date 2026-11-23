"""Bounded observe-to-candidate loop; it never promotes without human approval."""

import hashlib
import json
from pathlib import Path
from time import monotonic


class ImprovementRunner:
    def __init__(self, coding, candidates, store=None, retry_limit=3, max_runtime_seconds=1800):
        self.coding = coding
        self.candidates = candidates
        self.store = store
        self.retry_limit = max(1, min(int(retry_limit), 3))
        self.max_runtime_seconds = max(1, min(int(max_runtime_seconds), 1800))

    def run(self, goal, project, files, core, session, alias="auto"):
        started = monotonic()
        deadline = started + self.max_runtime_seconds
        original_timeout = self.coding.timeout
        attempts = []
        seen_patches = set()
        last_failure = ""
        result = {"status": "runtime_budget_exhausted", "attempts": attempts}
        try:
            for attempt_number in range(1, self.retry_limit + 1):
                remaining = deadline - monotonic()
                if remaining < 6:
                    break
                self.coding.timeout = min(original_timeout, max(1, int(remaining / 6)))
                attempt_goal = goal
                if last_failure:
                    attempt_goal += (
                        "\n\nPrevious candidate failed. Do not repeat that approach. "
                        "Use this captured result as evidence and choose a different small change:\n"
                        + last_failure[:4000]
                    )
                proposal = self.coding.propose(attempt_goal, project, files, core, session, alias)
                patch_text = Path(proposal["patch_path"]).read_text(encoding="utf-8")
                digest = hashlib.sha256(patch_text.encode("utf-8")).hexdigest()
                candidate = self.candidates.create(proposal["candidate_id"])
                attempt = {
                    "attempt": attempt_number,
                    "proposal_id": proposal["candidate_id"],
                    "experiment_id": candidate["experiment_id"],
                    "patch_digest": digest,
                }
                attempts.append(attempt)
                if digest in seen_patches:
                    rejected = self.candidates.reject(
                        candidate["experiment_id"], "Identical patch was already tried and failed."
                    )
                    attempt["status"] = "rejected_duplicate_patch"
                    last_failure = "An identical patch was already attempted; do not repeat it."
                    result.update({"status": "rejected", "candidate": rejected})
                    break
                seen_patches.add(digest)

                remaining = deadline - monotonic()
                if remaining < 6:
                    result.update({"status": "runtime_budget_exhausted"})
                    break
                self.coding.timeout = min(original_timeout, max(1, int(remaining / 6)))
                verification = self.candidates.verify(candidate["experiment_id"], "pytest")
                attempt["verification"] = verification
                if verification["status"] != "verification_passed":
                    receipt = verification["candidate"]
                    last_failure = receipt.get("stdout", "") + receipt.get("stderr", "")
                    rejected = self.candidates.reject(
                        candidate["experiment_id"], "Candidate pytest verification failed."
                    )
                    attempt["status"] = "rejected_verification"
                    result.update({
                        "status": "rejected",
                        "proposal_id": proposal["candidate_id"],
                        "experiment_id": candidate["experiment_id"],
                        "verification": verification,
                        "candidate": rejected,
                    })
                    continue

                remaining = deadline - monotonic()
                if remaining < 6:
                    result.update({"status": "runtime_budget_exhausted", "verification": verification})
                    break
                self.coding.timeout = min(original_timeout, max(1, int(remaining / 4)))
                benchmark = self.candidates.benchmark(candidate["experiment_id"])
                attempt["benchmark"] = benchmark
                if benchmark["ready_for_human_review"]:
                    attempt["status"] = "ready_for_human_approval"
                    result.update({
                        "status": "ready_for_human_approval",
                        "proposal_id": proposal["candidate_id"],
                        "experiment_id": candidate["experiment_id"],
                        "verification": verification,
                        "benchmark": benchmark,
                        "candidate": self.candidates._load(candidate["experiment_id"]),
                    })
                    break
                last_failure = json.dumps(benchmark, ensure_ascii=False)[:4000]
                rejected = self.candidates.reject(
                    candidate["experiment_id"],
                    "Candidate did not satisfy the fixed quality/performance benchmark gate.",
                )
                attempt["status"] = "rejected_benchmark"
                result.update({
                    "status": "rejected",
                    "proposal_id": proposal["candidate_id"],
                    "experiment_id": candidate["experiment_id"],
                    "verification": verification,
                    "benchmark": benchmark,
                    "candidate": rejected,
                })
        finally:
            self.coding.timeout = original_timeout
        result["attempt_count"] = len(attempts)
        result["duration_seconds"] = round(monotonic() - started, 3)
        result["retry_limit"] = self.retry_limit
        result["maximum_runtime_seconds"] = self.max_runtime_seconds
        if self.store:
            self.store.audit("improvement_run", result["status"])
        return result
