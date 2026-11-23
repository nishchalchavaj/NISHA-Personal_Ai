# NISHA

NISHA is an independent personal assistant running on your Windows PC. Her base model,
conversation context, selected memories, speech recognition and speech output run locally.
The active application does not import the archived prototype.

## Start on this PC

Security controls and verification are documented in [docs/security.md](docs/security.md):
allowlisted/content-checked local imports, bounded document processing, plain-text UI
rendering, restricted source URLs, local JSON API protections and private NTFS access.
NISHA has no payment gateway or payment webhook.

Local response learning and reviewed answers from other models are available through
**Ctrl+L → Response learning and teacher answers**. Rate an answer with **"good answer"**
or **"bad answer"**. See [reinforcement learning](docs/reinforcement-learning.md) for
the local policy, teacher review, preference-pair exports, pause and reset controls.
Reviewed chosen/rejected answer comparisons can also be used for a separate
[Llama preference fine-tuning workflow](docs/preference-finetuning.md) once enough
examples have been collected.
Casual conversation also learns from **"that sounded natural"** and **"you sound robotic"**.
Review teacher replies as conversation examples to guide tone locally on later turns.

Open PowerShell in `E:\NISHA`.

Terminal 1 starts the authenticated model gateway:

```powershell
.\.venv\Scripts\python.exe -m nisha gateway
```

Terminal 2 starts the desktop:

```powershell
.\.venv\Scripts\python.exe -m nisha desktop
```

Alternatively, run `start_nisha.bat` to start the gateway in the background and open the desktop.
Manual launches run on demand: closing/Alt+F4 exits NISHA and stops her microphone
and owned background workers. Editors and other user applications launched by NISHA
remain open. In explicitly selected background mode, closing hides the desktop in
the system tray and keeps wake listening running.
The first wake word from the background restores the window quietly, with voice interaction
still idle. Once it is visible, say **"Hey NISHA"** or **"NISHA"** again for attention, or
give a prefixed command such as **“NISHA, open YouTube.”** Follow-ups keep the current
conversation. Two minutes without conversation returns to wake-only idle while keeping
the window and context. Ctrl+N or /new explicitly starts a new conversation.
Ctrl+H hides the window; Ctrl+Q or the tray's **Quit NISHA** stops listening and exits.
The tray also provides mute and **Start with Windows**. Login startup defaults to disabled
and respects your tray-menu choice. When enabled, it starts NISHA hidden with a windowless Python process.
Running the launcher again reopens the existing resident instead of starting another listener.
To start hidden manually, run `.\scripts\start.ps1 -Background`.
Services started by an on-demand NISHA process stop with that process. An independently
started gateway stays available after NISHA quits. Stop it with
`.\scripts\stop_gateway.ps1`; a manually started gateway is stopped with Ctrl+C in its terminal.
The desktop retains the original transparent teal dashboard and large orb. Type a question
and press Enter, or say **"NISHA, ..."**. The desktop starts listening automatically.
Say **"Hey NISHA"** or **"NISHA"** on its own to wake her, then ask your question. Neesha,
Nishaa, Nisa and Meesha also work, with or without "Hey". Follow-ups keep listening until
two minutes of conversation inactivity, or until
you say **"quiet"**, **"just be quiet"**, **"close"**, **"bye"**, **"goodbye"**,
**"shut up"**, **"close your mouth"**, **"go to sleep"** or **"stop listening"**,
or mute manually. These whole phrases hide the window and return to wake listening;
"quite", "shutup" and "close you mouth" spellings also work. Commands such as
"close YouTube" are not dismissal phrases. The microphone icon /
Ctrl+Space toggles mute; a red slash means muted. A standalone wake receives the brief
local spoken acknowledgment **"Yes, Boss?"**. Calling NISHA gets her attention and keeps
the existing conversation. A hidden window's first wake only opens it; another wake in
the visible window gets her attention and receives the acknowledgment.
To reset conversation context, say **"start fresh"**, **"start a new conversation"**,
**"let's talk new"**, **"let's talk about a different topic"**, or
**"have some other conversation than this"**. These requests also interrupt a current
reply and start an empty conversation while keeping follow-up listening active.
Previous chats and learned preferences remain stored locally. An idle/hidden NISHA still
requires attention first. Once the window is visible, a combined command such as
**"Hey NISHA, start fresh"** both gets attention and resets the conversation.
Opening the desktop manually shows the window but leaves voice interaction idle until
you say a wake word. Unmuting an idle window also keeps it waiting for the wake word.
The personal detector corroborates wake speech without consuming short commands.
Capture continues during transcription
and accepts a new explicit wake or a close phrase while thinking; a wake interrupts generation and
queues its command in the active conversation after the current operation finishes. Already-dispatched
actions are not undone. During spoken replies, the microphone stays open for interruption
controls. Say **"stop"**, **"enough"**, **"that's enough"** or **"stop speaking"** without
a wake word to cancel speech and keep the conversation open. Quiet/close phrases stop
speech and hide NISHA; closing/Alt+F4, Ctrl+H and tray Hide also cancel the current reply.
**"Hey NISHA"** also interrupts a spoken reply and returns to conversation listening.
This mode accepts attention/stop/dismiss controls, using short rolling local-ASR windows and
recognized reply-echo filtering. Voice interruption has capture/inference latency;
full acoustic echo cancellation and arbitrary new commands during playback remain future work.
Audio is processed in RAM locally;
background speech without the wake word is discarded and never enters conversation history.
This PC uses the downloaded large-v3 speech model on the RTX 3060. It loads at startup;
wait for "Waiting for NISHA". Speech recognition still has endpoint and inference latency.
Press **Ctrl+R** or use **Personal voice samples** in the tray to record/import your
own reviewed speech samples locally and train a separate personal wake classifier.
See [personal voice enrollment](docs/personal-voice.md) for sample types and command
accuracy evaluation. The personal wake model was trained locally on your saved recordings;
add more takes and retrain to include further variations. Silent/noisy padding is trimmed
for training while the original WAVs remain unchanged. Whisper weight fine-tuning is a
separate later step.
Say **"minimize windows"**, **"show desktop"** or **"close windows"** to act on other
visible app windows. NISHA checks their actual state and reports any that stay open.
Closing uses normal Windows close requests, so unsaved documents can show a save prompt.
NISHA retains its own window and background listener.
F9 switches wall/table layouts; F10 switches
monitor/projector output. Ctrl+N starts a new conversation; Ctrl+Shift+S toggles spoken
replies to typed questions. Voice questions receive spoken replies.

