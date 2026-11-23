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

## Sandbox snapshot fallback and stop/exit race

- **What happened:** The first emergency-stop stress test could not reach the fake guest process for a non-Git project. After snapshot staging was corrected, a narrow race could report an emergency stop as an unexpected Sandbox exit.
- **Likely cause:** The filesystem-walk fallback retained absolute file paths while downstream validation expected relative paths; the process-exit branch also needed to recheck cancellation.
- **Confirmed cause:** The staging fallback's paths were filtered as absolute and skipped. If stop arrived between the cancellation poll and process-exit check, the latter could win.
- **Fix:** Store paths relative to the resolved project root and recheck the stop event before classifying early process exit.
- **Test performed:** `tests/test_sandbox.py::test_emergency_stop_terminates_active_sandbox_job`, focused integration suite, and full post-change suite.
- **Result:** Emergency-stop test passed; focused suite: 98 passed; full suite: 835 passed, 2 existing warnings.

## Sandbox Python guest mount path mismatch

- **What happened:** Final configuration review found that the guest bootstrap referenced `C:\NishaTools\Python311\python.exe`, while the `.wsb` file mounted the runtime at `C:\NishaTools\Python`.
- **Likely cause:** The executable path included a Python version tag that the mount mapping did not include.
- **Confirmed cause:** The request/bootstrap path and `MappedFolder.SandboxFolder` differed, which would prevent guest startup.
- **Fix:** Use the mapped `C:\NishaTools\Python\python.exe` path and assert the executable parent matches the configured guest mount.
- **Test performed:** Focused Sandbox/terminal/API tests and full post-fix regression suite.
- **Result:** Focused suite passed (31 tests); full suite passed (835 tests, 2 existing warnings).

## Windows Sandbox launcher exits before its guest session starts

- **What happened:** The live E2E initially failed with Windows Sandbox error `0x80070002` before returning a result. A simple mapped-folder probe later confirmed the Sandbox configuration and mappings were valid.
- **Likely cause:** `WindowsSandbox.exe` hands work to `WindowsSandboxRemoteSession.exe` and can exit before the guest's logon command finishes. The runner treated launcher exit as guest exit and removed mapped files during startup.
- **Confirmed cause:** The launcher exited before the test guest produced its output; the packaged remote-session app was the active guest UI. Delayed result delivery after launcher exit reproduced the lifecycle behavior.
- **Fix:** Track the packaged remote-session process, wait for the job receipt after launcher exit, then allow guest shutdown, close its disconnected UI, and retry temporary job cleanup.
- **Test performed:** Added a launcher-exits-first regression test; ran the live Windows Sandbox command and full pytest suite.
- **Result:** Real offline E2E passed: exit 0, local patch returned, host file unchanged, no new job directory. Focused suite: 33 passed; full suite: 837 passed, 2 existing warnings.
