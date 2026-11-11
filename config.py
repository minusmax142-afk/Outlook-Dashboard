"""
Settings. Defaults work out of the box. To change them, create `settings.json` next to app.py:

    { "backend": "imap" }

backend:
  "imap"    - (default) connect directly to your mail server over IMAP/SMTP, e.g.
              mail.indigoheights.com. Works with New Outlook, classic Outlook, or no Outlook app.
              Your email address, password and server are entered in the dashboard's sign-in form.
  "outlook" - classic Outlook desktop app on this PC (COM automation). No sign-in, but classic
              Outlook must be running.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent

# Per-user data folder: account settings (no password), task list, task-suggestion keys.
DATA_DIR = Path(os.environ.get("LOCALAPPDATA") or Path.home()) / "OutlookDashboard"


def _load() -> dict:
    path = BASE_DIR / "settings.json"
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))  # tolerate a BOM (Notepad/PowerShell)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        print("WARNING: settings.json could not be read; using defaults.")
        return {}


_settings = _load()

BACKEND = str(_settings.get("backend", "imap")).strip().lower()
if BACKEND not in ("imap", "outlook"):
    print(f"WARNING: unknown backend {BACKEND!r} in settings.json; using 'imap'.")
    BACKEND = "imap"
