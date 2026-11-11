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
    }


def list_tasks(include_completed: bool = False) -> list[dict]:
    with _lock, closing(_db()) as conn, conn:  # close the file handle; commit the transaction
        sql = "SELECT * FROM tasks" + ("" if include_completed else " WHERE completed = 0") + " ORDER BY id DESC LIMIT 500"
        return [_row(r) for r in conn.execute(sql)]


def create_task(title: str, due: str | None = None, notes: str = "", message_id: str | None = None,
                importance: str = "normal") -> dict:
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
    with _lock, closing(_db()) as conn, conn:  # close the file handle; commit the transaction
        cur = conn.execute(
            "INSERT INTO tasks (title, due, notes, importance, message_id, created) VALUES (?, ?, ?, ?, ?, ?)",
            (title, due or None, (notes or "").strip()[:4000], importance, message_id,
             datetime.now().astimezone().isoformat(timespec="seconds")),
        )
        return _row(conn.execute("SELECT * FROM tasks WHERE id = ?", (cur.lastrowid,)).fetchone())


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
