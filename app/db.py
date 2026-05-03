from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from .config import settings


SCHEMA_SQL = """
PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS groups (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    group_name TEXT NOT NULL UNIQUE,
    description TEXT,
    timezone TEXT NOT NULL DEFAULT 'Asia/Bangkok',
    source_owner TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    display_name TEXT NOT NULL,
    normalized_name TEXT NOT NULL UNIQUE,
    phone_number TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS import_batches (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    group_id INTEGER NOT NULL,
    file_name TEXT NOT NULL,
    file_sha1 TEXT NOT NULL,
    imported_at TEXT NOT NULL,
    total_lines INTEGER NOT NULL,
    parsed_messages INTEGER NOT NULL,
    new_messages INTEGER NOT NULL,
    duplicate_messages INTEGER NOT NULL,
    FOREIGN KEY (group_id) REFERENCES groups(id)
);

CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    group_id INTEGER NOT NULL,
    sender_id INTEGER,
    batch_id INTEGER NOT NULL,
    sent_at TEXT NOT NULL,
    message_type TEXT NOT NULL,
    content_raw TEXT NOT NULL,
    content_normalized TEXT NOT NULL,
    content_th TEXT,
    media_path TEXT,
    source_hash TEXT NOT NULL UNIQUE,
    source_line_start INTEGER NOT NULL,
    source_line_end INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY (group_id) REFERENCES groups(id),
    FOREIGN KEY (sender_id) REFERENCES users(id),
    FOREIGN KEY (batch_id) REFERENCES import_batches(id)
);

CREATE INDEX IF NOT EXISTS idx_messages_group_sent_at ON messages(group_id, sent_at DESC);
CREATE INDEX IF NOT EXISTS idx_messages_sender_sent_at ON messages(sender_id, sent_at DESC);
CREATE INDEX IF NOT EXISTS idx_messages_content_normalized ON messages(content_normalized);

CREATE VIRTUAL TABLE IF NOT EXISTS messages_fts USING fts5(
    content_raw,
    content_normalized,
    content_id UNINDEXED,
    tokenize="unicode61 remove_diacritics 1"
);

CREATE TRIGGER IF NOT EXISTS messages_ai AFTER INSERT ON messages BEGIN
  INSERT INTO messages_fts(rowid, content_raw, content_normalized, content_id)
  VALUES (new.id, new.content_raw, new.content_normalized, new.id);
END;

CREATE TRIGGER IF NOT EXISTS messages_ad AFTER DELETE ON messages BEGIN
  INSERT INTO messages_fts(messages_fts, rowid, content_raw, content_normalized, content_id)
  VALUES ('delete', old.id, old.content_raw, old.content_normalized, old.id);
END;

CREATE TRIGGER IF NOT EXISTS messages_au AFTER UPDATE ON messages BEGIN
  INSERT INTO messages_fts(messages_fts, rowid, content_raw, content_normalized, content_id)
  VALUES ('delete', old.id, old.content_raw, old.content_normalized, old.id);
  INSERT INTO messages_fts(rowid, content_raw, content_normalized, content_id)
  VALUES (new.id, new.content_raw, new.content_normalized, new.id);
END;
"""


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def get_connection() -> sqlite3.Connection:
    db_path = Path(settings.db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    with get_connection() as conn:
        conn.executescript(SCHEMA_SQL)
        conn.commit()
