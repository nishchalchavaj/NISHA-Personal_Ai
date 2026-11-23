# NISHA Experiments

## 2026-11-24 — Candidate lifecycle harness validation

- **Experiment ID:** Temporary pytest-generated IDs; no persistent experiment was run against a configured user project.
- **Objective:** Validate candidate isolation, baseline/candidate verification, fixed-suite benchmarking, explicit promotion, rollback, rejection, and restart recovery.
- **Current system:** NISHA Phases 1–5 checkpoint at `cc520a9`.
- **Proposed change:** Generated a small local patch in a temporary Git repository and exercised the Phase 6–12 lifecycle.
- **Hypothesis:** The candidate changes only its worktree until explicitly approved, and rollback restores tracked source through a new revert commit.
- **Metrics:** Candidate pytest/Ruff result, recorded elapsed time, base/stable commit, post-promotion content, and post-rollback content.
- **Baseline:** Test repository committed with value 1; test variations included a known failing baseline and a passing control.
- **Candidate:** Patch changes the fixture value to 2 in a separate worktree.
- **Tests:** `tests/test_versioning.py`; full suite after implementation.
- **Benchmark:** pytest and Ruff run on both baseline and candidate; review gate enforces candidate pass and limits per-suite time regression to 10% when that baseline suite passes and takes at least one second.
- **Result:** All lifecycle assertions passed; full suite passed 811 tests.
- **Decision:** Keep candidate isolation and fast-forward/revert design. This validated the mechanism only; it is not evidence of a quality improvement to the user's configured projects.
- **Rollback information:** Test repository was temporary. No candidate changes were applied to `E:\NISHA`; its code remains on the feature branch.

## 2026-11-24 — Offline Sandbox terminal stress validation

- **Experiment ID:** Windows Sandbox integration verification; tests use temporary projects and a fake Sandbox launcher because the Windows feature is unavailable.
- **Objective:** Verify privacy mappings, fail-closed behavior, bounded results, timeout, patch handling and emergency stop without sending project data outside the PC.
- **Current system:** NISHA feature branch with Windows Sandbox optional feature disabled.
- **Proposed change:** Route approved terminal jobs into a network-disabled guest and return a local bounded diff.
- **Hypothesis:** The production path never falls back to the host and only maps sanitized inputs read-only plus one unique writable output directory.
- **Metrics:** focused tests and complete regression tests; no network query or upload initiated.
- **Baseline:** terminal used host Job Objects, which did not isolate host files, credentials or network.
- **Candidate:** Windows Sandbox runner with filtered project snapshot, read-only local Python/Git tools, disabled networking and device sharing, capped result/patch, and emergency stop.
- **Tests:** Focused Sandbox/terminal/API/resident-UI suite; full `pytest -q`; Ruff; `git diff --check`.
- **Benchmark:** N/A; this is an isolation behavior change rather than a performance candidate.
- **Result:** Focused suite 98 passed; after fixing guest Python mount consistency and binding results to the one-use ID, focused Sandbox/terminal/API suite 32 passed and full suite 836 passed in 231.96s with two existing warnings. Real guest boot is unverified because `WindowsSandbox.exe` is absent.
- **Decision:** Keep the fail-closed implementation; do not claim guest E2E completion until the feature is enabled and a real guest run succeeds.
- **Rollback information:** Changes remain on the feature branch. No changes to unrelated untracked `trader/`.
