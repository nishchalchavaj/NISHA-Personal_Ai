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
