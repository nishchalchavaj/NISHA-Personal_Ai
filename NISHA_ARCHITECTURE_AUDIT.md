# NISHA Architecture Audit

**Audit date:** 2026-11-23
**Repository:** `E:\NISHA`
**Branch at audit start:** `main`
**Current commit:** `9bfaa52` (`Merge remote-tracking branch 'origin/main'`)

The architecture and gap findings below describe the project before the Phase 3 changes in this task; the roadmap and verification sections record the resulting updates.

## Current Architecture

NISHA is an existing Python 3.11–3.13 Windows desktop assistant, packaged as `nisha-assistant` 0.1.0. It is a modular application, not a single-file prototype. `nisha/__main__.py` delegates to `nisha.cli:main`, which selects text chat, desktop, voice, API, gateway, service, doctor, or backup entry points. The PySide6 desktop and terminal clients share `NishaCore`.

The core composes conversation policy and domain services. The local model path is `NishaCore` → bounded context and `Gateway` → authenticated local LiteLLM → local Ollama models. YAML in `config/nisha.yaml` is the application configuration source; settings are validated in `nisha/settings.py`. No implicit cloud fallback is configured. Separate external-task workers exist but are opt-in and isolated from base conversation.

Major source areas:

| Area | Existing modules and responsibility |
| --- | --- |
| Entry points and composition | `nisha/cli.py`, `nisha/core.py`, `nisha/__main__.py` |
| Conversation and context | `context.py`, `dialogue.py`, `interaction.py`, `conversation_style.py`, `conversation_learning.py`, `task_planning.py` |
| Model gateway and services | `gateway.py`, `http_stream.py`, `services.py`, `health.py` |
| Voice | `listening.py`, `microphones.py`, `speech_worker.py`, `voice.py`, `voice_profile.py`, `neural_wake.py`, `ui/listener.py` |
| Desktop UI | `nisha/ui/` (Qt window, conversation, resident/tray, workers, dialogs, visuals) |
| Memory and persistence | `storage.py`, `memory.py`, `knowledge.py`, `preferences.py`, `reinforcement.py` |
| Tools and actions | `tools.py`, `local_utilities.py`, `desktop.py`, `pc_control.py`, `system_actions.py`, `window_actions.py`, `browser_session.py`, `workflows.py`, `automation.py`, `connections.py`, `devices.py`, `mail.py` |
| API and safety | `api.py`, `api_security.py`, `file_security.py`, `document_limits.py`, `image_security.py`, `url_security.py`, `video_security.py`, `safety-related tests` |
| Diagnostics and logs | `logging_setup.py`, `errors.py`, `scripts/verify_*.py`, `scripts/verify_all.py` |
| Archived prototype | `legacy/`; README and architecture notes state that active imports do not use it |

## Existing Capabilities

- Local text conversation through Ollama with LiteLLM gateway, streaming, bounded context, local cancellation, health checks, and persistent SQLite history.
- Local Whisper speech recognition, Windows speech output, wake-word handling, microphone management, and a PySide6 dashboard with tray/resident lifecycle.
- Selected local memories, searchable imported references, preference/feedback learning, and conversation review workflows.
- Authenticated loopback API and local service startup/recovery.
- A constrained file tool service for listing, reading, and recycle-bin deletion inside `data/workspace`. Deletion requires a one-use, expiring approval bound to the file digest. Arbitrary shell/Python execution is explicitly blocked.
- Other specific Windows actions and user-configured workflows (apps, browsers, windows, documents, email, devices) are implemented in dedicated adapters with their own validation/approval boundaries. These are not a general arbitrary computer-use agent.
- Existing automated tests cover core, API, memory, voice, UI, workflows, tools, and security. Separate verification scripts exercise selected real Windows, local-model, voice, and UI paths.
- Dependencies and optional feature groups are declared in `pyproject.toml`; exact environment pins are in `requirements.lock`. Configuration is in `config/nisha.yaml`; `.env` and user data are ignored by Git.

## Missing Capabilities

- A central general-purpose tool catalog with discoverable schemas, risk/approval metadata, and one dispatch interface. Current `ToolService` is deliberately narrow and its supported actions are implicit in conditional logic.
- General tool invocation/planning from conversational requests. The README explicitly says the model does not yet invoke file tools automatically.
- Dedicated computer, coding, research, debugging, testing, review, and self-improvement agents with isolated inputs and outputs.
- General terminal execution with structured receipts (command, working directory, timestamps, exit code, stdout, stderr); no arbitrary terminal execution should be added without a separate policy and approval design.
- A bounded candidate workflow and local promotion/rollback now exist. Benchmarking is a fixed pytest/Ruff plus elapsed-time comparison, not a statistical performance suite. Broad evaluator coverage and sandboxed test execution remain missing.
- Persistent continuity files requested by the specification beyond existing `docs/` architecture, roadmap, security, and verification documentation.

## Problems

- `NishaCore` is a broad composition root with many dependencies and substantial workflow routing. It is a candidate for gradual boundary extraction only where concrete coupling or tests show a benefit.
- Tool definitions, action authorization, and behavior are coupled in `ToolService.propose`; clients cannot ask the running application for a machine-readable list of available tools or their approval requirements.
- Existing action adapters provide useful capabilities, but there is no uniform tool contract or cross-tool execution receipt.
- The architecture docs and README are detailed, but verification claims are historical and environment-specific; they must not be mistaken for a fresh run.
- No `AGENTS.md` was found in the repository listing. The working tree has an unrelated untracked `trader/` directory, which must be preserved.

## Risks

