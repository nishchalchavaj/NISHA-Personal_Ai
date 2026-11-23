# NISHA Changelog

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
