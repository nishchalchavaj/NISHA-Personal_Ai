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
