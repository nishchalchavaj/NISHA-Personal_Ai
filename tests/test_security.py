"""Adversarial imports, native HTML injection, URL schemes and local API boundaries."""

import io
import wave
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

import pytest
from docx import Document
from fastapi.testclient import TestClient
from PIL import Image

from nisha.api import create_app
from nisha.api_security import MAX_REQUEST_BYTES
from nisha.document_limits import check_office_archive
from nisha.errors import NishaError
from nisha.file_security import document_import, read_local_file
from nisha.image_security import passive_image
from nisha.pdf_import import pdf_text
from nisha.url_security import browser_source
from nisha.voice_profile import read_wav


@pytest.fixture
def client(core, monkeypatch):
    monkeypatch.setenv("NISHA_API_KEY", "synthetic-security-token")
    return TestClient(
        create_app(core.settings, core),
        base_url="http://127.0.0.1",
        headers={"Authorization": "Bearer synthetic-security-token"},
    )


@pytest.mark.parametrize(
    "extension", [".exe", ".dll", ".cmd", ".bat", ".ps1", ".js", ".html", ".svg", ".docm", ".zip"]
)
def test_import_allowlist_rejects_active_formats(core, tmp_path, extension):
    path = tmp_path / ("import" + extension)
    path.write_bytes(b"not safe to execute")
    with pytest.raises(NishaError, match="Unsupported file format"):
        core.knowledge.import_file(path)
    assert not core.knowledge.sources()


@pytest.mark.parametrize(
    "payload",
    [
        b"MZrenamed.exe",
        b"\x7fELFrenamed",
        b"\xfe\xed\xfa\xcfrenamed",
        b"\x00binary",
        b"#!/bin/sh\necho dangerous",
        b"\xff\xfeinvalid utf8",
    ],
)
def test_renamed_executable_and_binary_text_is_rejected(core, tmp_path, payload):
    path = tmp_path / "innocent.exe.txt"
    path.write_bytes(payload)
    with pytest.raises(NishaError):
        core.knowledge.import_file(path)
    assert not core.knowledge.sources()


@pytest.mark.parametrize(
    "name",
    [
        r"\\attacker.invalid\share\notes.txt",
        "//attacker.invalid/share/notes.txt",
        r"C:\notes.txt:payload.txt",
        "notes\u202etxt.exe.txt",
        "notes.txt.",
        "notes.txt ",
    ],
)
def test_ambiguous_and_network_import_paths_rejected_before_access(monkeypatch, name):
    monkeypatch.setattr(
        Path, "is_file", lambda *_: pytest.fail("Filesystem access before validation")
    )
    with pytest.raises(NishaError):
        read_local_file(name, allowed={".txt"}, limit=100)


def test_file_limit_is_enforced_by_read_not_filename_or_declared_size(tmp_path):
    path = tmp_path / "oversized.txt"
    path.write_bytes(b"x" * 101)
    with pytest.raises(NishaError, match="at most 100 bytes"):
        read_local_file(path, allowed={".txt"}, limit=100)


@pytest.mark.parametrize(
    "extension,payload",
    [
        (".json", "not json"),
        (".jsonl", '{"valid":true}\nnot json'),
        (".pdf", "%not a pdf"),
        (".docx", "not a zip"),
    ],
)
def test_content_must_match_declared_document_type(tmp_path, extension, payload):
    path = tmp_path / ("source" + extension)
    path.write_text(payload)
    with pytest.raises(NishaError):
        document_import(path)


def test_text_import_uses_validated_snapshot_and_stores_only_text(core, tmp_path, monkeypatch):
    import nisha.file_security

    path = tmp_path / "notes.txt"
    path.write_text("Reviewed engineering reference.")
    original = nisha.file_security.document_import

    def swap_after_validation(filename):
        imported = original(filename)
        path.write_bytes(b"MZ changed after validation")
        return imported

    monkeypatch.setattr(nisha.file_security, "document_import", swap_after_validation)
    core.knowledge.import_file(path)
    assert "Reviewed engineering" in core.knowledge.search("engineering")[0]["text"]
    assert list(core.settings.data_dir.glob("**/notes.txt")) == [path]


@pytest.fixture
def docx_bytes():
    output = io.BytesIO()
    document = Document()
    document.add_paragraph("A valid passive document.")
    document.save(output)
    return output.getvalue()


def office_with(data, added=None, replaced=None):
    output = io.BytesIO()
    with (
        ZipFile(io.BytesIO(data)) as source,
        ZipFile(output, "w", compression=ZIP_DEFLATED) as target,
    ):
        for part in source.infolist():
            target.writestr(part.filename, (replaced or {}).get(part.filename, source.read(part)))
        for name, payload in (added or {}).items():
            target.writestr(name, payload)
    return output.getvalue()


