"""SQLite application state: users, login sessions and the incident list shown in the UI.

This is NOT the agent's memory. Hindsight is the only memory the agent recalls from; these tables
back authentication, incident IDs, the history view and the status of background learning.
Every incident row has an owner (user_id) and every query filters by it.
"""

import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import Any

from app.config import get_settings

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id TEXT PRIMARY KEY,
    username TEXT NOT NULL UNIQUE COLLATE NOCASE,
    password_hash TEXT NOT NULL,
    hindsight_bank_id TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL
);
-- Only a SHA-256 hash of each bearer token is stored, so a leaked database yields no usable sessions.
CREATE TABLE IF NOT EXISTS auth_sessions (
    token_hash TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(id),
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS incidents (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    service TEXT NOT NULL,
    environment TEXT NOT NULL,
    severity TEXT NOT NULL,
    symptoms TEXT NOT NULL,
    error_logs TEXT NOT NULL,
    recent_changes TEXT NOT NULL,
    created_by TEXT NOT NULL,
    created_at TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'open',
    analysis_json TEXT,
    recall_json TEXT,
    groq_prompt TEXT,
    groq_model TEXT,
    root_cause TEXT,
    solution TEXT,
    outcome TEXT,
    failed_approaches TEXT,
    notes TEXT,
    resolved_at TEXT,
    retained_in_hindsight INTEGER NOT NULL DEFAULT 0,
    user_id TEXT REFERENCES users(id),
    learning_json TEXT
);
"""


def now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


@contextmanager
def connect() -> Iterator[sqlite3.Connection]:
    conn = sqlite3.connect(get_settings().database_path, timeout=5.0)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
    finally:
        conn.close()


def _add_column_if_missing(conn: sqlite3.Connection, table: str, column: str, decl: str) -> None:
    cols = {r["name"] for r in conn.execute(f"PRAGMA table_info({table})")}
    if column not in cols:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {decl}")


def init_db() -> None:
    with connect() as conn:
        conn.execute("PRAGMA journal_mode=WAL")  # background learning writes while requests read
        conn.executescript(SCHEMA)
        # Migrations for databases created by earlier versions.
        _add_column_if_missing(conn, "incidents", "user_id", "TEXT REFERENCES users(id)")
        _add_column_if_missing(conn, "incidents", "learning_json", "TEXT")
        # The old table stored bearer tokens in plaintext: drop it, invalidating every old token.
        conn.execute("DROP TABLE IF EXISTS sessions")
        conn.execute("DELETE FROM auth_sessions WHERE expires_at < ?", (now_iso(),))
        conn.execute("CREATE INDEX IF NOT EXISTS idx_incidents_user ON incidents(user_id, created_at)")


def _loads(raw: str | None) -> Any:
    return json.loads(raw) if raw else None


def row_to_incident(row: sqlite3.Row) -> dict[str, Any]:
    data = dict(row)
    data["analysis"] = _loads(data.pop("analysis_json"))
    data["recall"] = _loads(data.pop("recall_json"))
    data["learning"] = _loads(data.pop("learning_json", None))
    data["retained_in_hindsight"] = bool(data["retained_in_hindsight"])
    return data
