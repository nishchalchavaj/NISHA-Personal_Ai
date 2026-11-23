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
- Follow-up focused terminal/research/versioning/API/tool/coding suite: **44 passed in 33.56s**. Changed-file Ruff passed.
- Full suite after follow-up: **820 passed, 2 warnings in 197.18s**.
- Live screen capture smoke check: **passed**, JPEG 2560×999, 332,572 bytes; pixels were neither inspected nor sent to a vision model.
- Windows Sandbox focused stress suite (`tests/test_sandbox.py`, terminal, gateway API, resident UI): **98 passed**, 63.15s. Covered locked-down WSB XML, readonly mappings, private/untracked-file exclusion, local patch handling, missing-feature fail-closed behavior, output/patch limits, timeout and emergency stop.
- Final Sandbox/terminal/API suite after guest Python mount-path and receipt-ID checks: **32 passed**.
- Full post-Sandbox regression after mount-path and receipt-ID checks: **836 passed, 2 warnings**, 231.96s. The warnings are pywinauto's externally defined COM flags and pypdf's `add_js` deprecation.
- Changed-file Ruff and `git diff --check`: passed.
- Platform limits: `WindowsSandbox.exe` is absent because enabling the optional feature was canceled at UAC; real guest boot/shutdown remains unverified until feature enablement and restart. External SearXNG, physical microphone and live target-app actions were not exercised. The live screen capture check validated JPEG metadata/dimensions only; it did not test pixel interpretation. Coordinate-aware general clicks and broad task-success/GPU metrics remain outside current implementation.
- Warnings: pywinauto externally defined COM initialization flags; pypdf `add_js` deprecation.
