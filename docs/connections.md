# Devices, cameras, projects and saved routines

Open **Ctrl+D**, or say/type **“setup devices”**, **“setup project”** or
**“setup routines”**. Nothing is connected until you save your actual settings.
The original dashboard remains in place; configuration opens in a separate dialog.

## Project setup

The Project tab provides a folder chooser, project name, requirements, budget, public
research query, presentation chooser and supporting file paths. Supporting files are
relative to the selected project folder, one per line. Set the presentation explicitly;
NISHA does not guess which of several decks is due tomorrow.

- **“Open my project folder”** asks Explorer to open your configured default folder.
  A named project/alias can select another configured folder.
- **“Prepare everything for tomorrow’s presentation”** reads the selected deck and
  supporting documents locally, generates notes/checklist with the local smart model,
  and creates a new `data/workspace/presentation-ready-*` bundle. Files are copied,
  originals remain in place, and missing/unreadable files are reported. Explorer and
  the default presentation app receive open requests. This does not establish that
  every presentation requirement has been satisfied.
- **“Find the best option for this project”** uses the configured requirements and
  budget. Only the configured **public research query** leaves this PC. With no search
  endpoint, NISHA opens that query in the browser. To get a comparison inside NISHA,
  configure a [SearXNG JSON search endpoint](https://docs.searxng.org/dev/search_api.html),
  such as `http://127.0.0.1:8888/search`, with JSON results enabled. Search snippets and
  source URLs go to the local model; private requirements and files are not sent to the
  search service. Comparisons are preliminary snippet-based research and flag unknown
  prices or evidence. No external language model is called automatically.

Presentation reading supports PPTX slides/notes, TXT/MD/CSV, DOCX paragraphs/tables
and text PDFs. XLSX files can be copied/opened but are reported as lacking a text reader.
Bounds apply to file size, source count and extracted text. Macros and code are not executed.

## Direct devices and cameras

The **Advanced JSON** tab edits the local configuration and provides a read-only,
copyable example. Example addresses are placeholders, not discovered devices. Use your
device’s documented API; brands expose different URLs, methods, request bodies and state
formats. Direct adapters support HTTP(S) GET/POST/PUT with optional JSON bodies and
none/basic/digest/bearer authentication. Status and snapshot checks are GET only.
MQTT, Zigbee, Bluetooth control and proprietary vendor/cloud APIs do not yet have adapters.

For example, a light entry contains:

```json
{
  "id": "desk_light",
  "name": "Desk light",
  "kind": "light",
  "aliases": ["desk lamp"],
  "status": {"url": "http://192.168.1.50/status"},
  "state_key": "state",
  "on_state": "on",
  "off_state": "off",
  "on": {"url": "http://192.168.1.50/power", "method": "POST", "body": {"state": "on"}},
  "off": {"url": "http://192.168.1.50/power", "method": "POST", "body": {"state": "off"}},
  "auth": "none"
}
```

`state_key` may use dot notation, such as `power.state`. Configure `on_state`/`off_state`
to match the device’s real response. Commands may target a name, alias, ID, or **“all lights”**.
NISHA reports a verified on/off state only when the GET status response agrees; otherwise
it reports acceptance without claiming the state changed. Failed commands are not retried.
Redirects are not followed. Credentials belong in the masked **Credentials** tab and are
kept in Windows Credential Manager; do not embed them in URLs or configuration JSON.

- **“Turn on lights”**, **“turn Desk light off”** control registered light/switch adapters.
- **“What’s the status of the devices?”** performs current checks and reports last successful
  response ages. Background checks run every 30 seconds off the UI thread. A stream without
  a health/snapshot endpoint is marked untested rather than online. Successful HTTP responses
  establish reachability, not complete physical health. Persisted status is rechecked after restart.
- **“Show me CCTV camera visuals”** or **“show Front camera”** opens the right-middle glass
  panel. Configure a camera `stream` RTSP/RTSPS/HTTP(S) URL or a `snapshot` GET request.
  Snapshots take priority when both are provided; omit the snapshot to use the stream.
  Snapshots refresh every five seconds in memory; failures clear the old frame, and later
  refreshes recover. No frames are recorded to disk. Multiple cameras can be cycled through.
  Stream audio stays muted. Closing the card stops playback/refresh. Basic/digest credentials
  are resolved only when opening a stream; bearer-authenticated cameras need snapshots.

Stream playback uses [Qt Multimedia/FFmpeg](https://doc.qt.io/qt-6/qtmultimedia-index.html),
so compatibility depends on the actual camera’s stream format and authentication.
Physical RTSP cameras and authenticated camera streams have not been verified on this PC.
The screenshot in `data/desktop-camera-preview.png` uses a synthetic local HTTP camera.

## Saved routines

Open **Ctrl+D → Routines** to create a named routine. Enter an optional exact command,
such as **“Get ready for College studies”**. Each **Step** tab contains one activity and
target. Add, remove, or reorder steps, then save. The same command can be said or typed
later to run the saved activities in order. Existing “do/start/run NAME” commands still work.
Supported steps are `open_folder`, `open_file`, `open_app`, `open_website`,
`open_chrome_url`, `search_chrome`, `device_on` and `device_off`.
Use `open_path` to open any saved absolute local path, including a folder, document,
shortcut or program. Pasted paths wrapped in double quotes are accepted.
Chrome URL steps can use a saved YouTube video link or any other HTTP(S) page;
search steps open results for the exact saved query. Opening a page does not verify
that a video is playing or that search results are relevant.
File/folder paths must be absolute; device steps refer to a configured ID. Document
opening excludes executable files. App steps use installed/configured app adapters.

```json
{
  "name": "Usual setup",
  "trigger": "Get ready for College studies",
  "steps": [
    {"action": "open_folder", "target": "E:\\YOUR_PROJECT"},
    {"action": "open_app", "target": "notepad"},
    {"action": "device_on", "target": "desk_light"}
  ]
}
```

Say **“do the usual setup”** to run these exact steps. Each action reports its own result;
an unconfirmed/failed action stops remaining steps. The model cannot insert new commands.
Say **“plan Usual setup”** to preview the ordered steps and **“run Usual setup”** to
execute them. Plans are built from the saved routine and include concise action descriptions;
they do not ask a language model to invent commands. Completion reports distinguish a request
accepted by Windows from a state confirmed by a device. Run
`python scripts/evaluate_task_automation.py` for the offline planning check; it uses
synthetic examples and does not open apps, contact devices, or use the network.
**“Show routines”** lists saved routines. After performing supported actions in the same
conversation, say **“remember this as NAME”** to save the last actual action, or
**“remember these actions as NAME”** to save the most recent supported actions (maximum 12).
The saved steps are printed for review and can be edited in Ctrl+D. Existing routines
are not silently overwritten. Steps are learned from actual folder/app/browser/device
receipts, not guessed from conversation text. Arbitrary autonomous app planning remains future work.

## Gmail context and replies

Connect your account with Ctrl+G, then:

1. **“Check Gmail”** lists the five most recent inbox messages.
2. **“Select email one”** or **“read email 1”** selects a message and displays its plain text.
3. **“Reply to him saying …”** drafts a reply with the local model using that selected message,
   explicit preferences and locally supplied writing examples. NISHA does not claim to have
   learned your entire historical email style without examples.
4. Press **Ctrl+E**, or say **“send it”**, to review the exact recipient, subject and body.
   **Approve and send** submits that exact draft. Ordinary “yes” does not send it.

Inbox access uses [Gmail IMAP over SSL](https://developers.google.com/workspace/gmail/imap/imap-smtp),
read-only selection and BODY.PEEK: it does not mark messages read, download/open attachments
or load remote HTML images. Headers/plain text are bounded to 100KB per fetched message;
large messages may be incomplete. Inbox lists/selection are session-scoped in memory;
displayed messages and drafts also enter local conversation/storage under the existing
retention policy. Refreshing the list clears selection; selections expire after 30 minutes.
Ambiguous/missing reply addresses and a different explicitly named recipient require clarification.
Reply threading headers are bound to the one-use draft approval along with recipient/content.
Account permissions/app-password eligibility still depend on Google; no real inbox or email
delivery has been tested without your account setup.

## Verification

`python scripts/verify_connections.py` runs a synthetic loopback HTTP light/camera and checks
actual request/state handling, config save, refresh failure/recovery, responsive Qt and the
original dashboard. `python scripts/verify_project_model.py` checks real local-model notes and
reply generation with synthetic project/email data and simulated launch/mail adapters.
Neither test connects to real IoT devices or sends email. Automated coverage checks status
ages, credential separation, limits, invalid configuration, routine scope/failures, project
path bounds, research payload privacy and exact reply approval.
Configuration/routines live in `data/connections.json` and response timestamps in
`data/device-status.json`; include those files when backing up your setup. SQLite-only
backups do not include these files or Windows Credential Manager credentials.
