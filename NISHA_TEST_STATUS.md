# NISHA Test Status

Updated: 2026-11-24

- Latest real-time information / Spotify routing fix: **884 passed, 2 warnings in 284.43s**. Added deterministic local date/time answers and per-turn local timestamp context; fixed question-form live-weather routing; latest-news prompts now fetch Google News RSS headlines with publication dates and source links; Spotify open-and-play requests stay within one Spotify workflow. Public live smoke checks succeeded: Google News returned 8 headlines and Open-Meteo returned a current Nargund forecast. No conversation history or personal data was sent with the news query. Ruff, compileall and `git diff --check` passed. Spotify UI playback was verified through mocked accessibility controls, not a live click.

- Final conversation, multi-command, orbit and full-project verification: **878 passed, 2 warnings in 254.88s**. Covered local LLM small talk and wake turns, bounded two-sided compaction, cross-session summary retrieval, recent follow-ups/corrections/topic changes, natural-language command prefaces, ordered app/web commands, 10-message unread email draft cap, transparent orbit overlay, and the repository stress tests. Repository Ruff, compileall and `git diff --check` passed. Warnings: pywinauto COM initialization flags and pypdf `add_js` deprecation. No live Gmail, Spotify, microphone or real-target visual click was exercised.

- Multi-action and mood-music/email update: focused orchestration, workflow, Gmail inbox, dialogue, contextual action, browser, PC-control and responsiveness suite **70 passed** after routing compatibility fixes. Full repository regression **873 passed, 2 existing warnings in 229.82s**. Changed-file Ruff, compile and `git diff --check` passed. Gmail IMAP behavior and multi-reply drafting used synthetic messages/adapters; no live Gmail or Spotify account was accessed.

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
- Final focused Sandbox/terminal/API suite after launcher/session and cleanup fixes: **33 passed**, 17.47s.
- Full post-Sandbox regression after launcher/session and cleanup fixes: **837 passed, 2 warnings**, 305.51s. The warnings are pywinauto's externally defined COM flags and pypdf's `add_js` deprecation.
- Real Windows Sandbox E2E: **passed**. Offline guest command returned exit 0; local patch contained the guest edit; host test file remained unchanged; no new job directory remained.
- Changed-file Ruff and `git diff --check`: passed.
- Platform limits: Sandbox guest operation is verified. External SearXNG, physical microphone and live target-app actions were not exercised. The visual-click feature was tested with synthetic images and fake input; no live screen pixels were sent to vision and no real click was made. Multi-step computer-use planning and broad task-success/GPU metrics remain outside current implementation.
- Visual-control follow-up: focused `tests/test_screen.py`, `tests/test_vision.py`, `tests/test_pc_control.py`, and `tests/test_gateway_api.py`: **50 passed**. Changed-file Ruff and `git diff --check`: passed. Full suite: **852 passed, 1 failed, 2 warnings in 769.83s**. The one failure was `tests/test_resident_ui.py::test_image_results_describe_then_advance_automatically_without_fake_user_memory`, which missed its two-speech deadline during the full run; isolated rerun passed (**1 passed in 5.39s**). This appears timing-sensitive and unrelated to visual click, but the full-suite run was not completely green.
- Final verification after stale-coordinate and sensitive-label hardening: focused screen/vision/UI control/API suite **53 passed**; Ruff and `git diff --check` passed; full suite **856 passed, 2 existing warnings in 349.95s**. The prior isolated resident-UI timing failure did not recur. No live click or screen interpretation was exercised.
- Warnings: pywinauto externally defined COM initialization flags; pypdf `add_js` deprecation.
- Front-page and action-feedback update: background UI/presentation tests **33 passed**; resident UI suite **69 passed**. Full regression after UI changes: **858 passed, 2 warnings in 261.38s**. Changed UI and test file Ruff checks and `git diff --check` passed. Repository-wide Ruff reports three pre-existing style issues in untouched `nisha/ui/gesture_studio.py`. Verification used offscreen UI tests; no real desktop actions, microphone recording or physical voice output were performed.
- Full-window HUD follow-up: added an opacity/render test and footer collision checks at 1366×768 and 1920×1080. Full regression: **859 passed, 2 warnings in 258.94s**. Changed UI/test Ruff and `git diff --check` passed.
- Functional command-center / extended-desktop follow-up: focused desktop, activity feed, monitor selection, screen and window-control suite: **118 passed in 71.36s**. Complete regression: **863 passed, 2 existing warnings in 252.71s**. Compile and changed-file Ruff passed. Center-monitor selection and virtual click mapping were checked against simulated layouts; physical three-monitor window placement and real display actions were not exercised.
- Reference-inspired dashboard refinement: resident and background UI suites **80 passed**; compile and changed-file Ruff passed. Covered the responsive card grid at 1366×768 and 1920×1080, activity search, quick command wiring, and footer/feed spacing. The full suite was not repeated for this layout-only change; the preceding full regression was 863 passed with 2 warnings.
- Orbit/compact-view follow-up: resident and background UI suites **81 passed**; compile and changed-file Ruff passed. Covered minimize-to-corner placement, orbit-only compact visibility, latest-conversation summary, restore, animated orbit state, and navigation nodes. Full suite not repeated; preceding full regression remains 863 passed with 2 warnings.
