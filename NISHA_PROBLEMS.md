# NISHA Problems

## Baseline contextual-action tests use unknown session

- **What happened:** Two full-suite tests fail before action assertions.
- **Likely cause:** Test fixtures used the literal `test-session` without creating it in the test SQLite store.
- **Confirmed cause:** `Store.history("test-session")` raised `ValueError("Unknown session. Start a new conversation.")` from `nisha/storage.py`.
- **Fix:** Updated the two affected tests to create a real session via `core.new_session()` and use its ID. Runtime code was unchanged.
- **Test performed:** Full baseline: 777 passed, 2 failed. Focused corrected suites: 28 passed. Final full suite: 780 passed.
- **Result:** Resolved; no remaining test failures.
# Phase 6–12 verification notes

- **Problem:** The first rollback lifecycle test raised while serializing Git's `CompletedProcess` receipt after `git revert` had already succeeded.
- **What happened:** Candidate promotion worked, but rollback metadata attempted to call `.strip()` on the process object rather than its stdout.
- **Confirmed cause:** Receipt serialization used the wrong return value attribute.
- **Fix:** Persist the bounded `stdout` text and re-read `HEAD`; add an end-to-end promotion/rollback test that checks source content and commit state.
- **Test performed:** `tests/test_versioning.py` and the focused candidate/coding/API/diagnostics set.
- **Result:** Passed after fix; final full suite reports 811 passed.

## Sub-second benchmark timing jitter

- **Problem:** A full run intermittently rejected a candidate with all checks passing because the single-run Ruff process time varied by more than 10% on a sub-second fixture.
- **What happened:** Process launch and Windows scheduling dominated the small workload, producing 13.64% timing variance between equivalent baseline/candidate runs.
- **Confirmed cause:** The candidate was not slower in the test workload; measurement noise from one tiny sample crossed the latency threshold.
- **Fix:** Keep recording each timing, but apply the 10% regression gate only when the passing baseline command takes at least one second. Full-suite timings remain gated; sub-second timings are explicitly marked as ungated.
- **Test performed:** Reproduced in `tests/test_versioning.py::test_restart_recovery_finishes_rollback_metadata_after_git_revert`; verify the candidate remains reviewable and that the sub-second lint guard is marked unapplied.
- **Result:** Focused test passes with the minimum measurement threshold.

## Follow-up gap-closure fixes

- **Benchmark guard:** Review found that a failing baseline suite could bypass the slowdown condition for another suite. The readiness gate now requires candidate quality and applies per-suite slowdown checks only where the baseline suite passed and its median is at least one second. Three-run median/MAD evidence is persisted for every suite.
- **Windows process containment:** Initial Job Object creation and suspended-process flag handling were incompatible with the installed pywin32 API; corrected using a named/empty job name and `CREATE_SUSPENDED`, with assignment failures failing closed. PowerShell, CMD, and Python smoke commands then completed under Job Object limits; timeout termination is covered by a regression test.
- **Secret redaction:** Generic `TOKEN=...` assignments were not redacted from public research snippets. The assignment-secret matcher now handles generic token names as well as API key/secret names; regression test passes.
- **Result:** Follow-up focused suite passed: 44 tests; full suite passed: 820 tests with the two existing warnings.
