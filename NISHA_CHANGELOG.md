# NISHA Changelog

## 2026-11-24 — Conversation continuity and orbit cleanup

- **Conversation:** Small talk and wake-only greetings use the existing local LLM path. Recent user and assistant turns, corrections and follow-ups stay in context; bounded local summaries preserve prior recommendations and retrieve relevant notes across sessions without loading full old transcripts.
- **Action routing:** Natural prefaces such as “I'm stressed after college, so play music” reach supported adapters, while action-like words in ordinary explanations remain conversation. Simple social turns go directly to the LLM; other conversational turns never wait for the action lock. Explicit multi-step commands remain sequential and report each step.
- **Display:** Removed painted rings from the orb overlay while preserving animated shortcut controls.
- **Email:** Local unread reply bundles are capped at ten; nothing is sent or uploaded as a Gmail draft.
- **Live information:** Added local date/time answers and context, fixed question-form weather requests, and routed latest-news questions to dated Google News RSS headlines. Only the public search query is sent; personal conversation context is not.
- **Spotify:** “Open Spotify and play some song” stays one Spotify workflow so the play step keeps its app context and returns the adapter's actual playback result.
- **Verification:** Added tests for compaction, prior-session recall, reference continuity, topic changes, natural action prefaces, wake behavior and orbit transparency; full regression results are recorded in `NISHA_TEST_STATUS.md`.

## 2026-11-24 — Ordered multi-action requests and mood music

- **Changed:** Added explicit chained commands across NISHA's supported app, browser, window, device, and workflow adapters. NISHA reports each step in order and stops after a failed or unsupported step; the sequence parser does not generate new actions.
- **Music:** Natural mood phrasing such as “I'm stressed after college, so play some song in Spotify” searches Spotify for calming music. NISHA plays only when one accessible result Play control can be identified and confirms Spotify's Pause control; otherwise it leaves the search open.
- **Email:** “Check new email” lists unread Gmail messages using read-only IMAP search and BODY.PEEK. “Draft replies for all” creates local review drafts for up to ten messages with a single valid reply address, shows them in chat and saves a local JSON bundle. The action does not create Gmail drafts or send messages.
- **Privacy:** Email message content is passed only through NISHA's configured local model path for drafting; the inbox connection itself uses Gmail IMAP over TLS. Messages remain unread and attachments/remote HTML are not opened.
- **Verification:** Orchestration, workflow, Gmail inbox, dialogue, contextual action, browser action, PC control and responsiveness tests; changed-file Ruff, compile and diff checks. Full regression result is recorded in `NISHA_TEST_STATUS.md`.

## 2026-11-24 — State-reactive orbit and compact minimize view

- **Changed:** Added animated orbit shortcut buttons to Tasks, Memory and Microphone controls. The painted rings were later removed to keep the NISHA core clear; the orbit timing and shortcuts remain functional.
- **Minimize behavior:** The minimize button docks a compact bottom-corner window on the selected center display. It shows only the reactor/orbit and latest conversation; the same button becomes a restore control. Closing still exits NISHA. Background actions restore the full dashboard when they need to show a result.
- **Verification:** Resident and background UI suites: **81 passed**; compile and changed-file Ruff passed. The compact layout, latest-turn truncation, restore control, orbit animation/state and node navigation are covered. No full-suite rerun was needed for these desktop-only changes.

## 2026-11-24 — Reference-inspired command center refinement

- **Changed:** Rebalanced the front page into a denser dashboard with a compact navigation rail, live-state/date/search header, NISHA hero panel, right-side activity feed, overview/memory/model/device cards, CPU/memory/disk meters, working quick commands, and a persistent voice/text dock. Shortened navigation labels, removed the duplicate painted title, and made feed search filter recent activity.
- **Functionality:** System meters use local `psutil` data on a five-second timer. Quick buttons invoke new chat, open-window listing, installed-app listing, and device-status requests. Search filters only the bounded recent activity feed. No agent, calendar, network, or provider status is fabricated.
- **Verification:** Resident and background UI suites: **80 passed**; compile and Ruff passed. A full suite was not repeated for this layout-only update; the preceding full regression passed **863 tests**.

## 2026-11-24 — Functional Jarvis command center and extended-desktop support

- **Changed:** Reworked the front page into an opaque command center with working navigation, real local service/memory/device/task cards, and a bounded live feed for conversation and action receipts. Added live task filtering and cancellation. NISHA chooses the display nearest the center of the extended desktop at launch; visual screen capture/click coordinates and existing window operations use all connected displays. Added window minimize, full-window toggle and close controls.
- **Performance:** Removed dashboard database/status refreshes from each streamed text update. The activity feed batches UI redraws, follows the newest entry and retains at most 60 items. Device status stays on its existing background poll timer.
- **Tests:** Focused desktop/screen/control suite: **118 passed**; complete regression: **863 passed, 2 existing warnings in 252.71s**. Compile, changed-file Ruff and `git diff --check` passed.
- **Limits:** Display placement/coordinate handling was tested with simulated monitor layouts; no physical multi-display move or live target-app action was exercised. Windows still chooses the initial position of an app launched by a command; NISHA can manage windows across displays after they appear.

