# Verification performed

The following checks passed during this build. No real private data was sent to an external
model. Live model checks used temporary synthetic conversation and memory data.

The most recent front-page / three-display update is tracked in `NISHA_TEST_STATUS.md`.
Its center-display choice and virtual desktop coordinate mapping are unit tested with
simulated display geometries; no physical multi-monitor window move is claimed here.

| Check | Result |
| --- | --- |
| Automated regression suite | 262 passed |
| Ruff code/import checks | Passed |
| Installed dependency compatibility (`pip check`) | Passed |
| Ollama and authenticated LiteLLM startup | Passed |
| Llama 3.2 streaming, memory retrieval, follow-up context | Passed against the real local model |
| Qwen3 14B streaming, memory retrieval, follow-up context | Passed against the real local model |
| Windows TTS → cached Whisper → local Core/model → Windows TTS | Passed with synthetic WAV files |
| Desktop submission and worker completion | Passed offscreen with a deterministic gateway |
| Desktop assets and layout | Original transparent teal dashboard restored, rendered and visually inspected (`data/desktop-preview.png`) |
| Wall/table and monitor/projector toggles, desktop model/memory commands | Passed offscreen |
| Desktop context across model changes and mute indicator | Passed offscreen; opening the desktop now starts fresh instead of restoring old display |
| Wake opens fresh conversation | Cached large-v3 ASR with synthetic speech drove the real Qt bridge: standalone Hey Nisha restored the hidden window, combined wake/command created another session, follow-up stayed in that session and Goodbye hid it without muting; old chat preserved |
| Resident close, mute and explicit quit | Offscreen checks passed: close hides without stopping engine, mute prevents wake reopening/reset, explicit quit stops capture, hidden completion leaves follow-up gate closed |
| Wake during thinking | Wake/close/stop filtering, generation interruption, queued new-session command and session isolation passed; uncertain bare wakes don't enable ambient commands |
| Spoken interruption | Stop, Enough, That's enough, Hey Nisha stop speaking and Be quiet passed real cached local ASR in 0.36–0.61s per clip. Enough passed rolling capture → actual local ASR → Qt → native muted SAPI cancellation in 1.19s, retaining the same conversation. Window close purged real muted SAPI output in 0.08s. Echo filtering, continuous-speech windows, cancellation on hide/quit and stale output rejection passed regression tests |
| Single resident process | Lock/socket show/quit and rejection of unknown operations passed; native launcher reopening reused the running desktop |
| Windows login startup | Hidden launcher command registered for the current user and verified enabled; initialization respects saved opt-out; PowerShell parsed successfully; actual next-login execution not yet observed |
| Wake word → website action → local conversational follow-up | Passed with real cached Whisper, synthetic WAVs and simulated browser launch |
| Background rejection, mute invalidation, speech endpoints and browser failure handling | Passed regression tests |
| Physical microphone access | Concurrent USB, webcam and built-in capture verified at 16 kHz |
| Microphone priority and failure recovery | Airwave driver capture stalled; isolated helper could not freeze healthy capture; USB fallback and clean shutdown passed |
| Microphone stability during wake phrases | Selection holds a healthy speaking input through syllable gaps and the configured speech endpoint; dead/stale inputs still fall back and silent preferred inputs do not earn a hold; regression checks passed |
| Windows default microphone | Default input is now used for live listening and enrollment; one isolated capture worker, endpoint-change reopening and generation reset tested; actual default USB capture and warm resume passed |
| Short wake phrases | Hey Nisha, Nisha, Hey Neesha and Neesha passed actual local Silero segmentation and cached large-v3 ASR with synthetic Windows speech |
| Live wake failure found | Live logs showed recognized wakes discarded under the full-command confidence threshold; wake acoustic evidence now has a separate threshold, while uncertain command execution remains blocked |
| Bounded local ASR | Real cached ASR passed through an isolated worker; deliberately stuck worker was terminated at its deadline, stop cancellation returned promptly, next request can start a fresh worker |
| Fresh manual opening | Startup, launcher and tray opening now start a fresh visible session; old text is cleared and stored history remains; regression and offscreen desktop checks passed |
| Personal voice enrollment | Review/save boundary, exact WAV/transcript hashes, duplicate rejection, labels, silence/clipping checks, disjoint training/calibration/test and failed-training preservation passed; retraining beyond 100 takes preserves originals |
| User's personal wake model | Trained locally with 11 wake takes and 60 non-wake/command takes; noisy webcam padding trimmed in features only. All 71 originals retained. Two held-out wake takes passed; zero false wakes in 12 held-out non-wake takes. Model activated; Whisper weights unchanged |
| Real enrollment recorder | USB microphone captured a four-second take with responsive Qt; no audio saved or transcribed; sample screen rendered and inspected |
| Spoken dismissal | Requested close/quiet/bye/shutup variants hide and reset the gate without muting; exact phrase boundaries, uncertain speech rejection, dismissal during thinking and subsequent wake passed |
| Continuous capture lifecycle | Healthy capture workers stayed warm; paused hardware closed; warm resume about 0.7 seconds in the device diagnostic |
| Accurate speech model | Downloaded large-v3, local CUDA inference; six synthetic command cases passed including YouTube versus "your book", custom domain, writing, code and email |
| Custom domain action after real ASR | "OpenExample.org" recognized and correctly dispatched as `https://example.org`; browser adapter simulated |
| Conversation wake aliases | Requested Nisha/Neesha/Nishaa/Nisa/Meesha variants, indefinite follow-ups, sleep/mute reset and pending-audio invalidation passed |
| Real local workflow generation | Qwen generated saved Notepad content, readable Word file, valid Python source and structured email draft; editor/mail adapters simulated in this check |
| Actual Windows editor actions | Generated synthetic files opened in real Notepad and VS Code; Word opened its `.docx` through COM; process titles and Word's document collection confirmed |
| Gmail review UI | Masked setup dialog, local draft review, approval button and one-time fake transport send passed offscreen |
| Gmail transport | TLS and exact approved recipient/subject/body verified with simulated SMTP; missing account made no network request |
| Gmail inbox and reply context | Read-only IMAP/PEEK, exact selected reply address/thread, session/expiry boundaries, mismatched named recipients and fresh/replayed/changed approvals passed with simulated transport |
| Structured email generation | JSON-schema payload forwarding, whole-object retries with increasing output room and rejection of still-truncated drafts passed; real Qwen reply to selected synthetic email produced a valid local draft, no SMTP call |
| Automatic response completion | Actual local Llama answer completed in four deliberately restricted 64-token segments (181 words). Native final-assistant prefill preserves mid-word continuations; final-delta text, boundary repetition, bounded continuation context, stalled progress, interruption and filter distinction passed contract tests. Context-first supplier request produced a complete Qwen JSON draft (53 body words), with no email transport or approval invoked |
| Direct HTTP devices | Local HTTP simulator received the exact light POST, reported the resulting state through GET and passed failure handling; no real hardware used |
| Device status | Actual last-success durations, never-seen distinction, recheck after restart, no redirect following, auth separation and response bounds passed |
| Connection/project dialog | Default project chooser/form saved locally; device credential field masked; examples are not activated automatically |
| CCTV snapshot UI | Real loopback HTTP JPEG snapshots refreshed in the muted glass panel, Qt stayed responsive, failure cleared the old image and recovery/dismissal passed; preview `data/desktop-camera-preview.png` |
| Saved routines | Actual folder/app/browser/device steps only, session-scoped learning, durable registry, path/type validation and stop-on-failure passed with simulated launches |
| Presentation preparation | Selected slide text/supporting notes read, files copied without moving originals, notes/checklist and readiness manifest saved; real local-model notes included source requirements/budget, native opening simulated |
| Configured research | SearXNG JSON transport simulated; only exact public query transmitted, private requirements stayed in local synthesis, source URLs and failure receipts passed; no live search endpoint configured |
| Windows Credential Manager | Unique synthetic Gmail credential written/read and then removed; no password appeared in the local account file |
| Preference learning | Feedback patterns, correction/reset, session/restart durability and one-turn detail overrides passed |
| Real local learned behavior | Short photosynthesis answer stayed under 75 words; detail override was 377 words; saved brief preference remained active; imported synthetic Zephyr voltage retrieved correctly |
| Knowledge imports | Text and Word tables, deduplication, bounds, source retrieval/forgetting and reference-only prompt placement passed |
| Learning/task dialogs | Local paste import, masked provider key, exact-task preview, isolated payload, local result/history learning passed with fake HTTP transport |
| External task adapters | OpenAI/Gemini/Claude request/response contracts, OpenAI `store:false`, approval mutation/expiry/cancel/replay and secret-safe failures passed using fake HTTP |
| Public image service | Live Openverse topic lookup and JPEG thumbnail retrieval passed; Wikimedia returned HTTP 403, with no repeated retry after failure |
| Floating visual card | Offscreen image rendering, transparent glass styling, right-middle placement, dismissal and original dashboard preservation passed; preview `data/desktop-visual-preview.png` |
| Video playback | Real Qt Multimedia decoded and played a synthetic local H.264 MP4, muted; clearing source released the file for cleanup |
| Actual Windows browser action | `OPEN YOUTUBE` invoked the default browser successfully |
| Actual Windows minimize/close | Native cross-process requests verified on three disposable Qt app windows: all minimized, two closed, one refused and was reported as remaining open; no user app was changed. Uncertain spoken commands still require confirmation |
| Live local API | Started successfully; authenticated health returned ready |
| Anonymous API memory access | Rejected with HTTP 401 |
| Background launcher | Started a hidden gateway and passed local generation readiness |
| Managed gateway shutdown and PowerShell syntax | Passed; test services stopped |
| Secret/data exclusions | `.env`, active data, prototype archive and virtual environment ignored by Git |