@pytest.mark.parametrize(
    "name",
    [
        "word/vbaProject.bin",
        "word/embeddings/oleObject1.bin",
        "word/activeX/activeX1.xml",
        "../outside.txt",
        "/absolute.xml",
        "word\\traversal.xml",
    ],
)
def test_office_active_content_and_unsafe_paths_rejected(docx_bytes, name):
    with pytest.raises(NishaError):
        check_office_archive(
            io.BytesIO(office_with(docx_bytes, {name: b"payload"})), expected=".docx"
        )


def test_office_duplicate_and_mismatched_main_parts_rejected(docx_bytes):
    output = io.BytesIO(docx_bytes)
    with pytest.warns(UserWarning), ZipFile(output, "a") as archive:
        archive.writestr("word/document.xml", "duplicate")
    with pytest.raises(NishaError, match="Duplicate"):
        check_office_archive(io.BytesIO(output.getvalue()), expected=".docx")
    with pytest.raises(NishaError, match="declared document format"):
        check_office_archive(io.BytesIO(docx_bytes), expected=".pptx")


@pytest.mark.parametrize("encoding", ["utf-8", "utf-16", "utf-32"])
def test_office_xml_entities_rejected_before_parser(docx_bytes, encoding):
    xml = '<?xml version="1.0"?><!DOCTYPE root [<!ENTITY secret SYSTEM "file:///private.txt">]><root>&secret;</root>'
    with pytest.raises(NishaError, match="entities"):
        check_office_archive(
            io.BytesIO(
                office_with(docx_bytes, replaced={"word/document.xml": xml.encode(encoding)})
            ),
            expected=".docx",
        )


@pytest.mark.parametrize(
    "kind,target",
    [
        ("image", "http://attacker.invalid/track"),
        ("hyperlink", "javascript:alert(1)"),
        ("hyperlink", "file:///C:/Windows/System32/cmd.exe"),
    ],
)
def test_office_external_active_relationships_rejected(docx_bytes, kind, target):
    rels = f'<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="bad" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/{kind}" Target="{target}" TargetMode="External"/></Relationships>'
    with pytest.raises(NishaError, match="Externally linked"):
        check_office_archive(
            io.BytesIO(office_with(docx_bytes, {"word/_rels/extra.xml.rels": rels.encode()})),
            expected=".docx",
        )


def test_valid_docx_and_normal_web_hyperlinks_are_preserved(core, tmp_path, docx_bytes):
    rels = b'<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="ok" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/hyperlink" Target="https://example.com/reference" TargetMode="External"/></Relationships>'
    path = tmp_path / "VALID.DOCX"
    path.write_bytes(office_with(docx_bytes, {"word/_rels/extra.xml.rels": rels}))
    core.knowledge.import_file(path)
    assert "passive document" in core.knowledge.search("passive")[0]["text"]


def make_pdf(script=None):
    from pypdf import PdfWriter
    from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

    writer = PdfWriter()
    page = writer.add_blank_page(width=600, height=800)
    font = DictionaryObject(
        {
            NameObject("/Type"): NameObject("/Font"),
            NameObject("/Subtype"): NameObject("/Type1"),
            NameObject("/BaseFont"): NameObject("/Helvetica"),
        }
    )
    page[NameObject("/Resources")] = DictionaryObject(
        {NameObject("/Font"): DictionaryObject({NameObject("/F1"): font})}
    )
    content = DecodedStreamObject()
    content.set_data(b"BT /F1 12 Tf 10 700 Td (Passive engineering PDF.) Tj ET")
    page[NameObject("/Contents")] = writer._add_object(content)
    if script:
        writer.add_js(script)
    output = io.BytesIO()
    writer.write(output)
    return output.getvalue()


def test_valid_pdf_is_read_in_bounded_worker_and_learned(core, tmp_path):
    path = tmp_path / "reference.pdf"
    path.write_bytes(make_pdf())
    core.knowledge.import_file(path)
    assert "Passive engineering PDF" in core.knowledge.search("engineering")[0]["text"]


def test_pdf_javascript_is_rejected_without_indexing(core, tmp_path):
    path = tmp_path / "active.pdf"
    path.write_bytes(make_pdf("app.alert('untrusted')"))
    with pytest.raises(NishaError, match="active actions"):
        core.knowledge.import_file(path)
    assert not core.knowledge.sources()


def test_pdf_reader_timeout_terminates_the_owned_worker():
    import multiprocessing

    before = {process.pid for process in multiprocessing.active_children()}
    with pytest.raises(NishaError, match="time limit"):
        pdf_text(make_pdf(), timeout=0.001)
    assert {process.pid for process in multiprocessing.active_children()} <= before


