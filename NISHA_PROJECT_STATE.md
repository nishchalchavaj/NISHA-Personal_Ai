# NISHA Project State

Updated: 2026-11-23

## Current State

- Version: 0.1.0 (from `pyproject.toml`)
- Working branch: `codex/nisha-agent-phases` (created for the remaining specification work); working changes are uncommitted.
- Entry point: `python -m nisha` → `nisha.cli:main`.
- Architecture: modular Python package, local-first Ollama/LiteLLM core, PySide6 desktop/voice clients, SQLite state, bounded action adapters. Details: [architecture audit](NISHA_ARCHITECTURE_AUDIT.md), [existing architecture](docs/architecture.md).
- Configuration: `config/nisha.yaml`; local/private values in `.env`; runtime state under `data/`.
- Current task: Phase 6 Git/version management, followed sequentially by phases 7–12.
- Completed: phase 1 audit; phase 2 architecture review (existing boundaries retained); phase 3 catalog and authenticated tool discovery endpoint.
- Next: build Phase 6 isolated Git candidate/worktree management; require a clean source checkout, keep candidates in separate worktrees, and retain human approval for promotion.
- Known issues: no test failures from the final full suite. Two existing test warnings remain: pywinauto COM initialization and pypdf `add_js` deprecation.
- Current tools: list/read/delete files inside `data/workspace`; delete is one-use, expiring, content-bound approval. Arbitrary shell and Python execution are not registered.
- Phase 4 progress: `nisha/screen.py` implements explicit size-bounded screen capture and local-only vision analysis. Core routes explicit screen questions; authenticated `POST /computer/screen` is available. Automated checks use synthetic images; no real desktop pixels were captured during tests.
- Phase 4 controls: existing UI Automation gained right-click, double-click and drag between uniquely named controls. Existing named-control typing, key allowlist, app/window focus/launch, scroll and camera-guided pointer remain. External/destructive labels stay blocked from generic control calls.
- Phase 5: `nisha/coding.py` inspects configured project source with path/size/private-file limits and secret redaction; proposes local-model diffs saved without applying them; runs only fixed pytest/Ruff commands with bounded output, timeout, filtered environment and JSONL receipts. Authenticated API and explicit voice/text routes are wired. Patch application is delegated to Phase 6's isolated worktree.
- Recovery: inspect Git status, this file, `NISHA_TASKS.md`, and the audit before continuing. Preserve the unrelated untracked `trader/` directory.

## Last Verified

- Focused Phase 4 control/screen/API tests: 51 passed in 19.58s.
- Full pre-change baseline: 777 passed, 2 failed in 259.84s; both invalid test-session fixtures were corrected.
- Full suite after Phase 5: 798 passed, 2 warnings in 188.12s.
- Ruff on changed Python files: passed. `git diff --check`: passed.