For text only, with no audio dependency:

```powershell
.\.venv\Scripts\python.exe -m nisha chat
```

For push-to-talk in the terminal:

```powershell
.\.venv\Scripts\python.exe -m nisha voice
```

## Install or reproduce the environment

Install Python 3.11 or 3.12 and Ollama, then run:

```powershell
.\scripts\setup.ps1 -Desktop -Voice
```

For the smaller text-only environment, omit `-Desktop -Voice`. If Python is not on PATH:

```powershell
.\scripts\setup.ps1 -Python 'C:\Users\NISHCHAL CHAVAJ\AppData\Local\Programs\Python\Python311\python.exe' -Desktop -Voice
```

The setup script uses the tested dependency constraints, creates `.env` if missing and
generates local authentication keys without displaying them. It never overwrites existing
keys. `.env`, data, logs, archived files and virtual environments are excluded from Git.

The configured local models are already installed on this PC. On another PC:

```powershell
ollama pull llama3.2
ollama pull qwen3:14b
```

The accurate large-v3 speech weights are already installed under `data/models/speech-large-v3`.
`setup.ps1 -Voice` downloads them once on a new installation (about 3 GB). To retry:

```powershell
.\.venv\Scripts\python.exe scripts\setup_speech.py
```

Transcription never downloads weights or uploads audio. The current CUDA configuration
uses the CUDA 12.3 libraries already installed on this PC and CTranslate2's bundled cuDNN.
On a machine without compatible CUDA, change `voice.device` to `cpu` and `voice.compute_type`
to `int8`; large-v3 will be slower. Model residency and available GPU memory affect latency.

## Configuration

`config/nisha.yaml` is the source of truth. Restart the gateway after changing model profiles.
Its LiteLLM config is generated under `data/litellm.yaml`; do not edit that generated file.

| Setting | Purpose |
| --- | --- |
| `local_fast` | Default conversation model, currently `llama3.2` |
| `local_smart` | Optional heavier model, currently `qwen3:14b` |
| `context_window` | Model context allocation; input and output share this limit |
| `max_output` | Output reserve for context packing and single-call helpers; conversation/writing use bounded segments and can continue |
| `recent_exchanges` | Threshold for attempting a local rolling summary |
| `history_retention_days` | Expire inactive transcripts and task results after 30 days |
| `external_tasks_enabled` | `false`; legacy external gateway routing remains disabled |
| `online_visuals` | Public-topic image lookup; `false` keeps visuals local |
| `voice.microphone` | `null` follows the system default; an integer fixes one device |
| `voice.auto_microphone` | `false` uses the system default; `true` enables headset/USB/webcam priority selection |
| `voice.record_seconds` | Bounded push-to-talk recording length |
| `voice.continuous_listening` | Start desktop wake-word listening automatically |
| `voice.wake_word` | Local wake phrase, default `nisha` |
| `voice.wake_aliases` | Accepted NISHA name spellings |
| `voice.follow_up_seconds` | `120` gives two minutes of follow-up listening; the desktop also returns to idle after two minutes without conversation |
| `voice.silence_seconds` | Silence ending a spoken question; configured to 1 second |
| `voice.max_utterance_seconds` | Maximum duration of one spoken question; 30 seconds |
| `voice.use_speech_vad` | Local Silero speech detector filters non-speech noise |
| `voice.min_confidence` | Unclear recognition requires confirmation before an action |
| `contacts` | Local name-to-email mappings; addresses are never invented |
| `apps` | Additional installed app names mapped to existing executable paths |