def test_voice_upload_header_and_actual_frame_length_are_checked(tmp_path):
    path = tmp_path / "sample.wav"
    output = io.BytesIO()
    with wave.open(output, "wb") as stream:
        stream.setparams((1, 2, 16000, 0, "NONE", "not compressed"))
        stream.writeframes(b"\x01\x00" * 16000)
    path.write_bytes(output.getvalue())
    assert len(read_wav(path)) == 16000
    path.write_bytes(output.getvalue()[:-100])
    with pytest.raises(NishaError, match="truncated"):
        read_wav(path)
    path.write_bytes(b"MZ renamed as WAV")
    with pytest.raises(NishaError, match="Executable"):
        read_wav(path)


def test_raster_image_type_check_and_metadata_polyglot_removal():
    output = io.BytesIO()
    Image.new("RGB", (12, 12), "blue").save(output, format="PNG")
    payload = output.getvalue() + b"<script>alert('polyglot')</script>"
    normalized = passive_image(payload, ".png")
    assert b"<script>" not in normalized and Image.open(io.BytesIO(normalized)).size == (12, 12)
    with pytest.raises(NishaError, match="format"):
        passive_image(payload, ".jpg")
    with pytest.raises(NishaError):
        passive_image(b'<svg onload="alert(1)"></svg>')


@pytest.mark.parametrize(
    "url",
    [
        "javascript:alert(1)",
        "data:text/html,<script>x</script>",
        "file:///C:/malware.exe",
        "ms-msdt:/payload",
        "https://user:password@example.com",
        "https://example.com/%0aevil",
        "https://example.com\\@attacker.invalid",
        "https://example.com:bad",
    ],
)
def test_untrusted_source_urls_cannot_launch_active_protocols(url):
    assert not browser_source(url)


