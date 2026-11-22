"""Bound Office archive expansion before a document library loads its parts."""

import re
from pathlib import PurePosixPath
from xml.etree import ElementTree
from zipfile import ZIP_DEFLATED, ZIP_STORED, BadZipFile, ZipFile

from nisha.errors import NishaError

OFFICE_TYPES = {
    ".docx": (
        "word/document.xml",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml",
    ),
    ".pptx": (
        "ppt/presentation.xml",
        "application/vnd.openxmlformats-officedocument.presentationml.presentation.main+xml",
    ),
    ".xlsx": (
        "xl/workbook.xml",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml",
    ),
}


def safe_xml(data):
    # XML declarations can use UTF-16/32, so inspect null-stripped bytes too.
    normalized = data.replace(b"\x00", b"").upper()
    if b"<!DOCTYPE" in normalized or b"<!ENTITY" in normalized:
        raise NishaError("Document XML declarations and entities are not permitted.")
    return ElementTree.fromstring(data)


def check_office_archive(path, expected=None):
    try:
        with ZipFile(path) as archive:
            parts = archive.infolist()
            if (
                len(parts) > 2048
                or sum(part.file_size for part in parts) > 64_000_000
                or any(
                    part.file_size > 16_000_000
                    or part.flag_bits & 1
                    or part.compress_type not in {ZIP_DEFLATED, ZIP_STORED}
                    for part in parts
                )
            ):
                raise NishaError(
                    "This document exceeds safe reading limits. Split it into smaller files."
                )
            names = [part.filename.casefold() for part in parts]
            if len(set(names)) != len(names):
                raise NishaError("Duplicate Office archive parts are not permitted.")
            for part in parts:
                name = part.filename.casefold()
                if (
                    "\\" in name
                    or ":" in name
                    or name.startswith("/")
                    or ".." in PurePosixPath(name).parts
                    or (part.external_attr >> 16) & 0o170000 == 0o120000
                    or any(
                        marker in name
                        for marker in (
                            "vbaproject",
                            "vbadata",
                            "/activex/",
                            "/embeddings/",
                            "/customui/",
                            "xl/connections.xml",
                            "/querytables/",
                            "/externallinks/",
                        )
                    )
                ):
                    raise NishaError(
                        "Unsafe paths, macros and embedded active content are not permitted in Office imports."
                    )
                if name.endswith((".xml", ".rels")):
                    root = safe_xml(archive.read(part))
                    for element in root.iter():
                        instruction = (
                            element.text
                            if element.tag.endswith("}instrText")
                            else element.get(
                                "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}instr",
                                "",
                            )
                        )
                        if instruction and re.search(
                            r"\b(?:DDEAUTO|DDE|INCLUDETEXT|INCLUDEPICTURE|DATABASE)\b",
                            instruction,
                            re.IGNORECASE,
                        ):
                            raise NishaError("Active Office field instructions are not permitted.")
                    if name.endswith(".rels"):
                        for relationship in root:
                            relation_type = relationship.get("Type", "").casefold()
                            if any(
                                marker in relation_type
                                for marker in (
                                    "vbaproject",
                                    "oleobject",
                                    "activex",
                                    "attachedtemplate",
                                    "afchunk",
                                )
                            ):
                                raise NishaError("Active Office relationships are not permitted.")
                            if relationship.get("TargetMode", "").casefold() == "external":
                                from nisha.url_security import browser_source

                                target = relationship.get("Target", "")
                                safe_mail = bool(
                                    re.fullmatch(
                                        r"mailto:[A-Za-z0-9._+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}",
                                        target,
                                    )
                                )
                                if not relationship.get("Type", "").endswith("/hyperlink") or not (
                                    browser_source(target) or safe_mail
                                ):
                                    raise NishaError(
                                        "Externally linked Office content is not permitted; ordinary web/email hyperlinks are allowed."
                                    )
                    if name == "[content_types].xml" and any(
                        marker in ElementTree.tostring(root).lower()
                        for marker in (b"macroenabled", b"vbaproject", b"activex", b"oleobject")
                    ):
                        raise NishaError(
                            "Macro-enabled or embedded active Office content is not permitted."
                        )
            if expected:
                main_part, content_type = OFFICE_TYPES[expected]
                if (
                    main_part not in archive.namelist()
                    or "[Content_Types].xml" not in archive.namelist()
                ):
                    raise NishaError("Office content does not match the declared document format.")
                types = safe_xml(archive.read("[Content_Types].xml"))
                if not any(
                    item.get("PartName") == "/" + main_part
                    and item.get("ContentType") == content_type
                    for item in types
                ):
                    raise NishaError("Office content does not match the declared document format.")
    except (BadZipFile, OSError, ValueError, ElementTree.ParseError, RuntimeError) as exc:
        raise NishaError("This Office document is not a readable archive.") from exc
