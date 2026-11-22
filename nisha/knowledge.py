"""Local user-selected knowledge; no cloud embeddings, uploads or weight training."""

import re
from hashlib import sha256
from io import BytesIO
from uuid import uuid4

from nisha.errors import NishaError
from nisha.storage import now

STOPWORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "can",
    "could",
    "do",
    "does",
    "for",
    "from",
    "how",
    "i",
    "in",
    "is",
    "it",
    "me",
    "my",
    "of",
    "on",
    "or",
    "please",
    "tell",
    "that",
    "the",
    "this",
    "to",
    "was",
    "what",
    "when",
    "where",
    "which",
    "who",
    "why",
    "with",
    "you",
    "your",
    "about",
    "explain",
    "know",
    "answer",
}


class Knowledge:
    def __init__(self, store):
        self.store = store

    def add_text(self, name, text, kind="user_text"):
        text = text.strip()
        if not text or len(text) > 500_000:
            raise NishaError("Choose non-empty text up to 500,000 characters per source.")
        digest = sha256(text.encode("utf-8")).hexdigest()
        source = uuid4().hex[:12]
        # Whole import is atomic, including the searchable chunks.
        with self.store.connect() as db:
            existing = db.execute(
                "SELECT id FROM knowledge_sources WHERE digest=?", (digest,)
            ).fetchone()
            if existing:
                return existing["id"]
            db.execute(
                "INSERT INTO knowledge_sources VALUES(?,?,?,?,?)",
                (source, name[:200], kind, digest, now()),
            )
            db.executemany(
                "INSERT INTO knowledge_search VALUES(?,?,?)",
                [
                    (source, index, text[offset : offset + 1200])
                    for index, offset in enumerate(range(0, len(text), 1000))
                ],
            )
        return source

    def import_file(self, filename):
        from nisha.file_security import document_import, text_content

        imported = document_import(filename)
        path, suffix = imported.path, imported.suffix
        try:
            if suffix in {".txt", ".md", ".csv", ".json", ".jsonl"}:
                text = text_content(imported.data, suffix)
            elif suffix == ".docx":
                from docx import Document

                document = Document(BytesIO(imported.data))
                text = "\n".join(p.text for p in document.paragraphs)
                text += "\n" + "\n".join(
                    " | ".join(cell.text for cell in row.cells)
                    for table in document.tables
                    for row in table.rows
                )
            elif suffix == ".pdf":
                from nisha.pdf_import import pdf_text

                text = pdf_text(imported.data)
                if not text.strip():
                    raise NishaError(
                        "This PDF has no extractable text. OCR isn't installed; provide a text version."
                    )
            else:
                raise NishaError(
                    "Supported knowledge files: TXT, Markdown, CSV, JSON, JSONL, DOCX and text PDFs."
                )
        except NishaError:
            raise
        except Exception as exc:
            raise NishaError("That file couldn't be read. Check its format and encoding.") from exc
        return self.add_text(path.name, text, "user_file")

    def sources(self):
        with self.store.connect() as db:
            return [
                dict(row)
                for row in db.execute("SELECT * FROM knowledge_sources ORDER BY created_at DESC")
            ]

    def forget(self, source):
        with self.store.connect() as db:
            if db.execute(
                "SELECT 1 FROM sqlite_master WHERE name='teacher_examples' AND type='table'"
            ).fetchone():
                if db.execute(
                    "SELECT 1 FROM sqlite_master WHERE name='conversation_teachers' AND type='table'"
                ).fetchone():
                    db.execute(
                        "DELETE FROM conversation_teachers WHERE teacher_id IN (SELECT id FROM teacher_examples WHERE source_id=?)",
                        (source,),
                    )
                db.execute("DELETE FROM teacher_examples WHERE source_id=?", (source,))
            db.execute("DELETE FROM knowledge_search WHERE source_id=?", (source,))
            return db.execute("DELETE FROM knowledge_sources WHERE id=?", (source,)).rowcount > 0

    def search(self, text, limit=3):
        words = list(
            dict.fromkeys(
                word
                for word in re.findall(r"\w+", text.casefold())
                if word not in STOPWORDS and len(word) > 1
            )
        )[:20]
        if not words:
            return []
        with self.store.connect() as db:
            rows = db.execute(
                "SELECT s.id,s.name,s.kind,k.text FROM knowledge_search k JOIN knowledge_sources s ON s.id=k.source_id WHERE knowledge_search MATCH ? AND s.kind != 'conversation_style_example' ORDER BY rank LIMIT ?",
                (" OR ".join('"' + word + '"' for word in words), limit),
            )
            return [dict(row) for row in rows]

    def handle(self, text):
        if text.casefold().strip() in {"/knowledge", "show my knowledge", "show learned sources"}:
            return "Local knowledge sources:\n" + (
                "\n".join(f"{row['id']} · {row['name']} ({row['kind']})" for row in self.sources())
                or "No sources yet. Use Ctrl+L to add files or paste text."
            )
        if text.startswith("/learn-file "):
            source = self.import_file(text[len("/learn-file ") :].strip().strip('"'))
            return f"Learned locally. Source: {source}."
        if text.casefold().startswith(("learn this:", "remember this information:", "/learn ")):
            value = (
                text.split(":", 1)[1]
                if ":" in text and not text.startswith("/learn ")
                else text[len("/learn ") :]
            )
            source = self.add_text("User-provided information", value)
            return f"Added to local knowledge. Source: {source}."
        if text.startswith("/forget-source "):
            return (
                "Source removed from local knowledge."
                if self.forget(text.split(maxsplit=1)[1])
                else "Source not found."
            )
        return None
