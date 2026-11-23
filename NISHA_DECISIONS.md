# NISHA Decisions

## 2026-11-23 — Preserve existing modular source layout

**Decision:** Do not move or rename modules during Phase 2.
**Reason:** Audit found distinct modules for core, voice, UI, storage, tools, configuration, safety, and evaluation; a structural shuffle has no demonstrated benefit and creates regression risk.
**Alternatives considered:** Recreate the specification's illustrative folder tree or extract additional agents immediately.
**Consequences:** Keep current imports and behavior; extract responsibilities only when a concrete need and narrow verification path exist.

## 2026-11-23 — Make existing tools discoverable without broadening permissions

**Decision:** Publish metadata for the existing file tools via an authenticated read-only endpoint.
**Reason:** Clients could not discover supported actions and confirmation requirements.
**Alternatives considered:** Add arbitrary shell, Python, or model-driven tool execution.
**Consequences:** `GET /tools` lists only workspace list/read/delete; deletion still needs approval; no automatic invocation is added.

## 2026-11-24 — Keep terminal execution inside an offline Windows Sandbox

**Decision:** Require Windows Sandbox for production terminal commands and fail closed when it is unavailable. Map a sanitized project snapshot and local runtimes read-only, expose only one unique writable result folder, disable guest networking and device/clipboard sharing, and return changes as a local patch.
**Reason:** The user asked for local execution without personal/project data leaving the PC. A host Job Object limits resources but does not isolate credentials, filesystem or network.
**Alternatives considered:** Continue host execution with Job Objects; mount the project writable; allow network access; silently fall back to host when Sandbox is unavailable.
**Consequences:** No command runs until the optional feature is enabled. A real guest boot has not yet been verified because the prior UAC enable attempt was canceled. This execution path makes no remote project/query calls.
