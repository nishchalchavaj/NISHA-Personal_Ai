# NISHA application security review

Reviewed on 23 October 2026. This review covers the active `nisha/` application, its API, import and rendering paths, configuration/setup, and the archived orb WebView. It does not connect the archived prototype to the active application.

## Actual architecture and payment findings

NISHA is a Windows Qt application with a bearer-authenticated JSON API bound to loopback. It has local file selection/import rather than an HTTP upload endpoint. No payment SDK, gateway configuration, checkout, payment webhook, order or entitlement implementation was found in the active code, project dependencies/configuration, or the archived application. Provider-task billing is controlled by the external provider and is not a NISHA payment integration.

Therefore no webhook signature/status/amount/currency verification code was added. Adding a pretend webhook verifier would create a misleading security boundary. Tests verify that forged payment-success requests to common payment/webhook paths receive 404 and invoke no model/action. A future real payment integration needs provider-specific verification of the original body, server-side order reconciliation and durable idempotency before any paid access exists.

## Implemented fixes

### File import and storage

- Added shared allowlists and a bounded file reader. Checks happen before filesystem lookup for UNC/network paths, alternate data streams, misleading filename controls and unsupported extensions. Symlinks and non-files are rejected. A single byte snapshot is used for validation and subsequent document parsing.
- Renamed PE/ELF/Mach-O executables are rejected by content signature. Text must be valid UTF-8 without binary control characters; executable shebang scripts are rejected. JSON and JSONL must parse as their declared formats. Ordinary reference text containing HTML or code remains text, preserving legitimate learning workflows.
- Documents are limited to 20 MB. Office packages are checked for type-specific main parts/content types, duplicate/unsafe paths, encryption, compression type, part count, individual part size and aggregate expansion. Macros, OLE/ActiveX, embedded objects, external content relationships, external spreadsheet connections, XML entities/DTDs and active field instructions are rejected. Ordinary web/email hyperlinks remain permitted.
- Presentation preparation validates source documents before adding them to the bundle. It copies the validated byte snapshots; rejected documents are not quietly copied/opened. Knowledge import persists extracted text and source metadata in SQLite, not an executable copy of the supplied file.
- PDFs must have a PDF signature and are parsed in an owned worker with a 15-second deadline and 512 MiB process memory limit. Page, object and extracted-text limits apply. Scripts, attachments, external/automatic actions and active multimedia references are rejected. Only extracted text is returned to the parent.
- WAV input is limited by byte size, actual PCM format, sample rate/channel count, declared frame duration and actual frame length. Truncated and renamed executable recordings are rejected.
- Raster images require a supported actual image format, at most 25 MB and 32 megapixels. They are decoded, oriented correctly and re-encoded to bounded PNG pixels before native display/local vision. Original metadata and trailing polyglot data are discarded. Local videos receive container-signature and 500 MB checks before native playback; remote video sources remain restricted to the supported Wikimedia hosts.
- No imported file is served from a static web directory or executed by the server. Deliberate source-code generation remains available: it saves code for review and opens an editor, without executing that generated code.

These controls use the layered approach described in the [OWASP File Upload Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/File_Upload_Cheat_Sheet.html), adapted to this application's local import boundary.

### Native UI and API injection protection

- Remaining dynamic status/preferences labels and error dialogs explicitly use plain text.
- Text editors used for references, device configuration, standalone task review, email review and result display reject rich clipboard content. Their document resource loader cannot load file/network resources. HTML/JavaScript payloads remain visible literal text rather than formatted content.
- Conversation bubbles and existing dashboard/results labels retain their explicit plain-text rendering. Data is preserved in storage rather than destructively filtered; rendering is handled at the output boundary.
- The results panel permits only valid HTTP(S) source URLs and revalidates before opening. `javascript:`, `data:`, `file:`, custom application protocols, credentials, control characters and malformed URL ports are rejected.
- The local API rejects foreign/ambiguous Host headers, cross-origin browser requests and non-JSON bodies. Declared and streamed bodies have a 1 MiB limit and a 15-second receive deadline. Successful and rejected responses include JSON-safe/non-executable response policy headers, `nosniff`, framing protection and `Cache-Control: no-store` for private content.

