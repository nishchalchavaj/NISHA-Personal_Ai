"""Parse imported PDFs in a bounded child process; return passive text only."""

import io
import logging
import multiprocessing
import os

from nisha.errors import NishaError


def _pdf_text(data, page_limit):
    from pypdf import PdfReader
    from pypdf.generic import ArrayObject, DictionaryObject, IndirectObject

    reader = PdfReader(io.BytesIO(data), strict=True)
    if reader.is_encrypted:
        raise NishaError("Unlock this PDF before importing it.")
    if len(reader.pages) > 300:
        raise NishaError("Split this PDF into parts of up to 300 pages before importing it.")
    pending, seen, count = [reader.trailer], set(), 0
    while pending:
        obj = pending.pop()
        if isinstance(obj, IndirectObject):
            identity = (obj.idnum, obj.generation)
            if identity in seen:
                continue
            seen.add(identity)
            obj = obj.get_object()
        count += 1
        if count > 50_000:
            raise NishaError("This PDF exceeds the safe object reading limit.")
        if isinstance(obj, DictionaryObject):
            if any(
                key in obj
                for key in (
                    "/JS",
                    "/JavaScript",
                    "/AA",
                    "/EmbeddedFiles",
                    "/EF",
                    "/XFA",
                    "/RichMediaContent",
                    "/Movie",
                    "/Sound",
                )
            ) or obj.get("/S") in {
                "/JavaScript",
                "/Launch",
                "/SubmitForm",
                "/ImportData",
                "/GoToR",
                "/GoToE",
                "/Rendition",
                "/RichMediaExecute",
            }:
                raise NishaError("PDF scripts, attachments and active actions are not permitted.")
            if obj.get("/Type") == "/Filespec":
                raise NishaError("PDF external file references and attachments are not permitted.")
            if "/OpenAction" in obj:
                action = obj["/OpenAction"]
                if not isinstance(action, ArrayObject) and not (
                    isinstance(action, DictionaryObject) and action.get("/S") == "/GoTo"
                ):
                    raise NishaError("Automatic external PDF actions are not permitted.")
            if "/URI" in obj:
                from nisha.url_security import browser_source

                if not browser_source(str(obj["/URI"])):
                    raise NishaError("Unsafe PDF link protocols are not permitted.")
            pending.extend(obj.values())
        elif isinstance(obj, (list, ArrayObject)):
            pending.extend(obj)
    chunks, length = [], 0
    for page in reader.pages[:page_limit]:
        text = page.extract_text() or ""
        length += len(text) + 1
        if length > 500_000:
            raise NishaError("Split this PDF into smaller text sources before importing it.")
        chunks.append(text)
    return "\n".join(chunks)


def _worker(connection, data, page_limit):
    try:
        if os.name == "nt":
            from nisha.process_lifetime import attach_child_lifetime

            attach_child_lifetime(memory_limit=512 * 1024 * 1024)
        else:
            import resource

            resource.setrlimit(resource.RLIMIT_AS, (512 * 1024 * 1024,) * 2)
        connection.send((True, _pdf_text(data, page_limit)))
    except NishaError as exc:
        connection.send((False, str(exc)))
    except Exception as exc:  # noqa: BLE001 -- isolated parser boundary must fail closed.
        logging.getLogger("nisha").warning("Bounded PDF import failed: %s", type(exc).__name__)
        connection.send(
            (
                False,
                "This PDF could not be safely read. Check its format or provide a plain-text version.",
            )
        )
    finally:
        connection.close()


def pdf_text(data, *, page_limit=300, timeout=15):
    if not data.startswith(b"%PDF-") or len(data) > 20_000_000:
        raise NishaError("Choose a valid PDF of at most 20 MB.")
    context = multiprocessing.get_context("spawn")
    parent, child = context.Pipe(duplex=False)
    process = context.Process(target=_worker, args=(child, data, page_limit), daemon=True)
    try:
        process.start()
        child.close()
        if not parent.poll(timeout):
            raise NishaError(
                "PDF reading exceeded its time limit. Split it or provide a plain-text version."
            )
        try:
            success, text = parent.recv()
        except EOFError as exc:
            raise NishaError(
                "The bounded PDF reader stopped. Try a smaller or plain-text document."
            ) from exc
        if not success:
            raise NishaError(text)
        return text
    finally:
        parent.close()
        child.close()
        if process.pid is not None:
            process.join(timeout=0.5)
            if process.is_alive():
                process.terminate()
                process.join(timeout=2)
            process.close()
