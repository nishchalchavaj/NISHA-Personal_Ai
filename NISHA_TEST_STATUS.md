# NISHA Test Status

Updated: 2026-11-24

- Full pre-change suite: **777 passed, 2 failed**, 2 warnings, 259.84s. Both failures were contextual-action tests using a session that was never created; their fixtures are corrected.
- Focused post-change suite (`tests/test_contextual_actions.py`, `tests/test_tools.py`, `tests/test_gateway_api.py`): **28 passed**, 4.64s on final run.
- Full suite after Phase 4: **790 passed, 2 warnings**, 188.57s.
- Phase 4 focused suite: **51 passed**, 19.58s.
- Phase 5 focused coding/API/automation suites: **36 passed**, 7.15s. Final coding/API subset including failure and timeout receipts: **18 passed**, 4.07s.
- Full suite after Phase 5: **798 passed, 2 warnings**, 188.12s.
- Focused candidate lifecycle suite (`tests/test_versioning.py`): **10 passed**, 19.13s.
- Authenticated API suite: **10 passed**, 1.62s.
- Full suite after Phases 6–12, evaluation-path guard and timing-noise fix: **811 passed, 2 warnings**, 212.90s.
- CLI smoke check: `.venv\\Scripts\\python.exe -m nisha --help` completed successfully.
- Ruff on all changed Python files and `git diff --check`: passed.
- Ruff on changed Python files: passed. `git diff --check`: passed.
- Platform limit: live screen capture, microphone, external web research and real application actions were not exercised by this regression run.
- Warnings: pywinauto externally defined COM initialization flags; pypdf `add_js` deprecation.
