# NISHA Test Status

Updated: 2026-11-23

- Full pre-change suite: **777 passed, 2 failed**, 2 warnings, 259.84s. Both failures were contextual-action tests using a session that was never created; their fixtures are corrected.
- Focused post-change suite (`tests/test_contextual_actions.py`, `tests/test_tools.py`, `tests/test_gateway_api.py`): **28 passed**, 4.64s on final run.
- Full suite after Phase 4: **790 passed, 2 warnings**, 188.57s.
- Phase 4 focused suite: **51 passed**, 19.58s.
- Phase 5 focused coding/API/automation suites: **36 passed**, 7.15s. Final coding/API subset including failure and timeout receipts: **18 passed**, 4.07s.
- Full suite after Phase 5: **798 passed, 2 warnings**, 188.12s.
- Ruff on changed Python files: passed. `git diff --check`: passed.
- Platform/runtime smoke checks: not rerun for this documentation and API catalog change.
- Warnings: pywinauto externally defined COM initialization flags; pypdf `add_js` deprecation.
