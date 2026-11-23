# NISHA Project State

Updated: 2026-11-24

## Current State

- Version: 0.1.0 (from `pyproject.toml`)
- Working branch: `codex/nisha-agent-phases`; Phase 1–5 checkpoint is `cc520a9`, Phases 6–12 are committed as `33a4cdb`, and the latest checkpoint adds the offline Windows Sandbox terminal integration. Only the unrelated untracked `trader/` directory remains outside these commits.
- Entry point: `python -m nisha` → `nisha.cli:main`.
- Architecture: modular Python package, local-first Ollama/LiteLLM core, PySide6 desktop/voice clients, SQLite state, bounded action adapters. Details: [architecture audit](NISHA_ARCHITECTURE_AUDIT.md), [existing architecture](docs/architecture.md).
- Configuration: `config/nisha.yaml`; local/private values in `.env`; runtime state under `data/`.
- Current task: Windows Sandbox integration, real guest end-to-end verification, and post-change stress/regression are complete.
- Completed: phase 1 audit; phase 2 architecture review (existing boundaries retained); phase 3 catalog and authenticated tool discovery endpoint.
- Next: remaining master-spec boundaries are recorded in the architecture audit. Keep unrelated untracked `trader/` outside commits.
- Known issues: no test failures from the final full suite. Two existing test warnings remain: pywinauto COM initialization and pypdf `add_js` deprecation.
- Current tools: list/read/delete files inside `data/workspace`; delete is one-use, expiring, content-bound approval. Authenticated terminal prepare/execute now requires an offline Windows Sandbox, limits execution to a sanitized tracked-file snapshot and read-only local runtimes, disables network/clipboard/audio/video/printer/vGPU, and returns changes as a local patch. It fails closed and never runs commands on the host if Sandbox is unavailable.
- Phase 4: `nisha/screen.py` implements explicit size-bounded screen capture and local-only vision analysis. Core routes explicit screen questions; authenticated `POST /computer/screen` is available. Live smoke check captured a 2560×999 JPEG (332,572 bytes); only format, dimensions, and size were inspected, not image pixels.
- Phase 4 controls: existing UI Automation gained right-click, double-click and drag between uniquely named controls. Existing named-control typing, key allowlist, app/window focus/launch, scroll and camera-guided pointer remain. External/destructive labels stay blocked from generic control calls.
- Phase 5: `nisha/coding.py` inspects configured project source with path/size/private-file limits and secret redaction; proposes local-model diffs saved without applying them; runs only fixed pytest/Ruff commands with bounded output, timeout, filtered environment and JSONL receipts. Authenticated API and explicit voice/text routes are wired. Patch application is delegated to Phase 6's isolated worktree.
- Phase 6: `nisha/versioning.py` records per-repository stable pointers and creates Git worktree candidates only from clean tracked checkouts. It validates saved patch paths, applies only inside the candidate worktree, and records experiment manifests. Unrelated untracked directories are left outside the candidate.
- Phase 7: candidate verification runs the fixed suite on both baseline and candidate and records separate structured receipts.
- Candidate patches cannot modify test files/directories or pytest/Ruff configuration, keeping the evaluation gate independent from model-generated changes.
- Phase 8: benchmark runs pytest and Ruff three times by default on baseline and candidate, records every receipt and reports median elapsed time plus median absolute deviation. Each passing baseline suite with median >=1 second has a 10% median regression guard; shorter timings are reported but not gated because launch noise dominates. This is repeated local timing, not a broad benchmark corpus.
- Phase 9: local configured project source/documentation search and bounded test-failure inspection return evidence references. Separate query-only web research uses the configured SearXNG JSON endpoint and returns bounded public snippets/links; it does not fetch full pages or attach local project data.
- Phase 10: diagnostics summarize coding command receipts, audit events, turn outcomes, slow commands, observation counts, and optional psutil process/system CPU and memory.
- Phase 11: API/voice improvement run tries up to three distinct proposals within a 30-minute cap, includes captured failures in the next proposal prompt, and stops on a duplicate patch. Failed candidates are recorded as rejected; successful ones stop at human review.
- Phase 12: promotion requires authenticated `approved: true` plus `PROMOTE`, unchanged base branch/head, clean tracked checkout, and a successful benchmark gate. Rollback requires `ROLLBACK`, creates `git revert`, and refuses after branch movement. Startup reconciles interrupted operation metadata without rewriting source files.
- Privacy and verification limits: the real guest smoke run used a temporary one-file project, with guest networking disabled. It returned a local patch, left the host file unchanged, and cleaned the new job folder. No project data or research query was sent to an external service. Windows Update recorded Sandbox package servicing during setup; OS servicing is separate from NISHA and follows Windows privacy settings. Explicit SearXNG research remains opt-in and sends only its user-supplied query. Real microphone/app interactions, external SearXNG, pixel-level screen interpretation, general coordinate clicks, and broad task-success/GPU metrics remain outside this run's verified scope.
- Verification: `.venv\\Scripts\\python.exe -m pytest -q` — **837 passed, 2 existing warnings in 305.51s**. Focused Sandbox/terminal/API suite: **33 passed in 17.47s**. Real Windows Sandbox E2E: command exited 0, networking disabled, patch saved locally, host input unchanged, and no new job folder remained. Changed-file Ruff and `git diff --check` passed. Stress tests caught and verified fixes for non-Git project staging, launcher/session startup race, stop/exit handling, guest Python mount consistency, forged job receipts, and job cleanup.
- Recovery: inspect Git status, this file, `NISHA_TASKS.md`, and the audit before continuing. Preserve the unrelated untracked `trader/` directory.

## Last Verified

- Focused Phase 4 control/screen/API tests: 51 passed in 19.58s.
- Full pre-change baseline: 777 passed, 2 failed in 259.84s; both invalid test-session fixtures were corrected.
- Full suite after Phase 5: 798 passed, 2 warnings in 188.12s.
- Full suite after Phases 6–12: 811 passed, 2 warnings in 212.90s.
- Candidate lifecycle: 10 passed in 19.13s; API: 10 passed in 1.62s.
- Changed-file Ruff and `git diff --check`: passed. CLI `python -m nisha --help`: passed.
- Post-Sandbox focused suite: 98 passed in 63.15s; final Sandbox/terminal/API subset: 32 passed; final full suite: 836 passed, 2 warnings in 231.96s.
- Real Windows Sandbox E2E: passed offline command, local patch, unchanged host input, and per-job cleanup.
- Final full suite after launcher/session lifecycle fix: 837 passed, 2 warnings in 305.51s.
