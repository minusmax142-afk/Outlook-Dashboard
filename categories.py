"""
Colour categories (like Outlook's): names and colours are kept in categories.json on this PC;
which emails have which category is stored on the mail server as IMAP keywords, so it follows
the email between folders and is the same on every PC that runs this dashboard.
"""

from __future__ import annotations

import json
import os
import re
import threading
import uuid

import config
from errors import BadRequest, NotFound

COLORS = ["red", "orange", "yellow", "green", "teal", "blue", "purple", "pink", "gray"]
DEFAULTS = [("Urgent", "red"), ("Follow up", "orange"), ("Waiting", "yellow"),
            ("Done", "green"), ("FYI", "blue"), ("Personal", "purple")]
MAX_CATEGORIES = 50
NAME_MAX = 40

_PATH = os.path.join(config.DATA_DIR, "categories.json")
_lock = threading.Lock()
_cache: list[dict] | None = None


def _keyword_for(name: str, taken: set[str]) -> str:
    """IMAP keywords must be plain ASCII atoms: '$Cat_Follow_up'. Unique, never reused."""
    base = re.sub(r"[^A-Za-z0-9]+", "_", name).strip("_")[:30] or uuid.uuid4().hex[:8]
    kw = f"$Cat_{base}"
    n = 2
    while kw.lower() in taken:
        kw = f"$Cat_{base}_{n}"
        n += 1
    return kw


def _load() -> list[dict]:
    global _cache
    if _cache is None:
        try:
            with open(_PATH, encoding="utf-8") as fh:
                data = json.load(fh)
            items = data.get("categories", []) if isinstance(data, dict) else []
            _cache = [c for c in items if isinstance(c, dict) and c.get("name") and c.get("keyword")]
            retired = data.get("retired", []) if isinstance(data, dict) else []
            _retired.update(str(k).lower() for k in retired)
        except FileNotFoundError:
            _cache = []
            taken: set[str] = set()
            for name, color in DEFAULTS:
                kw = _keyword_for(name, taken)
                taken.add(kw.lower())
                _cache.append({"name": name, "color": color, "keyword": kw})
            _save()
        except (OSError, ValueError):
            _cache = []
    return _cache


_retired: set[str] = set()  # keywords of deleted categories: never handed out again


def _save() -> None:
    os.makedirs(config.DATA_DIR, exist_ok=True)
    tmp = _PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump({"categories": _cache, "retired": sorted(_retired)}, fh, ensure_ascii=False, indent=1)
    os.replace(tmp, _PATH)


def list_categories() -> list[dict]:
    with _lock:
        return [dict(c) for c in _load()]


def keyword_map() -> dict[str, dict]:
    """lower-case keyword -> category"""
    with _lock:
        return {c["keyword"].lower(): c for c in _load()}


def by_name(name: str) -> dict:
    with _lock:
        for c in _load():
            if c["name"].lower() == (name or "").strip().lower():
                return dict(c)
    raise NotFound("That category doesn't exist any more.")


def _check(name: str, color: str) -> tuple[str, str]:
    name = re.sub(r"\s+", " ", (name or "")).strip()
    if not name:
        raise BadRequest("Enter a category name.")
    if len(name) > NAME_MAX:
        raise BadRequest(f"Category names can be at most {NAME_MAX} characters.")
    if color not in COLORS:
        raise BadRequest("Pick one of the colours.")
    return name, color


def create(name: str, color: str) -> dict:
    name, color = _check(name, color)
    with _lock:
        cats = _load()
        if any(c["name"].lower() == name.lower() for c in cats):
            raise BadRequest("A category with that name already exists.")
        if len(cats) >= MAX_CATEGORIES:
            raise BadRequest(f"You can have at most {MAX_CATEGORIES} categories.")
        taken = {c["keyword"].lower() for c in cats} | _retired
        cat = {"name": name, "color": color, "keyword": _keyword_for(name, taken)}
        cats.append(cat)
        _save()
        return dict(cat)


def update(keyword: str, name: str, color: str) -> dict:
    """Rename / recolour. The keyword stays the same, so emails keep their category."""
    name, color = _check(name, color)
    with _lock:
        cats = _load()
        target = next((c for c in cats if c["keyword"].lower() == (keyword or "").lower()), None)
        if target is None:
            raise NotFound("That category doesn't exist any more.")
        if any(c is not target and c["name"].lower() == name.lower() for c in cats):
            raise BadRequest("A category with that name already exists.")
        target.update(name=name, color=color)
        _save()
        return dict(target)


def delete(keyword: str) -> dict:
    """Removes the category from the list. Emails keep the keyword on the server, but the
    dashboard no longer shows it (the keyword is never reused for a new category)."""
    with _lock:
        cats = _load()
        target = next((c for c in cats if c["keyword"].lower() == (keyword or "").lower()), None)
        if target is None:
            raise NotFound("That category doesn't exist any more.")
        cats.remove(target)
        _retired.add(target["keyword"].lower())
        _save()
        return {"deleted": target["keyword"]}
