"""
Dashboard task list, stored locally in %LOCALAPPDATA%\\OutlookDashboard\\tasks.db (SQLite).

Holds only what you approve as a task: title, due date, optional note, importance and the id of
the email it came from. Email bodies are never stored.
"""

from __future__ import annotations

import sqlite3
import threading
from contextlib import closing
from datetime import datetime

import config
from errors import BadRequest, NotFound

DB_FILE = config.DATA_DIR / "tasks.db"
_lock = threading.Lock()


def _db() -> sqlite3.Connection:
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    conn.execute(
        """CREATE TABLE IF NOT EXISTS tasks (
               id INTEGER PRIMARY KEY AUTOINCREMENT,
               title TEXT NOT NULL,
               due TEXT,
               notes TEXT NOT NULL DEFAULT '',
               importance TEXT NOT NULL DEFAULT 'normal',
               message_id TEXT,
               completed INTEGER NOT NULL DEFAULT 0,
               created TEXT NOT NULL,
               completed_at TEXT
           )"""
    )
    # Who gave / received the task (added later; older databases are upgraded in place).
    cols = {r[1] for r in conn.execute("PRAGMA table_info(tasks)")}
    if "direction" not in cols:
        conn.execute("ALTER TABLE tasks ADD COLUMN direction TEXT NOT NULL DEFAULT 'mine'")
        conn.execute("ALTER TABLE tasks ADD COLUMN person TEXT NOT NULL DEFAULT ''")
        conn.execute("ALTER TABLE tasks ADD COLUMN person_address TEXT NOT NULL DEFAULT ''")
        # Tasks added from an email were requests from someone else.
        conn.execute("UPDATE tasks SET direction = 'received' WHERE message_id IS NOT NULL")
        conn.commit()
    if "source_key" not in cols:
        # The sent email a Given task came from (its Message-ID), so the Sent Items scan never adds it twice.
        conn.execute("ALTER TABLE tasks ADD COLUMN source_key TEXT")
        conn.commit()
    return conn


def _row(r: sqlite3.Row) -> dict:
    return {
        "id": str(r["id"]),
        "title": r["title"],
        "completed": bool(r["completed"]),
        "due": r["due"],
        "importance": r["importance"],
        "notes": r["notes"],
        "createdDateTime": r["created"],
        "messageId": r["message_id"],
        "direction": r["direction"],  # mine | given (you assigned it) | received (someone asked you)
        "person": r["person"],  # given: who it was assigned to; received: who asked
        "personAddress": r["person_address"],
    }


def list_tasks(include_completed: bool = False) -> list[dict]:
    with _lock, closing(_db()) as conn, conn:  # close the file handle; commit the transaction
        sql = "SELECT * FROM tasks" + ("" if include_completed else " WHERE completed = 0") + " ORDER BY id DESC LIMIT 500"
        return [_row(r) for r in conn.execute(sql)]


DIRECTIONS = ("mine", "given", "received")


def create_task(title: str, due: str | None = None, notes: str = "", message_id: str | None = None,
                importance: str = "normal", direction: str | None = None, person: str = "",
                person_address: str = "", source_key: str | None = None) -> dict:
    title = (title or "").strip()[:255]
    if not title:
        raise BadRequest("A task needs a title.")
    if due:
        try:
            datetime.strptime(due, "%Y-%m-%d")
        except ValueError:
            raise BadRequest("Invalid due date. Use YYYY-MM-DD.") from None
    if importance not in ("low", "normal", "high"):
        importance = "normal"
    if direction not in DIRECTIONS:
        direction = "received" if message_id else "mine"
    with _lock, closing(_db()) as conn, conn:  # close the file handle; commit the transaction
        cur = conn.execute(
            "INSERT INTO tasks (title, due, notes, importance, message_id, created, direction, person, person_address, "
            "source_key) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (title, due or None, (notes or "").strip()[:4000], importance, message_id,
             datetime.now().astimezone().isoformat(timespec="seconds"), direction,
             (person or "").strip()[:200], (person_address or "").strip()[:320], source_key or None),
        )
        return _row(conn.execute("SELECT * FROM tasks WHERE id = ?", (cur.lastrowid,)).fetchone())


def source_keys() -> set[str]:
    """Sent emails already turned into Given tasks (any task, open or completed)."""
    with _lock, closing(_db()) as conn, conn:
        return {r[0] for r in conn.execute("SELECT source_key FROM tasks WHERE source_key IS NOT NULL")}


def set_task_completed(task_id: str, completed: bool) -> dict:
    if not str(task_id).isdigit():
        raise BadRequest("Invalid task id.")
    with _lock, closing(_db()) as conn, conn:  # close the file handle; commit the transaction
        cur = conn.execute(
            "UPDATE tasks SET completed = ?, completed_at = ? WHERE id = ?",
            (1 if completed else 0, datetime.now().astimezone().isoformat(timespec="seconds") if completed else None, int(task_id)),
        )
        if not cur.rowcount:
            raise NotFound("That task no longer exists.")
        return _row(conn.execute("SELECT * FROM tasks WHERE id = ?", (int(task_id),)).fetchone())
