"""Pamięć czatu: SQLite (sessions, messages). Zwraca ostatnie N wiadomości do condense/generacji."""
from __future__ import annotations
import json
import sqlite3
import time
from contextlib import contextmanager

from app.core.config import settings

DDL = """
CREATE TABLE IF NOT EXISTS sessions (
  session_id TEXT PRIMARY KEY, created_at REAL, context_json TEXT DEFAULT '{}');
CREATE TABLE IF NOT EXISTS messages (
  id INTEGER PRIMARY KEY AUTOINCREMENT, session_id TEXT, role TEXT, content TEXT,
  citations_json TEXT DEFAULT '[]', ts REAL);
CREATE INDEX IF NOT EXISTS ix_messages_session ON messages(session_id, id);
"""


class SessionStore:
    def __init__(self, path=settings.sessions_db):
        self.path = str(path)
        with self._conn() as c:
            c.executescript(DDL)

    @contextmanager
    def _conn(self):
        c = sqlite3.connect(self.path)
        try:
            yield c
            c.commit()
        finally:
            c.close()

    def touch(self, session_id: str, context: dict | None = None) -> None:
        with self._conn() as c:
            c.execute("INSERT OR IGNORE INTO sessions(session_id, created_at) VALUES(?,?)", (session_id, time.time()))
            if context:
                c.execute("UPDATE sessions SET context_json=? WHERE session_id=?", (json.dumps(context, ensure_ascii=False), session_id))

    def add(self, session_id: str, role: str, content: str, citations: list | None = None) -> None:
        with self._conn() as c:
            c.execute("INSERT INTO messages(session_id, role, content, citations_json, ts) VALUES(?,?,?,?,?)",
                      (session_id, role, content, json.dumps(citations or [], ensure_ascii=False), time.time()))

    def history(self, session_id: str, limit: int | None = None) -> list[dict]:
        limit = limit or settings.max_history_messages
        with self._conn() as c:
            rows = c.execute("SELECT role, content FROM messages WHERE session_id=? ORDER BY id DESC LIMIT ?",
                             (session_id, limit)).fetchall()
        return [{"role": r, "content": t} for r, t in reversed(rows)]

    def full(self, session_id: str) -> list[dict]:
        with self._conn() as c:
            rows = c.execute("SELECT role, content, citations_json, ts FROM messages WHERE session_id=? ORDER BY id",
                             (session_id,)).fetchall()
        return [{"role": r, "content": t, "citations": json.loads(cj), "ts": ts} for r, t, cj, ts in rows]

    def delete(self, session_id: str) -> None:
        with self._conn() as c:
            c.execute("DELETE FROM messages WHERE session_id=?", (session_id,))
            c.execute("DELETE FROM sessions WHERE session_id=?", (session_id,))