This follows [OWASP's output-context guidance](https://cheatsheetseries.owasp.org/cheatsheets/Cross_Site_Scripting_Prevention_Cheat_Sheet.html). Qt native labels are not JavaScript engines, but auto-detected rich text can still interpret markup; the relevant behavior is documented by [Qt QLabel](https://doc.qt.io/qt-6/qlabel.html#text-prop) and [QTextDocument resource loading](https://doc.qt.io/qt-6/qtextdocument.html#loadResource).

### Archived WebView

The active dashboard does not use a WebView. The archive did contain unsafe JavaScript interpolation in `OrbWebWidget.set_state`.

- Only four fixed state names are accepted and JSON-encoded into the call.
- A dedicated off-the-record profile isolates the renderer from normal browser profiles. Downloads, permissions, popups, clipboard access and untrusted navigation are denied.
- A profile request interceptor allows exactly `orb.html` and its bundled `three.min.js`, blocking other file and network requests.
- A CSP permits the exact hashed inline script and bundled script, with connections, frames and objects disabled.
- Profile/page destruction order is explicit so the security isolation does not introduce a shutdown crash.

The real browser smoke test verifies the trusted script still loads and a malicious state does not execute. The interceptor and profile mechanisms follow the official [Qt request interceptor](https://doc.qt.io/qt-6/qwebengineurlrequestinterceptor.html) and [Qt profile documentation](https://doc.qt.io/qt-6/qwebengineprofile.html).

### Actual NTFS permissions

The project and `data` directories were found to grant Everyone full control. That exposed application code, inherited access to `.env`, and personal data to other local accounts.

The broad grants were removed from both directories. The signed-in Windows account and SYSTEM have full access, and existing named development/admin identities were retained. Inspection verifies no Everyone allow entry on the project, `.env`, API source, SQLite database or voice manifest. The original DACLs are saved in `data/reports/security-acl-before.sddl` and `security-project-acl-before.sddl`; evidence is in `security-storage-acl-checks.json`. File ownership and audit policies were not changed.

`scripts/secure_data.ps1` is reusable and refuses drive roots, network shares and reparse points. Setup applies the permissions before generating API secrets. The existing Windows dependency is declared for the setup security helper. No secrets were printed or rotated.

## Validation

- Dedicated adversarial tests: **86 passed**, covering active/renamed files, paths, size/content mismatches, archive paths/macros/relationships/entities, DDE fields, PDF scripts/timeouts, malformed WAVs, raster normalization, unsafe source protocols, literal UI rendering, API bounds/origins/headers and absent payment routes.
- The final full run passed **604 tests in 116.01 seconds**, including all 86 security cases. Evidence: `data/reports/security-audit-2026-10-23-tests-verified.log`.
- Desktop smoke checks passed for the original dashboard, images/muted video, synthetic device snapshots and exact external-task approval with a mock transport. Dashboard/approval checks passed again after tightening permissions.
- The real archived WebView loaded its bundled Three.js and state function under CSP, rejected the injected state and exited cleanly. See `security-legacy-webview-smoke.log`.
- Existing personal database read-only `PRAGMA quick_check` returned `ok` after permission changes. Voice files remain accessible.
- Ruff lint/format, Python compilation and PowerShell syntax checks passed. The only observed warning is the test fixture's use of pypdf's deprecated `add_js` helper to construct a malicious PDF.

Run the main checks from `E:\NISHA`:

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m pytest -q tests/test_security.py tests/test_legacy_webview_security.py
.\.venv\Scripts\python.exe scripts/verify_legacy_webview_security.py
```

## Remaining risks and limits

- Content validation is not an antivirus engine or a proof that arbitrary documents are harmless. Native codecs and document parsers still need security updates. The PDF worker provides resource isolation, not an OS sandbox that removes its filesystem/network privileges.
- Imported references can contain misleading instructions or facts. NISHA treats them as reference data; model accuracy and prompt-injection resistance are not guaranteed by XSS protection. These changes do not authorize model-generated shell commands or bypass email/account approvals.
- SQLite/reference data and `.env` are not newly encrypted at rest. Administrators, the signed-in user and retained trusted development identities can access them. A process already running as that user can still use local application privileges. The ACL backups should be handled as administration artifacts, not reapplied blindly.
- Tightening permissions cannot undo any historical access. Existing local API keys were not rotated; if an untrusted account previously accessed this folder, rotate those keys and restart the matching services.
- The API remains a personal loopback service with bearer authentication. It is not a production multi-user Internet deployment. There is no payment system or paid-access boundary to certify.
- Live Gmail sending, YouTube mutations and physical IoT actions were not performed by these tests. No external-model request was made; approval transports in the smoke check were mocked.
