"""
People you email, for "Write for me": built from the From/To/Cc headers of your Inbox and Sent
folders (names and addresses only, never email text), plus names you've confirmed before
("qasim" -> qasim@...), which are remembered in %LOCALAPPDATA%\\OutlookDashboard\\contacts.json.
"""

from __future__ import annotations

import json
import re
import threading
import time
from collections import Counter, defaultdict
from email.utils import getaddresses

import config
import writer

_ALIAS_PATH = config.DATA_DIR / "contacts.json"
_lock = threading.Lock()
SKIP = re.compile(r"(?i)^(?:no-?reply|do-?not-?reply|mailer-daemon|postmaster|bounce|notifications?|alerts?)[@+.]|@.*\b(?:noreply|bounce)")


def _load_aliases() -> dict:
    try:
        data = json.loads(_ALIAS_PATH.read_text(encoding="utf-8"))
        return {str(k): str(v) for k, v in data.items()} if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def remember(phrase: str, address: str) -> None:
    key = re.sub(r"\s+", " ", (phrase or "").strip().lower())
    if not key or "@" in key or len(key) > 60 or not address:
        return
    with _lock:
        aliases = _load_aliases()
        if aliases.get(key) == address:
            return
        aliases[key] = address
        config.DATA_DIR.mkdir(parents=True, exist_ok=True)
        tmp = _ALIAS_PATH.with_suffix(".tmp")
        tmp.write_text(json.dumps(aliases, indent=1, ensure_ascii=False), encoding="utf-8")
        tmp.replace(_ALIAS_PATH)


def build(header_rows: list[tuple[str, dict]], me: str) -> dict:
    """header_rows: [(folder kind 'inbox'|'sent', {'From':..,'To':..,'Cc':..})] -> {address: {...}}"""
    weights = {("inbox", "From"): 2, ("sent", "To"): 3, ("sent", "Cc"): 1, ("inbox", "Cc"): 1, ("inbox", "To"): 1}
    score: Counter = Counter()
    names: dict[str, Counter] = defaultdict(Counter)
    my_names: Counter = Counter()
    for kind, h in header_rows:
        for field in ("From", "To", "Cc"):
            for name, addr in getaddresses([h.get(field) or ""]):
                addr = (addr or "").strip().lower()
                name = re.sub(r"\s+", " ", (name or "").strip().strip("'\""))
                if not addr or "@" not in addr:
                    continue
                if addr == me:
                    if name and field == "From":
                        my_names[name] += 1
                    continue
                if SKIP.search(addr):
                    continue
                score[addr] += weights.get((kind, field), 1)
                if name and "@" not in name:
                    names[addr][name] += 1
    people = {a: {"address": a, "name": (names[a].most_common(1)[0][0] if names[a] else ""), "count": n}
              for a, n in score.items()}
    return {"people": people, "myName": my_names.most_common(1)[0][0] if my_names else ""}


def _tokens(text: str) -> list[str]:
    return [t for t in re.findall(r"[a-z0-9]+", (text or "").lower()) if t]


def match(phrase: str, people: dict) -> list[dict]:
    """Best contacts for 'qasim', 'muhammad qasim', 'accounts', 'kamran driver' (best first)."""
    phrase = (phrase or "").strip()
    if writer.EMAIL.match(phrase):
        a = phrase.lower()
        p = people.get(a, {"address": a, "name": "", "count": 0})
        return [{**p, "score": 100}]
    aliases = _load_aliases()
    key = re.sub(r"\s+", " ", phrase.lower())
    alias_addr = aliases.get(key)
    pp = writer.person(phrase)
    toks = _tokens(pp["name"]) or _tokens(phrase)
    toks = [t for t in toks if t not in ("the", "mr", "mrs", "ms", "sir", "madam", "team", "dept", "department")] or toks
    if not toks:
        return []
    out = []
    for a, p in people.items():
        name_t = _tokens(p["name"])
        local = a.split("@")[0]
        local_t = _tokens(re.sub(r"[._\-+]", " ", local))
        full = name_t + local_t
        got = 0.0
        for t in toks:
            if t in full:
                got += 1
            elif len(t) >= 3 and any(x.startswith(t) for x in full):
                got += 0.7
            elif len(t) >= 4 and t in local:
                got += 0.5
        if not got:
            continue
        sc = 70 * got / len(toks) + min(15, p["count"] ** 0.5 * 3)
        if p["name"] and p["name"].lower() == key:
            sc += 30
        out.append({**p, "score": round(sc, 1), "_full": got >= len(toks) - 1e-9})
    if alias_addr:
        known = people.get(alias_addr, {"address": alias_addr, "name": "", "count": 0})
        out = [o for o in out if o["address"] != alias_addr]
        out.insert(0, {**known, "score": 200, "_full": True})
    out.sort(key=lambda o: -o["score"])
    return out[:6]


def resolve(phrase: str, people: dict) -> dict:
    """{phrase, address|None, name, candidates[]}: address is set only when the match is clear."""
    cands = match(phrase, people)
    pick = None
    if cands:
        top = cands[0]
        second = cands[1]["score"] if len(cands) > 1 else 0
        if top["score"] >= 200 or top["score"] == 100 and "@" in phrase or top.get("_full") and top["score"] - second >= 12:
            pick = top
    clean = [{"name": c["name"], "address": c["address"]} for c in cands]
    return {"phrase": phrase, "address": pick["address"] if pick else None,
            "name": pick["name"] if pick else "", "candidates": clean}


def search(q: str, people: dict, limit: int = 8) -> list[dict]:
    if not (q or "").strip():
        top = sorted(people.values(), key=lambda p: -p["count"])[:limit]
        return [{"name": p["name"], "address": p["address"]} for p in top]
    return [{"name": c["name"], "address": c["address"]} for c in match(q, people)][:limit]


_cache = {"at": 0.0, "data": None}
CACHE_SECONDS = 600


def cached(loader) -> dict:
    """loader() -> build(...) result; refreshed every 10 minutes."""
    with _lock:
        if _cache["data"] is not None and time.time() - _cache["at"] < CACHE_SECONDS:
            return _cache["data"]
    data = loader()
    with _lock:
        _cache.update(at=time.time(), data=data)
    return data


# ---------------------------------------------------------------------------
# Your signature for written emails: {name, title, company, phone}

_SIG_PATH = config.DATA_DIR / "signature.json"
SIG_FIELDS = ("name", "title", "company", "phone")


def get_signature(default_name: str = "") -> dict:
    try:
        data = json.loads(_SIG_PATH.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            return {k: str(data.get(k) or "")[:80] for k in SIG_FIELDS} | {"saved": True}
    except (OSError, ValueError):
        pass
    return {"name": default_name, "title": "", "company": "", "phone": "", "saved": False}


def save_signature(values: dict) -> dict:
    sig = {k: re.sub(r"\s+", " ", str(values.get(k) or "")).strip()[:80] for k in SIG_FIELDS}
    with _lock:
        config.DATA_DIR.mkdir(parents=True, exist_ok=True)
        tmp = _SIG_PATH.with_suffix(".tmp")
        tmp.write_text(json.dumps(sig, indent=1, ensure_ascii=False), encoding="utf-8")
        tmp.replace(_SIG_PATH)
    return sig | {"saved": True}
