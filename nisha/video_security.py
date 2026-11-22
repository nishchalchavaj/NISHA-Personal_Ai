"""Lightweight container and byte-size gate before the native media decoder."""

from nisha.errors import NishaError
from nisha.file_security import local_input_path


def local_video(filename):
    path = local_input_path(filename, {".mp4", ".mov", ".webm", ".mkv", ".avi"})
    if not 12 <= path.stat().st_size <= 500_000_000:
        raise NishaError("Choose a video of at most 500 MB.")
    with path.open("rb") as source:
        header = source.read(32)
    suffix = path.suffix.casefold()
    valid = (
        suffix == ".mp4"
        and header[4:8] == b"ftyp"
        or suffix == ".mov"
        and header[4:8] in {b"ftyp", b"moov", b"mdat", b"wide"}
        or suffix in {".webm", ".mkv"}
        and header.startswith(b"\x1a\x45\xdf\xa3")
        or suffix == ".avi"
        and header.startswith(b"RIFF")
        and header[8:12] == b"AVI "
    )
    if not valid:
        raise NishaError("Video content does not match an allowed container format.")
    return path