Both model services must use loopback addresses. Cloud model names are rejected from local
profiles, and downloaded model metadata is checked before sending conversation text.
LiteLLM telemetry and remote model-cost downloads are disabled by the launcher.

To disable Ollama's own cloud features across your Ollama installation, set
`disable_ollama_cloud` to `true` in `%USERPROFILE%\.ollama\server.json` and restart Ollama.
This project has not changed your global Ollama configuration. See the
[official Ollama instructions](https://docs.ollama.com/faq#how-do-i-disable-ollama-cloud-features).

## Conversation and memory

In terminal chat:

```text
/remember name=Nishchal
/remember I prefer beginner-friendly engineering explanations.
/memories
/forget FULL_MEMORY_ID
/use local_smart
/new
/exit
```

The desktop accepts `/remember TEXT`, `/remember KEY=TEXT`, `/use local_smart`, and `/new` too. Use the CLI or API to
inspect and delete memories. A keyed correction updates the existing record. Selected
memories persist across restarts. Response preferences are now learned automatically from
direct feedback, separately from selected factual memories; every sentence is not treated as a permanent fact.
Response preferences include usual length, language, follow-up questions and tone.
An explicit "just tell me" request asks for one word when a one-word answer is accurate;
"explain in detail" expands the current answer. On Windows, `voice.voice_locale: en-IN`
selects an installed Indian English female OneCore voice when available.
Retrieval currently uses SQLite FTS5 keyword search, not semantic vector search. Muting and
local model changes and name/wake calls preserve the current conversation. Explicit
requests such as "start fresh" start a new one.
Manual launch or tray opening starts a fresh conversation and clears old displayed text.
Previous conversations remain stored locally.
`data/desktop-session.txt` records the current session. Use `/new` or Ctrl+N to reset it.
Resume a terminal session with:

```powershell
.\.venv\Scripts\python.exe -m nisha chat --session YOUR_SESSION_ID
```

Recent conversation, local summaries and relevant selected memories enter a bounded prompt.
Conservative UTF-8 byte accounting reserves output space; it may fit fewer words than an
exact model tokenizer. Failed summaries never delete source turns. Failed or interrupted
responses are not saved as complete exchanges. Inactive transcripts expire on startup;
selected memories remain until explicitly deleted.

## Learning your preferences and data

The hidden desktop now checks Ollama and the gateway in background and starts missing
local services without downloading models. It continues retrying after a slow Windows
login or service failure; wake capture does not wait for model service readiness.
Microphone failures restart the listener on the Windows default input while respecting
manual mute. Cold inference has a 180-second local timeout; retries happen before any
answer output, and writing can fall back to the downloaded local-fast model before
an artifact is saved. Partial broken streams are not silently replayed.
Failed/interrupted turns are recorded separately in `turn_outcomes`, and safe error-type
diagnostics go to `data/nisha.log`. `scripts/audit_conversations.py` produces a local
report of saved exchanges and action receipts. Browser launch receipts prove requests,
not successful page loading or subsequent clicks.


Say **"tell me short"**, **"now answer in short"**, **"just answer what I asked"** or
**"that was too long"**. NISHA saves a preference for brief, direct replies locally, across
new conversations and restarts. Ordinary replies request 2–3 short sentences and use a
small output budget. **"Explain this"**, **"tell me in detail"** and **"step by step"**
override brevity for that answer; the next ordinary answer returns to your saved preference.
**"Always answer in detail"** changes the default; a later short-answer correction changes
it back. Direct feedback can also teach simple wording, bullets/paragraphs and English,
Hindi or Hinglish response language. This is supported feedback recognition, not guaranteed
prediction of every unstated preference.

Use **"show my preferences"** or `/preferences` to inspect them, and **"reset my
preferences"** or `/reset-preferences` to clear them. **Ctrl+L** opens local learning:
select TXT, Markdown, CSV, JSON/JSONL, DOCX or text PDFs, or paste reference material.
Files must be under 20 MB; extracted text is limited to 500,000 characters and PDFs to
300 pages. Scanned PDFs need a text/OCR version. Imports extract text into local SQLite
FTS5 chunks, deduplicate identical contents, and retrieve matching excerpts for future
local-model answers. Keyword retrieval can miss paraphrases; semantic embeddings are
future work. Imported material remains reference data, never an action or preference instruction.

Terminal/desktop commands: `learn this: INFORMATION`, `/learn-file FULL_PATH`, `/knowledge`
and `/forget-source SOURCE_ID`. Ctrl+L also lets you forget sources. Local backups include
the preferences and knowledge index. Source excerpts persist until you remove them.

NISHA now also reviews conversations locally when you say bye, close/hide the window,
start fresh, or quit. A separate windowless worker reviews bounded batches without
blocking the dashboard or microphone. Pending reviews survive restarts and retry if the
local model is unavailable. Trusted user input is retained for review even if you interrupt
the reply; unclear/unconfirmed speech is excluded.

The review extracts your directly stated family/friend details, college and daily-life
events, lasting preferences, and explicit corrections you give NISHA. Memories contain
your exact words, their date and local source evidence. Events stay dated, changed details
update their matching slots, and disagreements are recorded as your account. The local
model uses relevant memories and preferences in future conversations. It does not assume
someone is an enemy or that you feel a particular emotion based on silence.

Say **"show what you learned"** or `/learning` to inspect conversation learning;
**"show my personal profile"** includes learned details and life events. **"Forget my
personal details"** clears those details/events; **"forget conversation learning"** clears
all reviewed conversation memories and cancels pending reviews. Individual memories can
also be deleted with `/forget ID` in the terminal or the local API. Deletions invalidate
in-flight learning so an old review cannot recreate a removed memory. Newly shared
details can be learned in later conversations. "Don't remember ..." messages, credentials,
quoted examples, writing prompts, and external-model output are excluded from automatic
personal learning. Existing explicit memories and response-preference reset commands remain.

This is **local searchable knowledge and conversation learning**, not base-model weight
retraining. NISHA does not learn its own guesses as facts or upload chats for training.

## Quick offline utilities

NISHA also has small deterministic utilities that run on this PC without the language model
or a network request. Try **“calculate 12 * 3”**, **“convert 5 km to miles”**,
**“convert 1010 from binary to decimal”**, **“roll a die”**,
**“pick a random number between 1 and 20”**, or **“rock paper scissors rock.”**
Say **“create a QR code for https://example.org”** to save a local SVG image under
`data/workspace`. Say **“I’m bored”** for a few quick activity choices, or
**“show local utilities”** to see examples. Calculations use a restricted arithmetic
parser; they never run Python or shell code. Unit conversion is offline and does not
include live currency rates.

## Optional approved external tasks

External task execution is disabled while `external_tasks_enabled: false` in
`config/nisha.yaml`. Both the task dialog and worker enforce this switch before
reading provider credentials or sending a request. Enable it explicitly to use
individually approved tasks; base conversation and personal memory stay local.

**Ctrl+K** connects an optional OpenAI, Gemini or Claude task provider. Enter an API model
name available to your provider account and its API key in the masked local dialog. The
key is kept in Windows Credential Manager. No provider key is configured on this PC yet.

**Ctrl+T**, `/task` or **"external task"** opens a standalone task. Write the exact text,
review it, then choose **Approve and run**. Approval is bound to the provider, model, task
and learning choice, expires after five minutes, and is used once. Only that task text is
sent; local conversation, preferences, files and memories are not automatically attached.
No automatic retries or provider fallback occur. Model/account limitations and API charges
are controlled by the provider.

The result returns to the local conversation and local task log. If **Save the answer for
local learning review** is selected, it enters a review queue. Accept it in **Ctrl+L →
Response learning and teacher answers** to add it to the local index as unverified external
model output; it never changes response preferences or grants tool permissions.
The local base model remains the source of ordinary conversation. Provider-side retention
still depends on that provider/account. OpenAI requests use `store: false` as described in
the [official OpenAI documentation](https://developers.openai.com/api/docs/guides/migrate-to-responses);
that does not guarantee elimination of all provider-side logs. See
[OpenAI data controls](https://developers.openai.com/api/docs/guides/your-data).

## Floating visual references

Questions such as **"who is Nikola Tesla?"**, **"tell me about Paris"** or **"show me
images of Saturn"** can display related visuals in a movable glass-style card at the
left-middle of the screen. The original dashboard and orb remain intact. Browse results,
view their sources, drag the card or say **"hide visuals"**. Public-topic terms are sent
to a public image service; personal-reference queries and queries with local knowledge
matches stay local. This filter is conservative, not a general private-data classifier.
Set `online_visuals: false` to disable public lookup.

Images prefer Wikipedia/Wikimedia, with Openverse as a separate public image fallback.
Wikimedia rejects this PC's current network requests; Openverse lookup and thumbnail
display were verified. Captions show the creator/license where supplied. Related image
results are not guaranteed identity matches. Online lookup is asynchronous and never
blocks the local answer. Online video discovery uses Wikimedia Commons and is unavailable
on this network while that service rejects requests.

**Ctrl+I** selects an image or local video; `/show FULL_PATH` displays a specific local
asset. Files under `data/generated`, `data/workspace` or `data/media` with names matching
the topic are preferred over online search. Existing generated images/videos can be
displayed this way; an image/video generation model is not installed in this milestone.
Video playback starts manually and is muted so it doesn't interfere with listening.

## Websites, desktop writing and code

Say "NISHA, open YouTube" or type "open YouTube" to launch the actual site in your default
browser. Google, GitHub, Gmail and Wikipedia also work. Say **"open example dot org"** for a
custom address. An unfamiliar site name opens search results so NISHA does not guess its
domain. "Open it" uses the most recent unambiguous website or generated file. A browser
receipt confirms a launch request, not that the page finished loading.

- **"Write about solar power in Notepad"** saves actual text and opens it in Notepad.
- **"Write a study plan in Word"** creates a `.docx` and opens Microsoft Word.
- **"Write Python code to add two numbers"** saves source and opens VS Code. Other supported
  languages include JavaScript, TypeScript, HTML, CSS, Java, C++, C#, SQL, PowerShell, Bash,
  Rust and Go. Generated code is saved for review, never executed automatically.
- **"Make it shorter"** uses the conversation to revise the previous document, code or
  pending email. Revisions create new files so the originals remain available.
- **"Open Notepad"**, **"open Word"**, **"open VS Code"**, **"open calculator"** and
  **"open Paint"** launch installed apps. NISHA also checks exact desktop and Start-menu
  shortcut names; add missing executable paths under `apps` in the config.

For general PC control, say **"list installed apps"**, **"list shortcuts"**, **"show open
windows"**, or **"show controls in Chrome"**. You can then say **"click Search in Chrome"**,
**"right-click a file in Explorer"**, **"double-click a named control"**, or
**"drag Report to Archive folder in Explorer"**,
**"type cats into Search in Chrome"**, **"press Ctrl+F in Chrome"**, **"scroll down in
Chrome"**, or **"switch to Chrome"**. Name a more specific window title if several match.
After opening an app or website, short follow-ups such as **"click Search"** or
**"scroll down"** use that current window. After **"open My PC"**, **"open Local Disk C"**
opens C: in Explorer; later folder names resolve inside the current folder. Opening an
explicitly named app or website switches the context to it.
These commands use Windows accessibility controls in the currently open app. NISHA reports
when an app hides a control or the effect cannot be verified. General UI control does not
send messages, buy, publish, subscribe, delete, or submit forms; use a reviewed workflow.
**"Open Chrome"** now checks whether Chrome is the foreground window before claiming it is.
**"Open Spotify and play song"** looks for Spotify's accessible Play button and checks
whether it changes to Pause; this verifies the app control state, not audible output.
Current weather questions query Open-Meteo and include the place and model time.
The default place is Nargund, Karnataka; a named place overrides it. If the live service
fails, NISHA says so instead of giving a remembered forecast. A weather query sends the
place name to Open-Meteo.

Artifacts live under `data/workspace`. Writing uses the local smart model and can take
longer than short conversation replies. Some apps and websites do not expose their controls
to Windows accessibility; multi-step task planning across every app remains future work.

## Devices, projects and saved routines

Press **Ctrl+D** or say **“setup devices”** to configure direct HTTP lights/switches,
camera snapshots/streams, project folders, requirements/budget and saved routines.
You can configure them later; no example endpoints are activated automatically.
Say **“open my project folder”**, **“do the usual setup”**, **“turn on lights”**,
**“what's the status of the devices?”**, or **“show me CCTV camera visuals”** once set up.
Camera snapshots refresh in the existing left-middle glass panel, with no recording.
Device status reports actual responses and last-seen ages; commands do not claim success
without an adapter response. Direct HTTP and camera adapters require your device's API;
proprietary protocols and MQTT are not integrated yet.

**“Prepare everything for tomorrow's presentation”** uses the explicitly selected deck
and supporting files, saves a new local bundle with notes/checklist, and requests their
native opening. **“Find the best option for this project”** opens the configured public
research query, or uses a configured SearXNG JSON endpoint for a comparison with sources
generated locally. Detailed setup and limits: [Connections guide](docs/connections.md).

## Gmail drafts and approved sending

Press **Ctrl+G** or say/type **"setup gmail"**. Enter your Gmail address and a
[Google app password](https://support.google.com/accounts/answer/185833) in that local
dialog. Google requires 2-Step Verification for app passwords, and some accounts do not
offer them. The app password is kept in Windows Credential Manager, never in chat or `.env`.

Say **"Write an email to alex at gmail dot com about tomorrow's meeting"**. The local
model writes a draft; no email is sent. For names, add exact addresses to `contacts` in
`config/nisha.yaml`. If an address is missing, supply it in a follow-up such as
**"send it to alex at gmail dot com"**; this updates the draft and requires fresh approval.

Say **"review email"** or **"send it"**, click **Review email**, or press **Ctrl+E** to see
the exact recipient, subject and body. **Approve and send** submits that specific draft
through Gmail. In terminal/API chat, use `approve email CODE` shown with the draft.
Approvals expire after 30 minutes, cannot be replayed, and are invalidated by a revision,
file change or cancellation. Say **"cancel email"** to discard the pending approval.
Account connection is still needed on this PC; verification used a simulated mail transport
and sent no real email.

**“Check Gmail” → “select email one” → “reply to him saying …”** drafts a contextual
reply to a specific selected message. Inbox access is read-only; threading and content
are bound to the exact draft approval. Ctrl+E still reviews before sending. See the
[Gmail context guide](docs/connections.md#gmail-context-and-replies) for bounds and privacy.

## Approved file tools

Only `data/workspace` is accessible to the active file tools. Terminal commands are:

```text
/files
/read note.txt
/delete note.txt
```

Deletion previews the exact file and requires `yes`; the one-use approval expires after
two minutes and is invalidated if the file changes. Files go to the recycle bin. Arbitrary
Python execution, administrator commands and force-closing applications
from the old prototype are not registered in the active application. The language model
does not yet invoke tools automatically.
Project preparation separately reads only files explicitly configured within your
chosen project folder, and copies them into a new workspace bundle.

## Local API

```powershell
.\.venv\Scripts\python.exe -m nisha api
```

The API binds to `127.0.0.1:8765` and requires `Authorization: Bearer <NISHA_API_KEY>` from
your `.env`. Gateway and Core use different authentication keys.

| Endpoint | Behavior |
| --- | --- |
| `GET /health` | Component readiness |
| `POST /sessions` | Create a local conversation |
| `POST /chat` | `{ "session_id": "...", "text": "Hello", "model": "local_fast" }` |
| `GET /memories` | List selected memories |
| `POST /memories` | `{ "text": "...", "key": "optional-name" }` |
| `DELETE /memories/{id}` | Forget a selected memory |
| `GET /tools` | Discover the registered workspace tools and their confirmation requirements |
| `POST /computer/screen` | Capture and analyze the current screen with the configured local vision model; optional JSON `{ "question": "..." }` |
| `POST /tools/propose` | `{ "action": "read_file", "path": "note.txt" }` |
| `POST /tools/confirm` | `{ "approval_id": "...", "approved": true }` |
| `GET /projects` | List configured project folders |
| `POST /coding/inspect` | List/search/read source in a configured project; private filenames and credential values are filtered |
| `POST /coding/propose` | Generate a local unified-diff candidate for explicitly selected source files; proposal is saved for review and never applied |
| `POST /coding/verify` | Run the fixed `pytest` or `ruff` suite and return a structured command receipt |

The desktop voice/text client also supports **"inspect project NAME"**, **"search project NAME for PATTERN"**, **"run the tests"** (the configured default project), and **"run the tests in NAME"**. Project roots are configured in Ctrl+D. Coding proposals are generated with the local model and stored under `data/coding_candidates`; applying them is deferred to the isolated Git candidate phase. Verification runs the selected project's test code under the current Windows account, with a five-minute timeout and filtered environment; it is not an operating-system sandbox. Command receipts are written to `data/reports/coding-commands.jsonl`.

## Checks, backups and troubleshooting

```powershell
.\.venv\Scripts\python.exe -m nisha doctor
.\.venv\Scripts\python.exe -m nisha doctor --generate
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m ruff check nisha tests scripts
.\.venv\Scripts\python.exe scripts\verify_local.py
.\.venv\Scripts\python.exe scripts\verify_local.py --model local_smart
.\.venv\Scripts\python.exe scripts\verify_desktop.py
.\.venv\Scripts\python.exe scripts\verify_voice.py
.\.venv\Scripts\python.exe scripts\verify_listening.py
.\.venv\Scripts\python.exe scripts\verify_speech_accuracy.py
.\.venv\Scripts\python.exe scripts\verify_microphones.py
.\.venv\Scripts\python.exe scripts\verify_wake_phrases.py
.\.venv\Scripts\python.exe scripts\verify_workflows.py
.\.venv\Scripts\python.exe scripts\verify_learning.py
.\.venv\Scripts\python.exe scripts\verify_learning_ui.py
.\.venv\Scripts\python.exe scripts\verify_visuals.py
.\.venv\Scripts\python.exe -m nisha backup
```

The smoke checks use temporary synthetic data. The desktop check renders offscreen; the
voice check synthesizes audio files without recording your microphone or playing sound.
The microphone check briefly monitors real inputs without saving or transcribing audio.
The workflow check uses real local generation with simulated editor/mail adapters.
`scripts\verify_editor_actions.py --launch` explicitly opens real Notepad, Word and VS Code
with fresh synthetic files under `data/editor-verification`.

For the complete grouped smoke checks, run `scripts\verify_all.py --group ui`, then
`--group voice`, then `--group models`. Run `--group editors` to include real editor
launches, followed by native minimize/close checks on those synthetic editor windows.
Each group saves JSON results and individual logs under
`data/reports/full-check-YYYY-MM-DD`; retries preserve earlier failures. The voice
group also checks deliberately saved personal recordings without modifying them.
Stop the resident with `python -m nisha desktop --quit` before the voice group to
avoid loading two speech models, and restore it with `scripts\start.ps1 -Background`
afterward. Email and YouTube account mutations use simulated transports; device
checks use a local test server. They do not verify unconfigured physical devices
or send real email. The dedicated conversation-review check runs the real local
background learner; other temporary fixtures suppress asynchronous review so their
databases are not removed while a worker is still using them.

Backups use SQLite's consistent backup API. To restore, stop all Core clients, preserve the
current database and its sidecar files, then place the backup at `data/nisha.sqlite3`.

- **Gateway unavailable:** start `nisha gateway` and check its terminal output or
  `data/gateway-out.log` / `data/gateway-err.log` when using the batch launcher.
- **HTTP 401:** ensure `.env` keys match the running services; restart after changing keys.
- **Model missing:** run `ollama list`, pull the exact configured model and rerun doctor.
- **Slow smart model:** use `local_fast`; Qwen's VRAM, context and other GPU use compete.
- **Microphone selection:** NISHA now follows the Windows default input, including default
  endpoint changes checked every three seconds. Priority selection is optional through
  `voice.auto_microphone: true`: Airwave headset first, USB microphone second, webcam third,
  then other inputs. Usable speech and signal quality can override priority. An unclear
  transcript temporarily penalizes its input. Inputs are checked in the background.
  On this PC, Airwave capture stalls; its isolated worker is stopped during pause and the
  working USB input is used. A working headset capture path is needed before it can win.
- **Whisper model missing:** use the one-time download command above; live STT stays offline.
- **Wake word not heard:** wait until the mic is unmuted, then say "NISHA, ..." in one sentence.
  Wake detection uses local Whisper after an utterance ends, so it has transcription latency.
  Speak after the startup model load completes; restart after configuration changes.
  Unclear speech prompts a repeat or **"confirm command"** before performing an action.
- **Closing during a request:** the window hides and returns to wake-only background listening.
  Explicit **Quit NISHA** stops capture and waits for bounded operations before exiting.
  Wakes during thinking preserve the chat. Say **"start fresh"** to reset it.
  **"Stop"** or **"enough"** interrupts spoken
  output and keeps the chat open; closing/hiding cancels playback and keeps wake listening.
  Speech interruption uses local ASR; full acoustic echo cancellation remains pending.

## Engineering status

This is the first working foundation, not the completed long-term ecosystem. See
`docs/architecture.md` for decisions, `docs/migration.md` for preserved prototype assets,
and `docs/roadmap.md` for remaining milestones. Odysseus, autonomous full-page research,
semantic retrieval, weight fine-tuning, media generation and autonomous tool planning
are not enabled yet. Gentle idle conversation is implemented; scheduled proactive
notifications remain a future feature. Local knowledge, preference learning and
approved external-task adapters are implemented.
Configured project/routine actions, direct HTTP devices, camera viewing, Gmail reply
context and SearXNG snippet comparisons are also implemented. Physical devices and a
real Gmail account still require your local setup.



## Current browser, installed apps and personal conversation

- Say **"open YouTube and search Dr Bro"** or **"search Dr Bro on YouTube"**.
  Searches use YouTube's results URL in the existing default browser session.
- Say **"open YouTube and search Dr Bro and subscribe"**. NISHA opens a channel
  search and attempts exact-name channel navigation using Windows accessibility.
  If the match is ambiguous, choose the intended channel in the results first.
  **"subscribe"** and **"like this video"** prepare a review of the current page.
  Approve with **"approve YouTube action"** or the glass panel's review button.
  Approval expires after three minutes, is consumed once, and is cancelled by a
  new conversation. The helper rechecks the page and verifies the changed control.
  Keep one YouTube tab visible in Edge or Chrome. Sign-in, browser language or
  inaccessible controls can prevent automation; failures never count as success.
  This adapter still needs live validation in your signed-in session.
- Windows Start-menu discovery now includes packaged applications such as Claude.
  **"open Claude"**, **"is Claude installed"**, **"list installed apps"** and
  **"refresh installed apps"** use the local inventory. Launching an app does not
  grant arbitrary control of that app or approve sending tasks to cloud models.
  **"show app capabilities"** lists the currently supported adapters.
- Requested information, drafts, code and visuals use a scrollable glass results
  window on the left. Everyday conversation stays below the orb. Opening results
  keeps the original orb and title in their existing positions. The orb is teal
  when listening, speaking or idle, and dark blue while thinking.
  Click the small chat icon beside the microphone, or press **Ctrl+J**, to show
  the floating glass conversation window on the right. Your messages appear on
  the right and NISHA's on the left, with live replies and scrollable session
  history. Requested information and drafts stay in the left results panel.
  Only the orb and its title move to the center while chat is open, then return
  to their original positions when chat closes. Closing chat keeps listening
  and the current conversation active; a new conversation clears its chat view.
  Manual opening waits for attention with NISHA or Hey NISHA; hiding the window
  returns to wake-word listening. Images are described by the
  local **Moondream** model and narrated
  once while the panel advances automatically. Ask **"what do you see in the front camera?"**
  to analyze one fresh snapshot from a configured camera using local Moondream. Camera
  analysis is on demand; it does not continuously watch or record. Videos play muted and
  one sampled frame can be described; this is not a full video analysis. Local vision can
  make mistakes and never establishes a person's identity. Image bytes stay on this PC.
  **"stop"**, **"enough"**, panel dismissal and hiding NISHA cancel narration.
  Press **Ctrl+Shift+G** to open the hand drawing studio. Start the camera,
  pinch thumb and index finger to draw, or switch to **3D shape creator** and move your
  hand to rotate a cube, sphere, torus or pyramid. Save a PNG only when you choose
  **Save PNG**.
  Check **Show body pose keypoints** for a live body skeleton, or **Show face outlines
  and count** for local face detection. **Control mouse** enables index-finger pointer
  movement and pinch clicks; leave it unchecked to draw. Hand and body tracking run
  locally; closing the studio stops the camera. Camera feature dependencies are
  included in desktop setup:
  `powershell -ExecutionPolicy Bypass -File scripts/setup.ps1 -Desktop`.
- Direct statements such as **"my favorite color is green"**, **"I enjoy robotics"**,
  **"I live in Pune"** and **"call me Boss"** become local, correctable personal
  details. Quotations, imported knowledge, secrets and uncertain voice transcripts
  do not become profile facts. Use **"show my personal profile"**, the local memory
  review in Ctrl+L, or **"forget my personal details"** to inspect or clear them.
- After five minutes in idle with the window visible, NISHA can ask a brief, varied
  question such as **"Hey Boss, what's up?"** or **"Need a hand with anything?"**.
  One more invitation can follow after another ten minutes, then she waits quietly.
  You have 30 seconds after a check-in to reply without a wake word. The local model
  receives the check-in as temporary context for that reply; it isn't saved as a fake
  user exchange or learned personal fact. It stays quiet while muted, hidden, busy,
  or awaiting approval. **"don't disturb"** works while visible and idle, cancels
  speech, disables check-ins across restarts and receives **"I'll be here. Talk to me
  when you're free."** Say **"NISHA, you can talk now"** to re-enable check-ins.
  Set `idle_checkins: false` to disable them, or change `idle_checkin_seconds` (default 300).

Short greetings now work while the local model is starting. Explicit app/document
commands run in an ordered background queue so you can keep talking; completed
results appear without speaking over the current reply. Say **cancel background
tasks** to cancel queued work. See [response timing and background work](docs/responsiveness.md)
for cancellation behavior, approval boundaries and shared-GPU limits.