@pytest.fixture
def app(monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


def test_native_text_widgets_keep_xss_payload_literal_and_disable_rich_paste(app):
    from PySide6.QtCore import QMimeData, Qt

    from nisha.ui.conversation_panel import MessageBubble
    from nisha.ui.text_security import PlainTextEdit

    payload = '<img src="file:///private.png"><script>alert(1)</script><a href="javascript:alert(1)">click</a>'
    editor = PlainTextEdit()
    editor.setHtml(payload)
    assert editor.toPlainText() == payload and not editor.acceptRichText()
    bubble = MessageBubble("user", payload)
    assert bubble.body.text() == payload and bubble.body.textFormat() == Qt.PlainText
    mime = QMimeData()
    mime.setHtml('<img src="file:///private.png"><b>formatted</b>')
    mime.setText("plain clipboard data")
    editor.clear()
    editor.insertFromMimeData(mime)
    assert editor.toPlainText() == "plain clipboard data"
    editor.close()
    bubble.close()


def test_source_button_revalidates_url_before_opening(app, monkeypatch):
    from PySide6.QtGui import QDesktopServices

    from nisha.media import MediaAsset
    from nisha.ui.visual_panel import VisualPanel

    opened = []
    monkeypatch.setattr(QDesktopServices, "openUrl", lambda url: opened.append(url.toString()))
    panel = VisualPanel()
    panel.assets = [MediaAsset("image", "untrusted", "unused", "javascript:alert(1)")]
    panel.open_source()
    assert not opened
    panel.assets[0].source = "https://example.com/reference"
    panel.open_source()
    assert opened == ["https://example.com/reference"]
    panel.close()


def test_api_json_output_is_private_and_non_executable(client):
    payload = "<img src=x onerror=alert(1)><script>alert(2)</script>"
    response = client.post("/memories", json={"text": payload})
    assert response.status_code == 200
    response = client.get("/memories")
    assert response.json()[0]["text"] == payload
    assert response.headers["content-type"].startswith("application/json")
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["cache-control"] == "no-store"
    assert "default-src 'none'" in response.headers["content-security-policy"]


def test_api_rejects_dns_rebinding_and_cross_origin_requests(client):
    assert client.get("/memories", headers={"Host": "attacker.invalid"}).status_code == 400
    assert (
        client.get("/memories", headers={"Origin": "https://attacker.invalid"}).status_code == 403
    )
    assert client.get("/memories", headers={"Origin": "null"}).status_code == 403
    assert client.get("/memories", headers={"Origin": "http://127.0.0.1"}).status_code == 200


def test_api_rejects_multipart_and_bounds_declared_and_chunked_body(client):
    assert client.post("/chat", files={"file": ("evil.exe", b"MZbinary")}).status_code == 415
    oversized = b"x" * (MAX_REQUEST_BYTES + 1)
    assert (
        client.post(
            "/chat", content=oversized, headers={"Content-Type": "application/json"}
        ).status_code
        == 413
    )
    assert (
        client.post(
            "/chat",
            content=iter([oversized[:500_000], oversized[500_000:]]),
            headers={"Content-Type": "application/json"},
        ).status_code
        == 413
    )


@pytest.mark.parametrize(
    "path", ["/webhook", "/webhooks/stripe", "/payments/success", "/checkout/success"]
)
def test_no_payment_routes_accept_client_claims_or_grant_access(client, core, path):
    response = client.post(
        path, json={"paid": True, "status": "success", "amount": 1, "order_id": "forged"}
    )
    assert response.status_code == 404
    assert not core.gateway.calls


def test_office_active_relationship_cannot_hide_under_an_innocent_part_name(docx_bytes):
    rels = b'<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="bad" Type="http://schemas.microsoft.com/office/2006/relationships/vbaProject" Target="innocent.bin"/></Relationships>'
    with pytest.raises(NishaError, match="Active Office relationships"):
        check_office_archive(
            io.BytesIO(office_with(docx_bytes, {"word/_rels/extra.xml.rels": rels})),
            expected=".docx",
        )


def test_office_dde_fields_are_rejected_but_text_about_dde_is_allowed(docx_bytes):
    active = b'<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:fldSimple w:instr="DDEAUTO command dangerous"/></w:body></w:document>'
    with pytest.raises(NishaError, match="field instructions"):
        check_office_archive(
            io.BytesIO(office_with(docx_bytes, replaced={"word/document.xml": active})),
            expected=".docx",
        )
    passive = active.replace(
        b'<w:fldSimple w:instr="DDEAUTO command dangerous"/>',
        b"<w:p><w:r><w:t>An article about DDEAUTO.</w:t></w:r></w:p>",
    )
    check_office_archive(
        io.BytesIO(office_with(docx_bytes, replaced={"word/document.xml": passive})),
        expected=".docx",
    )


def test_video_header_is_checked_before_native_player_receives_a_path(tmp_path):
    from nisha.video_security import local_video

    path = tmp_path / "renamed.mp4"
    path.write_bytes(b"MZ executable with video extension")
    with pytest.raises(NishaError, match="container format"):
        local_video(path)
    path.write_bytes(b"\x00\x00\x00\x18ftypisom" + b"\x00" * 20)
    assert local_video(path) == path


def test_error_dialog_is_plain_text(app, monkeypatch):
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QMessageBox

    from nisha.ui.text_security import plain_warning

    messages = []
    monkeypatch.setattr(
        QMessageBox, "exec", lambda dialog: messages.append((dialog.textFormat(), dialog.text()))
    )
    payload = '<img src="file:///private.png"><a href="javascript:alert(1)">error</a>'
    plain_warning(None, "Error", payload)
    assert messages == [(Qt.PlainText, payload)]


def test_api_slow_request_body_is_bounded(monkeypatch):
    import asyncio

    from nisha.api_security import LocalApiBoundary

    timeout = asyncio.timeout
    monkeypatch.setattr(asyncio, "timeout", lambda _: timeout(0.01))
    sent = []

    async def app(*args):
        pytest.fail("Incomplete request reached application")

    async def receive():
        await asyncio.sleep(60)

    async def send(message):
        sent.append(message)

    scope = {
        "type": "http",
        "method": "POST",
        "scheme": "http",
        "headers": [(b"host", b"127.0.0.1"), (b"content-type", b"application/json")],
    }
    asyncio.run(LocalApiBoundary(app)(scope, receive, send))
    assert sent[0]["status"] == 408


def test_duplicate_host_headers_are_rejected(client):
    response = client.get(
        "/memories", headers=[("Host", "127.0.0.1"), ("Host", "attacker.invalid")]
    )
    assert response.status_code == 400


def test_image_orientation_is_preserved_and_metadata_removed():
    image = Image.new("RGB", (10, 20), "blue")
    exif = image.getexif()
    exif[274] = 6
    output = io.BytesIO()
    image.save(output, format="JPEG", exif=exif)
    with Image.open(io.BytesIO(passive_image(output.getvalue(), ".jpg"))) as normalized:
        assert normalized.size == (20, 10)
        assert not normalized.getexif()
        assert not normalized.info


def test_secure_storage_script_preserves_files_and_removes_broad_access(tmp_path):
    import json
    import os
    import subprocess

    if os.name != "nt":
        pytest.skip("Windows NTFS ACL verification")
    folder = tmp_path / "private-data"
    folder.mkdir()
    child = folder / "knowledge.txt"
    child.write_text("Private reference remains accessible.")
    backup = tmp_path / "original-acl.sddl"
    result = subprocess.run(
        [
            "powershell.exe",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(Path(__file__).resolve().parents[1] / "scripts/secure_data.ps1"),
            "-DataDir",
            str(folder),
            "-BackupFile",
            str(backup),
        ],
        capture_output=True,
        check=False,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["broad_access"] is False
    assert backup.is_file() and child.read_text() == "Private reference remains accessible."