Automated coverage includes local-only base routing, isolated future external task text,
per-task approval, blocked cloud-backed Ollama models, context limits, summary failures,
partial-stream failures, keyed memory correction, deduplication, forgetting, backup,
transcript retention, workspace path restrictions, file-change invalidation, cancelled
approvals, replayed approvals and API authentication. Email coverage additionally includes
missing recipient, dictated address follow-ups, malformed model JSON, changed drafts,
expiry, cancellation, wrong-session approvals, revisions and duplicate-send prevention.

The user's own accent, room noise and full speaker/microphone interaction still need
real-world use; physical device capture and synthetic speech were verified separately.
Airwave could not deliver reliable capture in this environment; its driver/profile needs
attention before it can be selected. Gmail account setup is pending; no real email was sent.
The assistant supports registered workflows, not arbitrary control of every PC application.
Direct HTTP device and camera contracts were verified against a synthetic loopback server.
Actual light/CCTV endpoints, authenticated RTSP streams, proprietary device protocols and a
live SearXNG search service were not configured or verified. Project paths and routines are
left for the user to configure in Ctrl+D. Gmail inbox checks/replies used synthetic messages;
real account access remains pending. Presentation notes are generated from selected sources
and are not a guarantee that all presentation requirements are complete.
Semantic memory,
Odysseus deployment and delegated PC tools were not verified or implemented. External
workers have no real account credentials yet; their approval UI and adapters were tested
with simulated transport only, and no paid model request was made. Public online video
retrieval is blocked by Wikimedia's current HTTP 403 response; local video playback works.
Weight fine-tuning and image/video generation models are not installed. The user chose
local searchable knowledge first. Spoken stop/dismiss controls interrupt replies; arbitrary
new commands during playback and full acoustic echo cancellation are not implemented.
Interruption checks used synthetic microphone audio and muted native playback; actual
speaker-to-microphone echo and the user's live overlapping voice still need daily use.
Background wake restoration was checked with real cached ASR and synthetic audio; the
user's live wake accuracy still depends on voice, noise and microphone conditions. Login
startup has been registered and its hidden launch was verified manually; a full sign-out/
sign-in cycle was not performed. Explicit wakes now start a fresh local desktop session,
while non-wake follow-ups keep that session. Older chats and learned preferences remain.
The desktop screenshot verifies the Qt view; it does not establish accuracy for every local
model answer. The current foundation remains version 0.1.0.

Inspected environment: Python 3.11.9, Ollama 0.35.1, LiteLLM 1.104.0, PySide6 6.11.2,
NVIDIA RTX 3060 with 12 GB VRAM. Exact installed packages are recorded in `requirements.lock`.

