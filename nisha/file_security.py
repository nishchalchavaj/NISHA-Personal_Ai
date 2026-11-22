"""Allowlisted, bounded snapshots of untrusted local imports. Never execute imports."""

import io
import json
from dataclasses import dataclass
from pathlib import Path, PureWindowsPath

from nisha.document_limits import check_office_archive
from nisha.errors import NishaError

TEXT_TYPES = frozenset({".txt", ".md", ".csv", ".json", ".jsonl"})
KNOWLEDGE_TYPES = TEXT_TYPES | {".docx", ".pdf"}
DOCUMENT_TYPES = TEXT_TYPES | {".docx", ".pptx", ".xlsx", ".pdf"}
IMAGE_TYPES = frozenset({".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif"})
EXECUTABLE_MAGIC = (
    b"MZ",
    b"\x7fELF",
    b"\xfe\xed\xfa\xce",
    b"\xce\xfa\xed\xfe",
    b"\xfe\xed\xfa\xcf",
    b"\xcf\xfa\xed\xfe",
)


@dataclass(frozen=True)
class ImportedFile:
    path: Path
    suffix: str
    data: bytes


def local_input_path(filename, allowed=None):
    """Reject network paths/ambiguous names before any filesystem lookup."""
    raw = str(filename)
    drive = PureWindowsPath(raw).drive
    if (
        not raw
        or "\x00" in raw
        or raw.startswith(("\\\\", "//"))
        or ":" in raw[len(drive) :]
        or any(char in raw for char in "\u202a\u202b\u202c\u202d\u202e\u2066\u2067\u2068\u2069")
        or raw.endswith((".", " "))
    ):
        raise NishaError(
            "Choose a local file with an unambiguous filename; network paths and alternate data streams are not allowed."
        )
    path = Path(raw)
    if allowed is not None and path.suffix.casefold() not in allowed:
        raise NishaError(
            "Unsupported file format. Choose an allowed document, image or recording type."
        )
    try:
        if path.is_symlink() or not path.is_file():
            raise NishaError("Choose an existing regular local file, not a symbolic link.")
        return path.resolve()
    except (OSError, ValueError) as exc:
        raise NishaError("The selected local file could not be read.") from exc


def read_local_file(filename, *, limit, allowed=None):
    """Check the path before filesystem access, then read a single bounded snapshot."""
    path = local_input_path(filename, allowed)
    try:
        with path.open("rb") as source:
            data = source.read(limit + 1)
    except (OSError, ValueError) as exc:
        raise NishaError("The selected local file could not be read.") from exc
    if not data or len(data) > limit:
        raise NishaError(f"Choose a non-empty file of at most {limit:,} bytes.")
    if data.startswith(EXECUTABLE_MAGIC):
        raise NishaError("Executable content is not accepted, including renamed executable files.")
    return ImportedFile(path, path.suffix.casefold(), data)


def text_content(data, suffix):
    try:
        text = data.decode("utf-8-sig")
        if any(ord(char) < 32 and char not in "\r\n\t\f" for char in text):
            raise ValueError("Binary control characters")
        if text.lstrip().startswith("#!"):
            raise ValueError("Executable script")
        if suffix == ".json":
            json.loads(text)
        elif suffix == ".jsonl":
            for line in text.splitlines():
                if line.strip():
                    json.loads(line)
        return text
    except (UnicodeError, ValueError, RecursionError) as exc:
        raise NishaError(
            "The file content does not match its permitted text format, or contains executable/binary content."
        ) from exc


def document_import(filename, allowed=KNOWLEDGE_TYPES):
    imported = read_local_file(filename, allowed=allowed, limit=20_000_000)
    if imported.suffix in TEXT_TYPES:
        text_content(imported.data, imported.suffix)
    elif imported.suffix in {".docx", ".pptx", ".xlsx"}:
        check_office_archive(io.BytesIO(imported.data), expected=imported.suffix)
    elif imported.suffix == ".pdf" and not imported.data.startswith(b"%PDF-"):
        raise NishaError("The file content does not match PDF format.")
    return imported