- Moving modules or rewriting core dispatch can break established voice, startup/shutdown, privacy, session, or approval behavior. The existing tests and user workflows are valuable compatibility constraints.
- Adding a general shell or computer-control tool would substantially expand the attack surface. Existing refusal of arbitrary shell/Python actions is an intentional boundary, not a missing implementation to bypass.
- Existing app, browser, email, and device integrations have different verification evidence; accepting a process/API request is not always proof the intended user-visible state changed.
- The full automated baseline is being run before code changes. It has reported failures; exact tests and final counts will be recorded after the run completes. No new tests are being represented as passed until executed.

## Recommended Refactoring

1. Keep the current client/core/domain-module structure. Do not reorganize files just to match the target tree: current voice, UI, storage, settings, safety, and action modules already provide those boundaries.
2. Add a small explicit registry/catalog over the existing safe file actions, including descriptions and whether confirmation is required. Keep existing `propose`/`confirm` behavior and API compatibility.
3. Add an authenticated read-only API endpoint for tool discovery. It must not add automatic model invocation or broaden filesystem, command, or computer-control permissions.
4. Use subsequent work to define a uniform execution receipt and policy for newly introduced tools, then add tools only in their designated later phase.
5. Extract responsibilities from `NishaCore` only when a narrow change can preserve behavior and be measured by focused regression checks.

## Target Architecture

```text
Terminal / Desktop / Authenticated API
                  |
             NishaCore
     conversation and task routing
        /         |          \
  Voice/UI    Memory/Store    Tool catalog and policy
                                  |
                    registered, bounded adapters
                    (workspace files, app/browser,
                     configured workflows/devices)
                                  |
                           Windows / local services

Future, isolated layers:
coding/research/debugging agents -> candidate worktree -> tests/evaluator
                                  -> security review -> human approval -> promotion
```

The target preserves local-first conversation, existing clients, user settings, and action-specific approval. Self-improvement and promotion remain future capabilities and must not alter safety controls automatically.

## Implementation Roadmap

| Phase | Result from this audit and execution plan |
| --- | --- |
| 1. Inspect and document | Complete. This audit records current structure, capability coverage, gaps, risks, and baseline/final verification evidence. |
| 2. Modular architecture | Existing package boundaries already satisfy the modularity goal. Preserve them; avoid a no-benefit source restructure. Extract only proven coupling in a future narrow change. |
| 3. Reliable tool system | Complete for the existing workspace file tools: an explicit catalog and authenticated discovery endpoint are in place; path limits, approval, audit, and shell refusal remain. |
| 4. Windows computer control | Complete for the scoped desktop interface. Existing UIA supports named windows/controls, focus, safe text fields, limited shortcuts and scroll; Gesture Studio offers camera-guided pointer/click. Added explicit bounded screen capture/local analysis, named-control right/double click and drag. No general coordinate click API was added because it cannot identify the target or reliably apply the current risk checks. |
| 5. Coding agent | Complete foundation: configured project listing/search/read with path/size/private-file limits and secret redaction; local model proposes review-only unified diffs; fixed pytest/Ruff commands return bounded structured receipts, record JSONL, timeout and report failures. Patch application awaits Phase 6 isolation. |
| 6. Git/version management | Complete foundation: clean tracked checkout guard, validated worktree patch application, branch/base recording, per-repository stable pointers, and experiment manifests. |
| 7. Testing and verification | Complete foundation: fixed pytest/Ruff receipts on baseline and candidate, bounded execution, and result persistence. |
| 8. Benchmark system | Complete foundation: baseline/candidate pass results and single-run per-suite elapsed-time comparison with a 10% slowdown guard for passing baseline commands at least one second long. Statistical repetitions and broad task-success metrics remain future work. |
| 9. Research/debugging | Complete local foundation: cited source/documentation search and captured failure inspection. Internet research continues through existing browser/search adapters. |
| 10. Self-analysis | Complete foundation: coding receipts, audit/outcome counts, slow commands, user observation counts, and optional psutil snapshots; no causal claims are invented. |
| 11. Controlled self-improvement | Complete bounded workflow: up to three distinct proposals within 30 minutes, isolated candidates, failure-informed retries, verification and benchmark, then stop for review or archive failures. |
| 12. Promotion/rollback | Complete: explicit authenticated human approval, fast-forward-only promotion from unchanged base, commit-based rollback, and startup metadata recovery. |

## Verification

**Baseline before implementation:** `.venv\Scripts\python.exe -m pytest -q` completed with **777 passed, 2 failed** in 259.84 seconds. Both failures are in `tests/test_contextual_actions.py` and pass an uncreated `test-session`; `Store.history()` raises `ValueError("Unknown session. Start a new conversation.")` before their action assertions. These are pre-existing baseline failures, recorded for comparison rather than changed as part of this task.

**Post-change verification:** After Phases 1–5, `.venv\Scripts\python.exe -m pytest -q` completed with **798 passed, 2 warnings**. After Phases 6–12, evaluation-path guard and timing-noise fix, the full suite completed with **811 passed, 2 warnings in 212.90 seconds**. The candidate lifecycle suite completed with **10 passed in 19.13 seconds**, and the authenticated API suite with **10 passed in 1.62 seconds**. Changed-file Ruff and `git diff --check` passed; `python -m nisha --help` completed successfully. The warnings are the existing pywinauto COM initialization notice and pypdf `add_js` deprecation warning.

## Audit Change Log

- Created this audit before implementation changes, as required by “YOUR FIRST TASK.”
- Phase 2 review: the repository already uses separate modules for major concerns; no source restructuring is justified by the inspected evidence.
- Phase 3 added an explicit safe tool catalog and authenticated `GET /tools` discovery; it does not broaden execution permissions.
- Phases 6–12 added the candidate/testing/benchmark/research/analysis/improvement lifecycle documented above. Candidate lifecycle behavior was exercised in temporary Git repositories; no self-improvement patch was applied to this NISHA checkout.
