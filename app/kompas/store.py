"""Trwały zapis przestrzeni roboczych (workspace) — jeden dokument JSON na przestrzeń.

Każda przeglądarka demo dostaje własną przestrzeń (nagłówek `X-Kompas-Workspace`), więc jurorzy
nie nadpisują sobie danych. Produkcyjnie: Postgres (`DATABASE_URL`); lokalnie i awaryjnie: SQLite.
"""
from __future__ import annotations

import sqlite3
import threading
from functools import lru_cache
from pathlib import Path
from typing import Protocol

from app.core.config import settings


class WorkspaceStore(Protocol):
    kind: str

    def load(self, workspace_id: str) -> str | None: ...

    def save(self, workspace_id: str, state_json: str) -> None: ...


class SqliteStore:
    kind = "sqlite"

    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(path), check_same_thread=False)
        self._lock = threading.Lock()
        with self._lock:
            self._conn.execute(
                "CREATE TABLE IF NOT EXISTS kompas_workspaces (id TEXT PRIMARY KEY, state TEXT NOT NULL, "
                "updated_at TEXT DEFAULT CURRENT_TIMESTAMP)")
            self._conn.commit()

    def load(self, workspace_id: str) -> str | None:
        with self._lock:
            row = self._conn.execute("SELECT state FROM kompas_workspaces WHERE id = ?", (workspace_id,)).fetchone()
        return row[0] if row else None

    def save(self, workspace_id: str, state_json: str) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO kompas_workspaces (id, state, updated_at) VALUES (?, ?, CURRENT_TIMESTAMP) "
                "ON CONFLICT(id) DO UPDATE SET state = excluded.state, updated_at = CURRENT_TIMESTAMP",
                (workspace_id, state_json))
            self._conn.commit()


class PostgresStore:
    kind = "postgres"

    def __init__(self, url: str):
        import psycopg
        self._psycopg = psycopg
        self._url = url
        with psycopg.connect(url, autocommit=True) as conn:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS kompas_workspaces (id TEXT PRIMARY KEY, state JSONB NOT NULL, "
                "updated_at TIMESTAMPTZ NOT NULL DEFAULT now())")

    def load(self, workspace_id: str) -> str | None:
        with self._psycopg.connect(self._url, autocommit=True) as conn:
            row = conn.execute("SELECT state::text FROM kompas_workspaces WHERE id = %s", (workspace_id,)).fetchone()
        return row[0] if row else None

    def save(self, workspace_id: str, state_json: str) -> None:
        with self._psycopg.connect(self._url, autocommit=True) as conn:
            conn.execute(
                "INSERT INTO kompas_workspaces (id, state, updated_at) VALUES (%s, %s::jsonb, now()) "
                "ON CONFLICT (id) DO UPDATE SET state = excluded.state, updated_at = now()",
                (workspace_id, state_json))


@lru_cache(maxsize=1)
def get_store() -> WorkspaceStore:
    if settings.database_url:
        try:
            return PostgresStore(settings.database_url)
        except Exception as e:  # baza niedostępna -> demo działa dalej na SQLite
            print(f"[store] Postgres niedostępny, używam SQLite: {e!r}")
    return SqliteStore(settings.workspaces_db)