## 2026-11-24 — Front-page action visibility and spoken receipts

- **Changed:** Added a full-window dark HUD backdrop with a drafting grid, reactor rings, framing marks and inset status cards. Made the floating results and conversation windows opaque; retained full answers in chat and the desktop conversation area; made chat follow new messages; added the always-visible navigation/settings bar; enabled spoken typed replies by default; and displayed queued, active and completed actions in the adjacent result panel with spoken completion receipts. Local UI actions such as showing media and closing results now report their outcome.
- **Compatibility:** Microphone mute controls capture only. Explicit action receipts still speak while input is muted, and background action completion brings NISHA forward so its result is visible.
- **Runtime issue found:** Earlier logs repeatedly reported that the selected Maono microphone delivered no audio frames. Later logs show successful local speech decoding, but the live input stream was not exercised during this UI verification. Device enumeration and the general doctor check pass.

## 2026-11-24 — Screenshot-grounded single-click control

- **Changed:** Added explicit chat/API requests to locate one inaccessible screen target with local vision, validate normalized coordinates/confidence, ensure primary-display dimensions match the input API, click once, and report a post-click screenshot change with an optional local description. Existing named UI Automation remains the preferred path.
- **Privacy:** The screenshot and target phrase go only to the verified loopback Ollama vision model; the screen service does not persist image bytes. No external vision service or remote model fallback is used.
- **Safety limits:** Sensitive-looking target/evidence text and confidence below 0.90 are refused. This heuristic is not a guarantee; visual clicking can still hit the wrong benign control. It performs one click only, does not retry, and screenshot pixel changes do not prove task completion. No live desktop click was exercised.
- **Tests:** Final focused screen/vision/UI control/API suite: **53 passed**. Ruff and `git diff --check` passed. Final full suite: **856 passed, 2 existing warnings in 349.95s**. An earlier full run hit one timing-sensitive resident-UI failure; the isolated test and final complete rerun both passed. No live desktop click was exercised.

## 2026-11-24 — Offline Windows Sandbox terminal

- **Changed:** Routed terminal execution through a Windows Sandbox job; it fails closed when `WindowsSandbox.exe` is unavailable. The guest receives no network, clipboard, microphone, camera, printer, or virtual GPU access; only a sanitized tracked-project snapshot, read-only local Python/Git runtimes, and a unique writable result folder are mapped. Guest changes are returned as a bounded local patch, and temporary job contents are removed.
- **Privacy:** No NISHA files, credentials, user-profile folders, queries, or commands are sent to an external service by this path. Explicit SearXNG research remains a separate feature that sends only the query when invoked.
- **Tests:** Focused Sandbox/terminal/API/resident-UI stress suite: 98 passed in 63.15s; final Sandbox/terminal/API suite: 32 passed. Full post-integration suite: 836 passed, 2 existing warnings in 231.96s. Ruff and `git diff --check` passed. Tests found and fixed non-Git project snapshot staging, emergency-stop race handling, guest Python mount mismatch, and job-receipt ID validation.
- **Runtime verification:** After the user enabled Windows Sandbox and restarted, a real offline guest run passed: command output and local patch were returned, host input stayed unchanged, and per-job cleanup completed. The initial run exposed a launcher/session race; the runner now waits for the packaged guest session before releasing mapped files and closes the disconnected session after saving results.
- **Known limits:** Host Windows diagnostics and feature servicing remain governed by Windows privacy settings. The Windows Update log recorded installation of the Sandbox app package during setup; this is separate from NISHA's offline guest execution.

## 2026-11-24 — Gap closure: benchmark, terminal, web research, screen smoke check

- **Changed:** Repeated fixed-suite benchmarking three times per checkout by default; persisted per-run receipts and median/MAD summaries. Added authenticated prepare/approve/execute terminal routes for bounded PowerShell, CMD, Python and Git commands, with Windows Job Object time, CPU, memory, and process-tree limits. Added explicit query-only web research over configured SearXNG, returning bounded public source snippets. Updated text/voice routing, catalog, docs and tests.
- **Why:** Continue the user's request after the phase implementation, closing the noted execution, research, benchmark-evidence and live-capture validation gaps without restructuring working modules.
- **Tests:** Follow-up focused suite: 44 passed in 33.56s; full suite: 820 passed, 2 warnings in 197.18s. Ruff on changed Python files, CLI help, imports and `git diff --check` passed.
- **Screen smoke check:** Captured one JPEG (2560×999, 332,572 bytes), validated only encoding metadata/dimensions/size, and did not inspect pixels or send them to a model.
- **Known limits:** Windows Job Objects constrain resources and process trees; they do not sandbox filesystem/network/credentials. Commands run as the signed-in account. Windows Sandbox, Docker and Podman were unavailable on this host. Web research requires configured SearXNG and summarizes snippets rather than fetching full pages.

