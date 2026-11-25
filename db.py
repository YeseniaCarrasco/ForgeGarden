"""SQLite storage shared by the app's features."""
import sqlite3
from datetime import date

from flask import current_app, g

SCHEMA = """
-- Accounts. Only Werkzeug password hashes are stored, never plain text.
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY,
    username TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- One row per compost route day; UNIQUE route_date means one volunteer per day.
CREATE TABLE IF NOT EXISTS compost_signups (
    id INTEGER PRIMARY KEY,
    route_date TEXT NOT NULL UNIQUE,
    username TEXT NOT NULL,
    training_date TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- Plant Help board.
CREATE TABLE IF NOT EXISTS questions (
    id INTEGER PRIMARY KEY,
    username TEXT NOT NULL,
    topic TEXT NOT NULL,
    title TEXT NOT NULL,
    body TEXT NOT NULL,
    helpful_answer_id INTEGER,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS answers (
    id INTEGER PRIMARY KEY,
    question_id INTEGER NOT NULL REFERENCES questions(id) ON DELETE CASCADE,
    username TEXT NOT NULL,
    body TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- Garden Journal (posts by the garden manager).
CREATE TABLE IF NOT EXISTS journal_posts (
    id INTEGER PRIMARY KEY,
    username TEXT NOT NULL,
    kind TEXT NOT NULL,
    title TEXT NOT NULL,
    body TEXT NOT NULL,
    link_url TEXT,
    link_title TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT
);

-- Plant Doctor: the AI's first take on a Plant Help question.
CREATE TABLE IF NOT EXISTS plant_doctor (
    question_id INTEGER PRIMARY KEY REFERENCES questions(id) ON DELETE CASCADE,
    topic TEXT NOT NULL,
    likely_issues TEXT NOT NULL,  -- JSON list of strings
    organic_treatment TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- Farmstand: what's harvested for a given Friday, and produce box reservations.
CREATE TABLE IF NOT EXISTS farmstand_days (
    farmstand_date TEXT PRIMARY KEY,
    boxes INTEGER NOT NULL DEFAULT 0,
    note TEXT
);
CREATE TABLE IF NOT EXISTS harvest_items (
    id INTEGER PRIMARY KEY,
    farmstand_date TEXT NOT NULL,
    name TEXT NOT NULL,
    note TEXT,
    photo_key TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS box_reservations (
    id INTEGER PRIMARY KEY,
    farmstand_date TEXT NOT NULL,
    username TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (farmstand_date, username)
);

-- Garden Helper chatbot conversations.
CREATE TABLE IF NOT EXISTS chat_messages (
    id INTEGER PRIMARY KEY,
    conversation_id TEXT NOT NULL,
    username TEXT NOT NULL,
    role TEXT NOT NULL,  -- 'user' or 'assistant'
    content TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS chat_messages_conversation ON chat_messages (conversation_id);
"""

# Columns added after the first release. Older databases get them on first use.
ADDED_COLUMNS = [
    ("questions", "photo_key", "TEXT"),
    ("journal_posts", "photo_key", "TEXT"),
]
_migrated = set()


def _add_missing_columns(db):
    for table, column, kind in ADDED_COLUMNS:
        existing = {row[1] for row in db.execute(f"PRAGMA table_info({table})")}
        if column not in existing:
            db.execute(f"ALTER TABLE {table} ADD COLUMN {column} {kind}")
    db.commit()


def get_db():
    """Open (and lazily create) the SQLite database for this request."""
    if "db" not in g:
        path = current_app.config["DATABASE"]
        g.db = sqlite3.connect(path)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
        g.db.executescript(SCHEMA)
        if path not in _migrated:
            _add_missing_columns(g.db)
            _migrated.add(path)
    return g.db


def close_db(_exc=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def current_date():
    """Today's date; tests can pin it with the TODAY config value."""
    return current_app.config.get("TODAY") or date.today()
