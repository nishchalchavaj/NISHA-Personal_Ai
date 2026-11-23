# NISHA Problems

## Baseline contextual-action tests use unknown session

- **What happened:** Two full-suite tests fail before action assertions.
- **Likely cause:** Test fixtures used the literal `test-session` without creating it in the test SQLite store.
- **Confirmed cause:** `Store.history("test-session")` raised `ValueError("Unknown session. Start a new conversation.")` from `nisha/storage.py`.
- **Fix:** Updated the two affected tests to create a real session via `core.new_session()` and use its ID. Runtime code was unchanged.
- **Test performed:** Full baseline: 777 passed, 2 failed. Focused corrected suites: 28 passed. Final full suite: 780 passed.
- **Result:** Resolved; no remaining test failures.
