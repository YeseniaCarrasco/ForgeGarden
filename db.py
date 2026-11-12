"""SQLite storage shared by the app's features."""
import sqlite3
from datetime import date

from flask import current_app, g

SCHEMA = """
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
"""


def get_db():
    """Open (and lazily create) the SQLite database for this request."""
    if "db" not in g:
        g.db = sqlite3.connect(current_app.config["DATABASE"])
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
        g.db.executescript(SCHEMA)
    return g.db


def close_db(_exc=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def current_date():
    """Today's date; tests can pin it with the TODAY config value."""
    return current_app.config.get("TODAY") or date.today()
