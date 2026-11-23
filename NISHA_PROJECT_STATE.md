# NISHA Project State

Updated: 2026-11-24

## Current State

- Version: 0.1.0 (from `pyproject.toml`)
- Working branch: `codex/nisha-agent-phases`; Phase 1–5 checkpoint is commit `cc520a9`. Phase 6–12 changes are currently uncommitted.
- Entry point: `python -m nisha` → `nisha.cli:main`.
- Architecture: modular Python package, local-first Ollama/LiteLLM core, PySide6 desktop/voice clients, SQLite state, bounded action adapters. Details: [architecture audit](NISHA_ARCHITECTURE_AUDIT.md), [existing architecture](docs/architecture.md).
- Configuration: `config/nisha.yaml`; local/private values in `.env`; runtime state under `data/`.
- Current task: Phases 1–12 have been implemented and regression-tested; inspect final diff, persist results, and create a second local checkpoint.
- Completed: phase 1 audit; phase 2 architecture review (existing boundaries retained); phase 3 catalog and authenticated tool discovery endpoint.
- Next: review/stage only the implementation and documentation changes on this branch, preserving the unrelated untracked `trader/` directory.
- Known issues: no test failures from the final full suite. Two existing test warnings remain: pywinauto COM initialization and pypdf `add_js` deprecation.
- Current tools: list/read/delete files inside `data/workspace`; delete is one-use, expiring, content-bound approval. Arbitrary shell and Python execution are not registered.
- Phase 4 progress: `nisha/screen.py` implements explicit size-bounded screen capture and local-only vision analysis. Core routes explicit screen questions; authenticated `POST /computer/screen` is available. Automated checks use synthetic images; no real desktop pixels were captured during tests.
- Phase 4 controls: existing UI Automation gained right-click, double-click and drag between uniquely named controls. Existing named-control typing, key allowlist, app/window focus/launch, scroll and camera-guided pointer remain. External/destructive labels stay blocked from generic control calls.
- Phase 5: `nisha/coding.py` inspects configured project source with path/size/private-file limits and secret redaction; proposes local-model diffs saved without applying them; runs only fixed pytest/Ruff commands with bounded output, timeout, filtered environment and JSONL receipts. Authenticated API and explicit voice/text routes are wired. Patch application is delegated to Phase 6's isolated worktree.
- Phase 6: `nisha/versioning.py` records per-repository stable pointers and creates Git worktree candidates only from clean tracked checkouts. It validates saved patch paths, applies only inside the candidate worktree, and records experiment manifests. Unrelated untracked directories are left outside the candidate.
- Phase 7: candidate verification runs the fixed suite on both baseline and candidate and records separate structured receipts.
- Candidate patches cannot modify test files/directories or pytest/Ruff configuration, keeping the evaluation gate independent from model-generated changes.
- Phase 8: benchmark runs pytest and Ruff on baseline and candidate, records quality and elapsed times, and requires candidate checks to pass. Each passing baseline suite taking at least one second has a 10% elapsed-time regression guard; shorter timings are reported but not gated because launch noise dominates. Timings are single-run comparisons, not statistical benchmarks.
- Phase 9: local configured project source/documentation search and bounded test-failure inspection return evidence references; existing browser/search adapters remain responsible for external research.
- Phase 10: diagnostics summarize coding command receipts, audit events, turn outcomes, slow commands, observation counts, and optional psutil process/system CPU and memory.
- Phase 11: API/voice improvement run tries up to three distinct proposals within a 30-minute cap, includes captured failures in the next proposal prompt, and stops on a duplicate patch. Failed candidates are recorded as rejected; successful ones stop at human review.
- Phase 12: promotion requires authenticated `approved: true` plus `PROMOTE`, unchanged base branch/head, clean tracked checkout, and a successful benchmark gate. Rollback requires `ROLLBACK`, creates `git revert`, and refuses after branch movement. Startup reconciles interrupted operation metadata without rewriting source files.
- Persistent limits: pytest/Ruff run as the signed-in Windows account and are not OS-sandboxed. Arbitrary shell execution is not exposed. `/research` searches local configured project material; external web search uses existing adapters.
- Verification: `.venv\\Scripts\\python.exe -m pytest -q` — **811 passed, 2 existing warnings in 212.90s**. Focused candidate lifecycle — **10 passed in 19.13s**; authenticated API — **10 passed in 1.62s**. Changed-file Ruff passed; `git diff --check` passed.
- Recovery: inspect Git status, this file, `NISHA_TASKS.md`, and the audit before continuing. Preserve the unrelated untracked `trader/` directory.

## Last Verified

- Focused Phase 4 control/screen/API tests: 51 passed in 19.58s.
- Full pre-change baseline: 777 passed, 2 failed in 259.84s; both invalid test-session fixtures were corrected.
- Full suite after Phase 5: 798 passed, 2 warnings in 188.12s.
- Full suite after Phases 6–12: 811 passed, 2 warnings in 212.90s.
- Candidate lifecycle: 10 passed in 19.13s; API: 10 passed in 1.62s.
- Changed-file Ruff and `git diff --check`: passed. CLI `python -m nisha --help`: passed.
