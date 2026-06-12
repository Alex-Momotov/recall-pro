"""SQLite storage. Single local file, source of truth.

Dates are stored as ISO strings (YYYY-MM-DD). The UNIQUE(item_id, due_on)
constraint on revisions makes completion idempotent: a revision per item per
due date counts once, even if the daemon reprocesses a checked task.
"""
from __future__ import annotations

import sqlite3
from datetime import date, timedelta
from pathlib import Path

from . import config, scheduler

SCHEMA = """
CREATE TABLE IF NOT EXISTS items (
    id          INTEGER PRIMARY KEY,
    title       TEXT NOT NULL,
    learned_on  TEXT NOT NULL,
    rung        INTEGER NOT NULL DEFAULT 0,
    next_due    TEXT NOT NULL,
    gtask_id    TEXT,
    created_at  TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);
CREATE TABLE IF NOT EXISTS subpoints (
    id       INTEGER PRIMARY KEY,
    item_id  INTEGER NOT NULL REFERENCES items(id) ON DELETE CASCADE,
    position INTEGER NOT NULL,
    depth    INTEGER NOT NULL,
    text     TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS revisions (
    id           INTEGER PRIMARY KEY,
    item_id      INTEGER NOT NULL REFERENCES items(id) ON DELETE CASCADE,
    due_on       TEXT NOT NULL,
    completed_on TEXT NOT NULL,
    UNIQUE (item_id, due_on)
);
CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT
);
"""


def connect(path: Path | str | None = None) -> sqlite3.Connection:
    if path is None:
        config.migrate_legacy_data()
        config.RECALLPRO_DIR.mkdir(parents=True, exist_ok=True)
        path = config.DB_PATH
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(SCHEMA)
    return conn


# --- items ---------------------------------------------------------------

def add_item(conn, title: str, learned_on: date,
             subpoints: list[tuple[int, str]] | None = None) -> int:
    next_due = scheduler.first_due(learned_on)
    cur = conn.execute(
        "INSERT INTO items (title, learned_on, next_due) VALUES (?, ?, ?)",
        (title, learned_on.isoformat(), next_due.isoformat()),
    )
    item_id = cur.lastrowid
    if subpoints:
        set_subpoints(conn, item_id, subpoints)
    conn.commit()
    return item_id


def get_item(conn, item_id: int) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM items WHERE id = ?", (item_id,)).fetchone()


def list_items(conn) -> list[sqlite3.Row]:
    return conn.execute("SELECT * FROM items ORDER BY next_due, id").fetchall()


def due_items(conn, today: date) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM items WHERE next_due <= ? ORDER BY next_due, id",
        (today.isoformat(),),
    ).fetchall()


def find_by_title_exact(conn, title: str) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM items WHERE title = ? COLLATE NOCASE", (title,)
    ).fetchall()


def find_by_title_substring(conn, fragment: str) -> list[sqlite3.Row]:
    pattern = f"%{fragment}%"
    return conn.execute(
        "SELECT * FROM items WHERE title LIKE ? ORDER BY id", (pattern,)
    ).fetchall()


def update_title(conn, item_id: int, title: str) -> None:
    conn.execute("UPDATE items SET title = ? WHERE id = ?", (title, item_id))
    conn.commit()


def set_gtask_id(conn, item_id: int, gtask_id: str | None) -> None:
    conn.execute("UPDATE items SET gtask_id = ? WHERE id = ?", (gtask_id, item_id))
    conn.commit()


def delete_item(conn, item_id: int) -> None:
    conn.execute("DELETE FROM items WHERE id = ?", (item_id,))
    conn.commit()


# --- subpoints -----------------------------------------------------------

def set_subpoints(conn, item_id: int, subpoints: list[tuple[int, str]]) -> None:
    """Replace the item's outline. subpoints = ordered [(depth, text), ...]."""
    conn.execute("DELETE FROM subpoints WHERE item_id = ?", (item_id,))
    conn.executemany(
        "INSERT INTO subpoints (item_id, position, depth, text) VALUES (?, ?, ?, ?)",
        [(item_id, pos, depth, text) for pos, (depth, text) in enumerate(subpoints)],
    )
    conn.commit()


def get_subpoints(conn, item_id: int) -> list[tuple[int, str]]:
    rows = conn.execute(
        "SELECT depth, text FROM subpoints WHERE item_id = ? ORDER BY position",
        (item_id,),
    ).fetchall()
    return [(r["depth"], r["text"]) for r in rows]


# --- revisions / completion ----------------------------------------------

def complete_revision(conn, item: sqlite3.Row, completed_on: date) -> bool:
    """Record a completed revision and advance the ladder.

    Returns False (no-op) if this due date was already completed — keeps the
    daemon idempotent across crashes/reprocessing.
    """
    try:
        conn.execute(
            "INSERT INTO revisions (item_id, due_on, completed_on) VALUES (?, ?, ?)",
            (item["id"], item["next_due"], completed_on.isoformat()),
        )
    except sqlite3.IntegrityError:
        return False
    new_rung = item["rung"] + 1
    next_due = scheduler.next_due_after_completion(new_rung, completed_on)
    conn.execute(
        "UPDATE items SET rung = ?, next_due = ?, gtask_id = NULL WHERE id = ?",
        (new_rung, next_due.isoformat(), item["id"]),
    )
    conn.commit()
    return True


def revision_history(conn, item_id: int) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM revisions WHERE item_id = ? ORDER BY completed_on",
        (item_id,),
    ).fetchall()


# --- meta ------------------------------------------------------------------

def meta_get(conn, key: str) -> str | None:
    row = conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else None


def meta_set(conn, key: str, value: str) -> None:
    conn.execute(
        "INSERT INTO meta (key, value) VALUES (?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, value),
    )
    conn.commit()
