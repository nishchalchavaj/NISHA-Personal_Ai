# Prototype preservation and cleanup

The active source is now `nisha/`. Old application modules, agents, voice experiments,
Windows automation, configuration, helper scripts and launchers were moved to
`legacy/prototype/`. The previous `venv` is archived; `.venv` is the active environment.
Old memory databases, documents, workspace files and logs remain inside the archive.

The original transparent wall dashboard, table layout, teal orb renderer and application
icon were restored in the active UI. The presentation connects to the new local core;
it has no imports from the archived application. The obsolete window picker was omitted.
The earlier logging approach and STT/TTS choices informed the new adapters; the old runtime
and command router are not imported or executed. Redundant entry points and UI experiments
were removed from the active project rather than mixed into the new application.

The hard-coded Tavily credential was removed from the archived settings file. Rotate that
credential through Tavily before any future web-search use. No Tavily integration is active.

The archive is intentionally excluded from Git because it contains personal files and
databases. It remains recoverable locally; make an independent backup before clearing it.
Previous memories have not been silently imported into the new memory store. To carry over
useful facts, review/export the old database and explicitly select the facts to migrate.
Do not launch the archived application as part of the new startup path.

Git metadata was initialized because the previous `.git` directory had no usable repository.
No remote, commit, push, or publication was created.