## 2026-11-23 — Architecture audit and tool catalog

- **Changed:** Added the architecture audit, persistent state/task/decision/problem/test/experiment records, a metadata catalog for existing tools, and authenticated `GET /tools`; documented discovery in README. Corrected two action-test fixtures to use created sessions.
- **Why:** Establish the current verified baseline and let clients inspect the narrow registered tool surface without reworking established modules.
- **Files:** `NISHA_*.md`, `nisha/tools.py`, `nisha/api.py`, `tests/test_tools.py`, `tests/test_gateway_api.py`, `README.md`.
- **Tests:** Full suite: 780 passed, 2 warnings in 230.50s. Final focused action/tool/API tests: 28 passed in 4.64s. Ruff and `git diff --check` passed.
- **Result:** Existing `propose` and `confirm` semantics remain; catalog metadata is copied on read and does not expose unregistered actions. The two invalid test fixtures now create real sessions.
- **Known issues:** No test failures. Two existing runtime/deprecation warnings remain.

## 2026-11-23 — Phase 4 Windows controls

- **Changed:** Added explicit bounded screen capture and local vision analysis through text/voice routing and authenticated `POST /computer/screen`. Extended UI Automation to right-click, double-click, and drag between uniquely identified controls. Updated command routing, README, and architecture docs.
- **Why:** Complete the next approved specification phase by filling verified screen and named-control gaps while keeping existing UI Automation and gesture controls.
- **Tests:** Full suite: 790 passed, 2 warnings in 188.57s. Focused PC control/screen/API/dialogue tests: 51 passed. Ruff and `git diff --check` passed.
- **Result:** Screen analysis is explicit, bounded, loopback-only and nonpersistent. Generic UI control still blocks sensitive/destructive labels; no coordinate click API was added.
- **Known limits:** Real screen capture was not performed during tests; vision/control contracts were tested with synthetic images and fake app controls. Screen capture requires the optional desktop/Pillow dependencies.

## 2026-11-23 — Phase 5 coding agent

- **Changed:** Added `ProjectCodingAgent` for configured project inspection, bounded source search/read with secret redaction, local-model unified-diff proposals stored without application, and fixed pytest/Ruff execution with JSONL command receipts. Added authenticated project/coding API routes and explicit voice/text routes to inspect/search/run tests/lint.
- **Why:** Reuse NISHA's configured project model while providing evidence-based code checks and command results without arbitrary shell execution.
- **Tests:** Full suite: 798 passed, 2 warnings in 188.12s. Final coding/API tests: 18 passed, including pass/fail/timeout and auth. Ruff and `git diff --check` passed.
- **Result:** Diff proposals remain unapplied until an isolated Git candidate exists; failed and timed-out commands return nonzero receipts; private source values are redacted from model context and response.
- **Known limits:** Project tests run as the signed-in Windows user, not in an OS sandbox. Only pytest/Ruff are exposed; general PowerShell/CMD execution is not implemented yet.

## 2026-11-24 — Phases 6–12 controlled candidate lifecycle

- **Changed:** Added proposal metadata, isolated Git candidate worktrees, a guard against candidate edits to tests/evaluation configuration, baseline/candidate pytest and Ruff verification, a fixed-suite benchmark with a 10% per-suite latency guard for baseline runs at least one second long, local evidence-based research/debugging, persistent self-analysis, a bounded three-attempt/30-minute improvement controller, explicit approval-gated promotion, commit-based rollback, and startup recovery for interrupted operations. Added authenticated API routes, voice/text routes for local research/debugging and bounded improvement, and architecture/API documentation.
- **Why:** Continue the specification after the verified Phase 1–5 checkpoint while leaving the stable checkout untouched until human approval.
- **Tests:** Candidate lifecycle suite: 10 passed in 19.13s; authenticated API suite: 10 passed in 1.62s. Full suite: 811 passed, 2 warnings in 212.90s. Ruff on changed Python files and `git diff --check` passed. CLI help smoke check passed.
- **Result:** Candidate patches are applied only in a worktree; promotion fast-forwards only the recorded base branch while the base commit is unchanged; rollback uses a revert commit. Candidate results, receipts, benchmark data and per-repository version pointers persist under `data/experiments/`.
- **Known limits:** Benchmark timings are single-run and should not be treated as statistically stable. Verification code runs under the signed-in account, not an OS sandbox. Local research searches configured source/docs; no new internet research agent or arbitrary terminal executor was added.
