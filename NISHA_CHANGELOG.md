# NISHA Changelog

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
