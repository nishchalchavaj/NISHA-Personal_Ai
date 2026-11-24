"""SQLite persists transcripts and explicitly selected memories in separate tables."""

import re
import sqlite3
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

MEMORY_STOP_WORDS = {
    "a",
    "an",
    "the",
    "is",
    "are",
    "was",
    "were",
    "am",
    "be",
    "been",
    "being",
    "i",
    "me",
    "my",
    "mine",
    "we",
    "our",
    "you",
    "your",
    "it",
    "its",
    "this",
    "that",
    "these",
    "those",
    "what",
    "who",
    "how",
    "when",
    "where",
    "why",
    "which",
    "do",
    "does",
    "did",
    "can",
    "could",
    "would",
    "should",
    "will",
    "about",
    "of",
    "on",
    "in",
    "at",
    "to",
    "for",
    "with",
    "from",
    "and",
    "or",
    "not",
    "please",
    "tell",
    "show",
    "know",
    "say",
    "s",
    "t",
}


def now():
    return datetime.now(UTC).isoformat()


class Store:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        with self.connect() as db:
            db.executescript("""
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS sessions (
                    id TEXT PRIMARY KEY, summary TEXT NOT NULL DEFAULT '',
                    summarized_until INTEGER NOT NULL DEFAULT 0);
                CREATE VIRTUAL TABLE IF NOT EXISTS conversation_summary_search USING fts5(
                    session_id UNINDEXED, summary, updated_at UNINDEXED);
                CREATE TABLE IF NOT EXISTS turns (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, session_id TEXT NOT NULL,
                    role TEXT NOT NULL, content TEXT NOT NULL,
                    cloud_allowed INTEGER NOT NULL, created_at TEXT NOT NULL);
                CREATE INDEX IF NOT EXISTS turn_session ON turns(session_id, id);
                CREATE TABLE IF NOT EXISTS memories (
                    id TEXT PRIMARY KEY, key TEXT UNIQUE, text TEXT NOT NULL,
                    category TEXT NOT NULL, source TEXT NOT NULL, confidence REAL NOT NULL,
                    importance INTEGER NOT NULL, cloud_allowed INTEGER NOT NULL,
                    created_at TEXT NOT NULL, updated_at TEXT NOT NULL, expires_at TEXT);
                CREATE VIRTUAL TABLE IF NOT EXISTS memory_search USING fts5(id UNINDEXED, text);
                CREATE TABLE IF NOT EXISTS audit (
                    id INTEGER PRIMARY KEY, action TEXT NOT NULL, outcome TEXT NOT NULL,
                    created_at TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS task_results (
                    id TEXT PRIMARY KEY, model TEXT NOT NULL, task TEXT NOT NULL,
                    result TEXT NOT NULL, created_at TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS email_approvals (
                    token TEXT PRIMARY KEY, session_id TEXT NOT NULL, path TEXT NOT NULL,
                    digest TEXT NOT NULL, expires REAL NOT NULL, status TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS preferences (
                    key TEXT PRIMARY KEY, value TEXT NOT NULL, evidence TEXT NOT NULL,
                    observations INTEGER NOT NULL, updated_at TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS knowledge_sources (
                    id TEXT PRIMARY KEY, name TEXT NOT NULL, kind TEXT NOT NULL,
                    digest TEXT UNIQUE NOT NULL, created_at TEXT NOT NULL);
                CREATE VIRTUAL TABLE IF NOT EXISTS knowledge_search USING fts5(
                    source_id UNINDEXED, ordinal UNINDEXED, text);
                CREATE TABLE IF NOT EXISTS user_observations (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, session_id TEXT NOT NULL,
                    content TEXT NOT NULL, prior_reply TEXT NOT NULL, created_at TEXT NOT NULL);
                CREATE INDEX IF NOT EXISTS observation_session ON user_observations(session_id,id);
                CREATE TABLE IF NOT EXISTS conversation_reviews (
                    session_id TEXT PRIMARY KEY, requested_until INTEGER NOT NULL,
                    cursor INTEGER NOT NULL DEFAULT 0, lease_until REAL NOT NULL DEFAULT 0,
                    retry_after REAL NOT NULL DEFAULT 0, status TEXT NOT NULL DEFAULT 'pending');
                CREATE TABLE IF NOT EXISTS memory_evidence (
                    memory_id TEXT PRIMARY KEY, observation_id INTEGER NOT NULL,
                    quote TEXT NOT NULL, created_at TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS forgotten_evidence (digest TEXT PRIMARY KEY);
                CREATE TABLE IF NOT EXISTS forgotten_slots (key TEXT PRIMARY KEY, until_id INTEGER NOT NULL);
                CREATE TABLE IF NOT EXISTS turn_outcomes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, session_id TEXT NOT NULL,
                    request TEXT NOT NULL, status TEXT NOT NULL, detail TEXT NOT NULL,
                    created_at TEXT NOT NULL);
            """)
            # Backfill summaries written before the searchable conversation index existed.
            for row in db.execute(
                "SELECT id,summary FROM sessions WHERE summary!='' "
                "AND id NOT IN (SELECT session_id FROM conversation_summary_search)"
            ):
                db.execute(
                    "INSERT INTO conversation_summary_search VALUES(?,?,?)",
                    (row["id"], row["summary"], now()),
                )

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    def new_session(self):
        session = str(uuid4())
        with self.connect() as db:
            db.execute("INSERT INTO sessions(id) VALUES (?)", (session,))
        return session

    def history(self, session):
        with self.connect() as db:
            state = db.execute("SELECT * FROM sessions WHERE id=?", (session,)).fetchone()
            if state is None:
                raise ValueError("Unknown session. Start a new conversation.")
            rows = db.execute("SELECT * FROM turns WHERE session_id=? ORDER BY id", (session,))
            return dict(state), [dict(row) for row in rows]

    def exchange(self, session, user, assistant, cloud_allowed):
        # Commit only complete pairs, so outages do not leave unanswered user turns.
        with self.connect() as db:
            if not db.execute("SELECT id FROM sessions WHERE id=?", (session,)).fetchone():
                raise ValueError("Unknown session.")
            db.executemany(
                "INSERT INTO turns(session_id,role,content,cloud_allowed,created_at) VALUES(?,?,?,?,?)",
                [
                    (session, role, text, int(cloud_allowed), now())
                    for role, text in (("user", user), ("assistant", assistant))
                ],
            )
            return db.execute("SELECT last_insert_rowid()").fetchone()[0]

    def save_summary(self, session, summary, until):
        with self.connect() as db:
            db.execute(
                "UPDATE sessions SET summary=?, summarized_until=? WHERE id=?",
                (summary, until, session),
            )
            db.execute(
                "DELETE FROM conversation_summary_search WHERE session_id=?", (session,)
            )
            if summary.strip():
                db.execute(
                    "INSERT INTO conversation_summary_search VALUES(?,?,?)",
                    (session, summary, now()),
                )

    def relevant_summaries(self, text, exclude_session, limit=2, include_recent=False):
        """Retrieve a few local summaries; never load another conversation's full transcript."""
        words = [
            word
            for word in re.findall(r"[a-z0-9]+", text.casefold())
            if len(word) > 2 and word not in MEMORY_STOP_WORDS
        ][:20]
        query = " OR ".join('"' + word + '"' for word in words)
        with self.connect() as db:
            if query:
                rows = db.execute(
                    "SELECT session_id,summary,updated_at FROM conversation_summary_search "
                    "WHERE conversation_summary_search MATCH ? AND session_id!=? "
                    "ORDER BY rank LIMIT ?",
                    (query, exclude_session, limit),
                ).fetchall()
                if rows:
                    return [dict(row) for row in rows]
            if not include_recent:
                return []
            rows = db.execute(
                "SELECT s.session_id,s.summary,s.updated_at "
                "FROM conversation_summary_search s "
                "WHERE s.session_id!=? ORDER BY s.updated_at DESC LIMIT ?",
                (exclude_session, limit),
            ).fetchall()
            return [dict(row) for row in rows]

    def remember(
        self, text, key=None, category="fact", cloud_allowed=False, source="explicit_user"
    ):
        text = text.strip()
        if not text or len(text) > 2000:
            raise ValueError("A memory must contain 1–2000 characters.")
        with self.connect() as db:
            existing = db.execute(
                "SELECT id,created_at FROM memories WHERE key=?"
                if key
                else "SELECT id,created_at FROM memories WHERE text=? LIMIT 1",
                (key if key else text,),
            ).fetchone()
            memory_id = existing["id"] if existing else str(uuid4())
            created = existing["created_at"] if existing else now()
            db.execute(
                """INSERT OR REPLACE INTO memories VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    memory_id,
                    key,
                    text,
                    category,
                    source,
                    1.0,
                    3,
                    int(cloud_allowed),
                    created,
                    now(),
                    None,
                ),
            )
            db.execute("DELETE FROM memory_search WHERE id=?", (memory_id,))
            db.execute("INSERT INTO memory_search VALUES(?,?)", (memory_id, text))
        return memory_id

    def memories(self):
        with self.connect() as db:
            return [
                dict(row) for row in db.execute("SELECT * FROM memories ORDER BY updated_at DESC")
            ]

    def search(self, text, cloud=False, limit=3):
        words = [
            word
            for word in re.findall(r"\w+", text.lower(), flags=re.UNICODE)
            if word not in MEMORY_STOP_WORDS
        ][:30]
        if not words:
            return []
        query = " OR ".join('"' + word + '"' for word in words)
        with self.connect() as db:
            rows = db.execute(
                """
                SELECT m.* FROM memory_search s JOIN memories m ON m.id=s.id
                WHERE memory_search MATCH ? AND (?=0 OR m.cloud_allowed=1)
                  AND (m.expires_at IS NULL OR m.expires_at>?)
                ORDER BY rank LIMIT ?
            """,
                (query, int(cloud), now(), limit),
            )
            return [dict(row) for row in rows]

    def forget(self, memory_id):
        with self.connect() as db:
            memory = db.execute("SELECT key FROM memories WHERE id=?", (memory_id,)).fetchone()
            if memory and (memory["key"] or "").startswith("learned:"):
                latest = db.execute("SELECT COALESCE(MAX(id),0) FROM user_observations").fetchone()[
                    0
                ]
                db.execute(
                    "INSERT OR REPLACE INTO forgotten_slots VALUES(?,?)", (memory["key"], latest)
                )
            evidence = db.execute(
                "SELECT * FROM memory_evidence WHERE memory_id=?", (memory_id,)
            ).fetchone()
            if evidence:
                import hashlib

                digest = hashlib.sha256(
                    f"{evidence['observation_id']}:{evidence['quote']}".encode()
                ).hexdigest()
                db.execute("INSERT OR IGNORE INTO forgotten_evidence VALUES(?)", (digest,))
            result = db.execute("DELETE FROM memories WHERE id=?", (memory_id,))
            db.execute("DELETE FROM memory_search WHERE id=?", (memory_id,))
            db.execute("DELETE FROM memory_evidence WHERE memory_id=?", (memory_id,))
            return result.rowcount > 0

    def audit(self, action, outcome):
        with self.connect() as db:
            db.execute(
                "INSERT INTO audit(action,outcome,created_at) VALUES(?,?,?)",
                (action, outcome, now()),
            )

    def record_outcome(self, session, request, status, detail=""):
        with self.connect() as db:
            db.execute(
                "INSERT INTO turn_outcomes(session_id,request,status,detail,created_at) VALUES(?,?,?,?,?)",
                (session, request, status, detail, now()),
            )

    def backup(self, destination: Path):
        with self.connect() as source, sqlite3.connect(destination) as target:
            source.backup(target)

    def save_task(self, model, task, result):
        task_id = str(uuid4())
        with self.connect() as db:
            db.execute(
                "INSERT INTO task_results VALUES(?,?,?,?,?)", (task_id, model, task, result, now())
            )
        return task_id

    def prune_transcripts(self, days):
        """Expire inactive transcripts, summaries and task results; keep selected memories."""
        cutoff = (datetime.now(UTC) - timedelta(days=days)).isoformat()
        with self.connect() as db:
            db.execute(
                "DELETE FROM sessions WHERE id IN (SELECT session_id FROM turns "
                "GROUP BY session_id HAVING MAX(created_at) < ?) "
                "AND id NOT IN (SELECT session_id FROM conversation_reviews WHERE status='pending')",
                (cutoff,),
            )
            db.execute("DELETE FROM turns WHERE session_id NOT IN (SELECT id FROM sessions)")
            db.execute(
                "DELETE FROM conversation_summary_search "
                "WHERE session_id NOT IN (SELECT id FROM sessions)"
            )
            db.execute(
                "DELETE FROM sessions WHERE id IN (SELECT session_id FROM user_observations "
                "GROUP BY session_id HAVING MAX(created_at) < ?) "
                "AND id NOT IN (SELECT session_id FROM conversation_reviews WHERE status='pending') "
                "AND id NOT IN (SELECT session_id FROM turns WHERE created_at >= ?)",
                (cutoff, cutoff),
            )
            db.execute("DELETE FROM turns WHERE session_id NOT IN (SELECT id FROM sessions)")
            db.execute(
                "DELETE FROM user_observations WHERE session_id NOT IN (SELECT id FROM sessions)"
            )
            db.execute(
                "DELETE FROM conversation_reviews WHERE session_id NOT IN (SELECT id FROM sessions)"
            )
            db.execute("DELETE FROM task_results WHERE created_at < ?", (cutoff,))
            db.execute("DELETE FROM turn_outcomes WHERE created_at < ?", (cutoff,))

    def save_email(self, token, session, path, digest, expires):
        with self.connect() as db:
            db.execute(
                "UPDATE email_approvals SET status='superseded' WHERE session_id=? AND status='pending'",
                (session,),
            )
            db.execute(
                "INSERT INTO email_approvals VALUES(?,?,?,?,?,'pending')",
                (token, session, path, digest, expires),
            )

    def pending_email(self, session):
        with self.connect() as db:
            row = db.execute(
                "SELECT * FROM email_approvals WHERE session_id=? AND status='pending' ORDER BY rowid DESC LIMIT 1",
                (session,),
            ).fetchone()
            return dict(row) if row else None

    def cancel_email(self, session):
        with self.connect() as db:
            db.execute(
                "UPDATE email_approvals SET status='cancelled' WHERE session_id=? AND status='pending'",
                (session,),
            )

    def consume_email(self, token, session):
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT * FROM email_approvals WHERE token=? AND session_id=? AND status='pending'",
                (token, session),
            ).fetchone()
            if row:
                db.execute("UPDATE email_approvals SET status='used' WHERE token=?", (token,))
                return dict(row)
            return None
