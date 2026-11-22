# Working milestones

The revised priority is a local-only base assistant for one user. External models may
perform self-contained approved tasks; they never become NISHA's base memory.

| Stage | Deliverable | State |
| --- | --- | --- |
| Local efficiency and quality loop | Keep privacy-preserving local traces and measure answer quality, latency and resource cost before changing routing or memory behavior | Planned from OpenJarvis review; local-only, opt-in, no automatic model training |
| Foundation | Independent core, LiteLLM, Ollama, configuration, health checks | Implemented |
| Local conversation | Streaming, bounded context, durable selected memories | Implemented |
| Permission boundary | Restricted file tools and one-use approvals | Implemented |
| Desktop | Original transparent wall/table dashboard, teal orb, typed chat and local model commands | Implemented |
| Voice | Local large-v3 STT, Silero VAD, TTS, continuous wake variants and manual mute | Implemented; synthetic recognition and physical fallback verified |
| Microphone selection | Windows system default, endpoint changes and driver isolation; optional priority mode | Implemented; system-default capture verified, priority mode disabled by user preference |
| Browser actions | Registered and dictated custom sites with truthful outcomes and follow-ups | Implemented; unfamiliar names open search results |
| Memory upgrades | Semantic retrieval, reviewed episodic/procedural extraction, old-data migration | Pending |
| Preference learning | Persistent short/detail, language, wording and format feedback, reset/review | Implemented; real local-model behavior and restart persistence verified |
| Local knowledge | User file/text imports, source tracking, bounded keyword retrieval and forgetting | Implemented; no model weight training |
| Visual references | Movable glass media card, public images, local/generated assets, muted video and on-demand local camera snapshot questions | Implemented; camera questions use one snapshot with no recording; Openverse works, Wikimedia requests rejected on this network |
| Odysseus | Authenticated adapter against a pinned local deployment | Pending; no deployment installed |
| Desktop writing | Real Notepad text, Word documents, source files and configured app launching | Implemented |
| Window control | Native close/minimize with observed results and normal save prompts | Implemented; actual cross-process requests verified on disposable windows |
| Gmail | Read-only inbox/selected reply context, local drafts, exact review, one-use approval and credential-protected sending | Implemented; real account/delivery not tested |
| Useful workflows | Configured project folder, presentation bundle/notes, saved exact routines and SearXNG snippet comparisons | Implemented; real local notes and simulated action integrations verified |
| Autonomous planning | Dynamic app planning, project-resume summaries and full-page research | Pending; saved-routine plans, concise tool instructions and an offline plan evaluator implemented |
| Voice interaction | Separate wake/command confidence, bounded isolated ASR, follow-ups, stop/dismiss during output and listener shutdown | Implemented; personal wake model activated, rolling stop → local ASR → native playback cancellation verified; live overlapping voice/full acoustic echo cancellation remain pending |
| Background resident | Close-to-tray listening, wake restores fresh chat, wake while thinking, single instance and Windows login startup | Implemented; cached ASR/Qt pipeline and native launcher verified |
| Proactivity | Local events, importance, quiet hours, interruption preferences | Pending |
| External task workers | OpenAI/Gemini/Claude standalone approvals, local result learning | Implemented; fake transport tested, user API credentials still needed |
| Model training | Local voice recordings, personal wake training and command evaluation | Personal wake classifier trained with 71 user recordings, originals retained and further variations supported; Whisper weight fine-tuning remains pending |
| Media generation | Local image/video generation adapters | Pending; existing generated assets can be displayed |
| Direct IoT/cameras | HTTP devices/status, HTTP snapshots and RTSP stream panel | Implemented; local HTTP simulator verified, physical endpoints/streams need setup |
| Other devices | MQTT, proprietary IoT, phones, glasses and robotics | Future |

For each pending stage, write one observable acceptance scenario, implement the smallest
working integration and verify failure/recovery before advancing. For Odysseus, first
demonstrate one authenticated local capability and then prove approval and privacy boundaries.
Do not move all of NISHA's state into Odysseus or maintain two competing sources of memory.

