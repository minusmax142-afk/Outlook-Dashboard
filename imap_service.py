"""
IMAP/SMTP backend: talks directly to your mail server (e.g. mail.indigoheights.com).

Works no matter which Outlook you use (classic, New Outlook, phone): they all read the same
server mailbox, so anything done here shows up everywhere.

Same function names and return shapes as outlook_service.py. Nothing here prints or stores email
content; a few recently opened messages are cached in memory only, to make attachments fast.
"""

from __future__ import annotations

import base64
import binascii
import email
import email.policy
import html
import imaplib
import logging
import mimetypes
import quopri
import re
import smtplib
import socket
import ssl
import threading
import time
from collections import OrderedDict
from datetime import date, datetime, timedelta
from email.message import EmailMessage
from email.utils import formataddr, format_datetime, getaddresses, make_msgid, parsedate_to_datetime

import imapclient
from imapclient.exceptions import IMAPClientError, LoginError

import imap_account
import categories
import contacts
import translate
import writer
import tasks_store
from errors import BadRequest, NotFound, NotSignedIn, OutlookError, ServiceUnavailable

log = logging.getLogger("imap")

PAGE_SIZE_DEFAULT = 50
PAGE_SIZE_MAX = 200
PREVIEW_BYTES = 2000
ATTACHMENT_SCAN_LIMIT = 2000  # "has attachments" filter checks at most this many newest messages

SPECIAL = {
    "sentitems": (b"\\Sent", ["Sent", "INBOX.Sent", "Sent Items", "INBOX.Sent Items", "Sent Messages"]),
    "drafts": (b"\\Drafts", ["Drafts", "INBOX.Drafts"]),
    "deleteditems": (b"\\Trash", ["Trash", "INBOX.Trash", "Deleted Items", "INBOX.Deleted Items", "Deleted Messages"]),
    "junkemail": (b"\\Junk", ["Junk", "INBOX.Junk", "Spam", "INBOX.spam", "Junk E-mail"]),
    "archive": (b"\\Archive", ["Archive", "INBOX.Archive"]),
}
EMAIL_RE = re.compile(r"^[^@\s<>;,]+@[^@\s<>;,]+\.[^@\s<>;,]+$")

# ---------------------------------------------------------------------------
# Connection (one shared, reused IMAP connection, serialized with a lock)
# ---------------------------------------------------------------------------

_lock = threading.RLock()
_client: imapclient.IMAPClient | None = None
_client_user: str | None = None
_folder_cache: dict = {}
_last_used = [0.0]  # monotonic time the connection last worked


def _connect() -> imapclient.IMAPClient:
    acc = imap_account.get_account()
    c = imapclient.IMAPClient(acc["imapHost"], port=acc["imapPort"], ssl=True,
                              ssl_context=ssl.create_default_context(), timeout=30)
    try:
        c.login(acc["email"], acc["password"])
    except LoginError:
        try:
            c.logout()
        except Exception:
            pass
        imap_account.password_rejected()
        raise NotSignedIn("The mail server rejected your saved password (was it changed?). Please sign in again.") from None
    return c


def _imap() -> imapclient.IMAPClient:
    global _client, _client_user
    acc = imap_account.get_account()
    if _client is not None and _client_user == acc["email"]:
        # A NOOP costs a round trip to the server; only check a connection that has been idle.
        # (run() reconnects and retries once if a recent connection turns out to be dead.)
        if time.monotonic() - _last_used[0] < 60:
            _last_used[0] = time.monotonic()
            return _client
        try:
            _client.noop()
            _last_used[0] = time.monotonic()
            return _client
        except Exception:
            _drop()
    _client = _connect()
    _client_user = acc["email"]
    _folder_cache.clear()
    _last_used[0] = time.monotonic()
    return _client


def _drop() -> None:
    global _client
    if _client is not None:
        try:
            _client.logout()
        except Exception:
            pass
    _client = None


def run(fn, *args, **kwargs):
    """Runs a backend call under the connection lock; retries once if the connection dropped."""
    with _lock:
        for attempt in range(2):
            try:
                return fn(*args, **kwargs)
            except OutlookError:
                raise
            except (imaplib.IMAP4.abort, ConnectionError, socket.timeout, ssl.SSLError, EOFError) as err:
                _drop()
                if attempt == 0:
                    continue
                log.warning("IMAP connection failed: %s", type(err).__name__)
                raise ServiceUnavailable("Lost the connection to the mail server. Check your internet/VPN and try again.") from None
            except socket.gaierror:
                raise ServiceUnavailable("Can't find the mail server. Check your internet connection.") from None
            except smtplib.SMTPAuthenticationError:
                raise NotSignedIn("The outgoing mail server rejected your password. Please sign in again.") from None
            except smtplib.SMTPRecipientsRefused as err:
                bad = ", ".join(list(err.recipients)[:5])
                raise BadRequest(f"The mail server refused these recipients: {bad}") from None
            except smtplib.SMTPException as err:
                log.warning("SMTP error: %s", type(err).__name__)
                raise BadRequest("The mail server didn't accept the message. It may be too large or contain a blocked attachment.") from None
            except (IMAPClientError, imaplib.IMAP4.error) as err:
                log.warning("IMAP error: %s", type(err).__name__)
                raise BadRequest("The mail server couldn't complete that request.") from None
            except Exception as err:
                log.error("Unexpected error: %s", type(err).__name__)
                raise OutlookError(f"Unexpected error ({type(err).__name__}). Please try again.") from None


# ---------------------------------------------------------------------------
# Folders and ids
# ---------------------------------------------------------------------------


def _folders() -> list[tuple]:
    if "list" not in _folder_cache:
        _folder_cache["list"] = _imap().list_folders()
    return _folder_cache["list"]


def _folder_name(key: str) -> str:
    """Maps a well-known key (inbox, sentitems, drafts, deleteditems, junkemail, archive) or a
    folder name to the server's real folder name."""
    k = (key or "inbox").strip()
    if k.lower() == "inbox":
        return "INBOX"
    if k.lower() in SPECIAL:
        cache_key = "special:" + k.lower()
        if cache_key not in _folder_cache:
            flag, names = SPECIAL[k.lower()]
            found = None
            for flags, _delim, name in _folders():
                if flag in flags:
                    found = name
                    break
            if not found:
                existing = {name.lower(): name for _f, _d, name in _folders()}
                found = next((existing[n.lower()] for n in names if n.lower() in existing), None)
            _folder_cache[cache_key] = found
        if not _folder_cache[cache_key]:
            raise NotFound(f"Your mailbox has no {k} folder.")
        return _folder_cache[cache_key]
    if any(name == k for _f, _d, name in _folders()):
        return k
    raise NotFound("That folder couldn't be found. It may have been renamed or deleted.")


def _make_id(folder: str, uidvalidity: int, uid: int) -> str:
    raw = f"{folder}\x00{uidvalidity}\x00{uid}".encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _parse_id(message_id: str) -> tuple[str, int, int]:
    try:
        padded = message_id + "=" * (-len(message_id) % 4)
        folder, validity, uid = base64.urlsafe_b64decode(padded.encode("ascii")).decode("utf-8").split("\x00")
        return folder, int(validity), int(uid)
    except (ValueError, UnicodeError, binascii.Error):
        raise BadRequest("Invalid message id.") from None


def _select(folder: str, readonly: bool = True) -> int:
    info = _imap().select_folder(folder, readonly=readonly)
    return int(info[b"UIDVALIDITY"])


def _open(message_id: str, readonly: bool = True) -> tuple[str, int]:
    """Selects the message's folder and returns (folder, uid). NotFound if it's gone."""
    folder, validity, uid = _parse_id(message_id)
    try:
        current = _select(folder, readonly)
    except IMAPClientError:
        raise NotFound("That email's folder no longer exists.") from None
    if current != validity or not _imap().search(["UID", uid]):
        raise NotFound("That email no longer exists. It may have been moved or deleted.")
    return folder, uid


# ---------------------------------------------------------------------------
# Parsing helpers
# ---------------------------------------------------------------------------


def _s(v) -> str:
    if v is None:
        return ""
    return v.decode("utf-8", "replace") if isinstance(v, bytes) else str(v)


def _person(value: str) -> dict | None:
    pairs = getaddresses([value or ""])
    if not pairs or not (pairs[0][0] or pairs[0][1]):
        return None
    name, addr = pairs[0]
    return {"name": name or addr, "address": addr}


def _people(value: str) -> list[dict]:
    return [{"name": n or a, "address": a} for n, a in getaddresses([value or ""]) if a or n]


def _iso_local(dt: datetime | None) -> str | None:
    if not dt:
        return None
    return (dt if dt.tzinfo else dt.astimezone()).astimezone().isoformat()


def _importance(headers) -> str:
    imp = (headers.get("Importance") or "").lower()
    prio = (headers.get("X-Priority") or "").strip()[:1]
    if imp == "high" or prio in ("1", "2"):
        return "high"
    if imp == "low" or prio in ("4", "5"):
        return "low"
    return "normal"


def _leaves(bs, number: str = ""):
    """Yields (IMAP part number, bodystructure) for every leaf part: "1", "2", "1.1", ..."""
    if bs.is_multipart:
        for i, child in enumerate(bs[0], start=1):
            yield from _leaves(child, f"{number}.{i}" if number else str(i))
    else:
        yield (number or "1"), bs


def _item(data: dict, prefix: bytes) -> bytes | None:
    """Fetch-response value whose key starts with prefix (servers vary in how they echo keys)."""
    for key, value in data.items():
        if isinstance(key, bytes) and key.upper().startswith(prefix.upper()):
            return value
    return None


def _params(part) -> dict:
    p = part[2] if len(part) > 2 and isinstance(part[2], tuple) else ()
    return {_s(p[i]).lower(): _s(p[i + 1]) for i in range(0, len(p) - 1, 2)}


def _has_attachments(bs) -> bool:
    for _num, part in _leaves(bs):
        maintype = _s(part[0]).lower()
        if maintype not in ("text", "multipart") or "name" in _params(part):
            return True
    return False


def _text_part(bs):
    """(part number, subtype, encoding, charset) of the best part for a preview, or None."""
    best = None
    for num, part in _leaves(bs):
        if _s(part[0]).lower() != "text" or "name" in _params(part):
            continue
        subtype = _s(part[1]).lower()
        info = (num, subtype, _s(part[5]).lower() if len(part) > 5 else "", _params(part).get("charset") or "utf-8")
        if subtype == "plain":
            return info
        if subtype == "html" and best is None:
            best = info
    return best


def _decode_partial(data: bytes, encoding: str, charset: str) -> str:
    try:
        if encoding == "base64":
            cleaned = re.sub(rb"[^A-Za-z0-9+/=]", b"", data)
            data = base64.b64decode(cleaned[: len(cleaned) - len(cleaned) % 4] or b"")
        elif encoding == "quoted-printable":
            data = quopri.decodestring(data)
    except (binascii.Error, ValueError):
        return ""
    try:
        return data.decode(charset, "replace")
    except LookupError:
        return data.decode("utf-8", "replace")


def _strip_html(text: str) -> str:
    text = re.sub(r"(?is)<(script|style|head)[^>]*>.*?</\1>", " ", text)
    text = re.sub(r"(?i)<br\s*/?>|</p>|</div>|</tr>|</li>", "\n", text)
    return html.unescape(re.sub(r"<[^>]+>", " ", text))


def _fetch_texts(uids: list[int], bodystructures: dict, max_bytes: int) -> dict[int, str]:
    """First max_bytes of each message's main text part, decoded (grouped to keep round trips low)."""
    groups: dict[str, list[int]] = {}
    info = {}
    for uid in uids:
        bs = bodystructures.get(uid)
        tp = _text_part(bs) if bs is not None else None
        if tp:
            info[uid] = tp
            groups.setdefault(tp[0], []).append(uid)
    out = {}
    for num, group in groups.items():
        prefix = f"BODY[{num}]".encode()
        for uid, data in _imap().fetch(group, [f"BODY.PEEK[{num}]<0.{max_bytes}>"]).items():
            raw = _item(data, prefix) or b""
            _num, subtype, enc, charset = info[uid]
            text = _decode_partial(raw, enc, charset)
            out[uid] = _strip_html(text) if subtype == "html" else text
    return out


HEADER_FIELDS = "BODY.PEEK[HEADER.FIELDS (FROM TO CC SUBJECT DATE MESSAGE-ID IMPORTANCE X-PRIORITY)]"
HEADER_KEY = b"BODY[HEADER.FIELDS"


def _headers(data: dict):
    return email.message_from_bytes(_item(data, HEADER_KEY) or b"", policy=email.policy.default)


def _categories_of(flags) -> list[str]:
    """Category names for an email's IMAP keywords (unknown keywords are ignored)."""
    known = categories.keyword_map()
    out = []
    for f in flags or ():
        cat = known.get(_s(f).lower())
        if cat:
            out.append(cat["name"])
    return out


def _summary(message_id: str, data: dict, preview: str = "") -> dict:
    h = _headers(data)
    flags = data.get(b"FLAGS") or ()
    bs = data.get(b"BODYSTRUCTURE")
    return {
        "id": message_id,
        "conversationId": "",
        "subject": (str(h.get("Subject") or "")).strip() or "(no subject)",
        "preview": re.sub(r"\s+", " ", preview).strip()[:160],
        "from": _person(str(h.get("From") or "")),
        "toRecipients": _people(str(h.get("To") or ""))[:5],
        "receivedDateTime": _iso_local(data.get(b"INTERNALDATE")),
        "isRead": imapclient.SEEN in flags,
        "isDraft": imapclient.DRAFT in flags,
        "hasAttachments": _has_attachments(bs) if bs is not None else False,
        "flagged": imapclient.FLAGGED in flags,
        "importance": _importance(h),
        "categories": _categories_of(flags),
        "size": int(data.get(b"RFC822.SIZE") or 0),
        "conversationKey": base_subject(str(h.get("Subject") or "")),
    }


# ---------------------------------------------------------------------------
# Status / folders / list
# ---------------------------------------------------------------------------


def get_status() -> dict:
    acc = imap_account.get_account()
    _imap()
    return {"connected": True, "backend": "imap", "user": acc.get("name") or acc["email"], "accounts": [acc["email"]]}


SPECIAL_ORDER = ["drafts", "sentitems", "archive", "junkemail", "deleteditems"]
SPECIAL_LABELS = {"inbox": "Inbox", "drafts": "Drafts", "sentitems": "Sent Items", "archive": "Archive",
                  "junkemail": "Junk Email", "deleteditems": "Deleted Items"}
FOLDER_NAME_MAX = 100
_BAD_FOLDER_CHARS = re.compile(r'[\x00-\x1f\x7f%*"\\/]')


def _personal_prefix() -> tuple[str, str]:
    """(namespace prefix, delimiter), e.g. ("INBOX.", ".") on cPanel/Dovecot servers, ("", "/") elsewhere."""
    if "ns" not in _folder_cache:
        prefix, delim = "", None
        try:
            ns = _imap().namespace()
            if ns.personal:
                prefix, delim = ns.personal[0][0] or "", ns.personal[0][1]
        except IMAPClientError:
            pass
        if not delim:
            delims = [d for _f, d, _n in _folders() if d]
            delim = delims[0] if delims else "/"
        _folder_cache["ns"] = (prefix, _s(delim))
    return _folder_cache["ns"]


def _special_keys() -> dict[str, str]:
    """Real folder name -> well-known key, for the folders the server has."""
    out = {"INBOX": "inbox"}
    for key in SPECIAL:
        try:
            out[_folder_name(key)] = key
        except NotFound:
            pass
    return out


def _display_path(name: str) -> list[str]:
    prefix, delim = _personal_prefix()
    if name.upper() == "INBOX":
        return ["Inbox"]
    rel = name[len(prefix):] if prefix and name.startswith(prefix) else name
    return [p for p in rel.split(delim) if p] or [name]


def list_folders() -> dict:
    """Every folder with unread/total counts, Inbox and the special folders first, then the user's own
    folders as a tree (parents before children, alphabetical)."""
    _folder_cache.pop("list", None)  # always fresh: folders may change in Outlook too
    for k in [k for k in _folder_cache if k.startswith("special:")]:
        _folder_cache.pop(k)
    c = _imap()
    specials = _special_keys()
    prefix, delim = _personal_prefix()
    out = []
    for flags, _d, name in _folders():
        noselect = any(f.lower() in (b"\\noselect", b"\\nonexistent") for f in flags)
        unread = total = 0
        if not noselect:
            try:
                st = c.folder_status(name, ["MESSAGES", "UNSEEN"])
                unread, total = int(st.get(b"UNSEEN", 0)), int(st.get(b"MESSAGES", 0))
            except IMAPClientError:
                noselect = True
        key = specials.get(name)
        path = _display_path(name)
        out.append({
            "id": name,
            "key": key,
            "name": SPECIAL_LABELS[key] if key else path[-1],
            "path": path,
            "depth": 0 if key else len(path) - 1,
            "unreadCount": unread,
            "totalCount": total,
            "selectable": not noselect,
            "hasChildren": any(n.startswith(name + delim) for _f, _d2, n in _folders()),
            "canModify": key is None and not noselect,
        })

    def order(f):
        if f["key"] == "inbox":
            return (0, 0, [])
        if f["key"]:
            return (1, SPECIAL_ORDER.index(f["key"]), [])
        return (2, 0, [p.lower() for p in f["path"]])

    out.sort(key=order)
    return {"folders": out, "delimiter": delim}


def _check_folder_name(name: str) -> str:
    _prefix, delim = _personal_prefix()
    name = (name or "").strip()
    if not name:
        raise BadRequest("Enter a folder name.")
    if len(name) > FOLDER_NAME_MAX:
        raise BadRequest(f"Folder names can be at most {FOLDER_NAME_MAX} characters.")
    if delim in name or _BAD_FOLDER_CHARS.search(name):
        raise BadRequest(f"Folder names can't contain {delim} / \\ % * or quotes.")
    if name.lower() == "inbox":
        raise BadRequest("That name is reserved.")
    return name


def _user_folder(folder: str) -> str:
    """Real name of a folder the user may rename/delete (not Inbox or a special folder)."""
    name = _folder_name(folder)
    if name in _special_keys():
        raise BadRequest("Inbox, Drafts, Sent Items, Deleted Items, Junk and Archive can't be renamed or deleted.")
    return name


def _refresh_folder_cache() -> None:
    for k in [k for k in _folder_cache if k == "list" or k.startswith("special:")]:
        _folder_cache.pop(k)


def _exists(name: str) -> bool:
    return any(n.lower() == name.lower() for _f, _d, n in _folders())


def create_folder(name: str, parent: str | None = None) -> dict:
    name = _check_folder_name(name)
    prefix, delim = _personal_prefix()
    if parent:
        base = _folder_name(parent)
        full = f"{base}{delim}{name}"
    else:
        full = f"{prefix}{name}"
    _refresh_folder_cache()
    if _exists(full):
        raise BadRequest("A folder with that name already exists there.")
    c = _imap()
    c.create_folder(full)
    try:
        c.subscribe_folder(full)  # so Outlook and phones show it
    except IMAPClientError:
        pass
    _refresh_folder_cache()
    return {"id": full, "name": name}


def rename_folder(folder: str, new_name: str) -> dict:
    old = _user_folder(folder)
    new_name = _check_folder_name(new_name)
    _prefix, delim = _personal_prefix()
    parent = old.rsplit(delim, 1)[0] + delim if delim in old else ""
    new = parent + new_name
    if new == old:
        return {"id": old, "name": new_name}
    if _exists(new) and new.lower() != old.lower():
        raise BadRequest("A folder with that name already exists there.")
    c = _imap()
    c.select_folder("INBOX", readonly=True)  # some servers can't rename the selected folder
    c.rename_folder(old, new)
    for name in [new] + [n for _f, _d, n in c.list_folders() if n.startswith(new + delim)]:
        try:
            c.subscribe_folder(name)
        except IMAPClientError:
            pass
    try:
        c.unsubscribe_folder(old)
    except IMAPClientError:
        pass
    _refresh_folder_cache()
    _raw_cache.clear()
    return {"id": new, "name": new_name}


def delete_folder(folder: str) -> dict:
    """Moves the folder's emails to Deleted Items, then removes the folder. Refuses if it has subfolders."""
    name = _user_folder(folder)
    _prefix, delim = _personal_prefix()
    if any(n.startswith(name + delim) for _f, _d, n in _folders()):
        raise BadRequest("This folder has subfolders. Delete or move them first.")
    c = _imap()
    moved = 0
    try:
        trash = _folder_name("deleteditems")
    except NotFound:
        trash = None
    _select(name, readonly=False)
    uids = c.search(["ALL"])
    if uids and trash:
        if c.has_capability("MOVE"):
            c.move(uids, trash)
        else:
            c.copy(uids, trash)
            c.add_flags(uids, [imapclient.DELETED])
            c.expunge()
        moved = len(uids)
    c.close_folder()
    c.select_folder("INBOX", readonly=True)
    c.delete_folder(name)
    try:
        c.unsubscribe_folder(name)
    except IMAPClientError:
        pass
    _refresh_folder_cache()
    _raw_cache.clear()
    return {"id": name, "deleted": True, "movedToDeletedItems": moved}


def move_messages(message_ids: list[str], destination: str) -> dict:
    """Moves one or more emails (from any folders) to another folder."""
    if not message_ids:
        raise BadRequest("Select at least one email.")
    if len(message_ids) > 1000:
        raise BadRequest("Move at most 1000 emails at a time.")
    dest = _folder_name(destination)
    by_folder: dict[tuple[str, int], list[int]] = {}
    for mid in message_ids:
        folder, validity, uid = _parse_id(str(mid))
        by_folder.setdefault((folder, validity), []).append(uid)
    c = _imap()
    moved = skipped = 0
    for (folder, validity), uids in by_folder.items():
        if folder == dest:
            skipped += len(uids)
            continue
        try:
            current = _select(folder, readonly=False)
        except IMAPClientError:
            skipped += len(uids)
            continue
        if current != validity:
            skipped += len(uids)
            continue
        present = set(c.search(["UID", ",".join(str(u) for u in uids)])) if uids else set()
        todo = [u for u in uids if u in present]
        skipped += len(uids) - len(todo)
        if not todo:
            continue
        if c.has_capability("MOVE"):
            c.move(todo, dest)
        else:
            c.copy(todo, dest)
            c.add_flags(todo, [imapclient.DELETED])
            if c.has_capability("UIDPLUS"):
                c.uid_expunge(todo)
            else:
                c.expunge()
        moved += len(todo)
    for mid in message_ids:
        _raw_cache.pop(str(mid), None)
    return {"moved": moved, "skipped": skipped, "destination": dest}


BULK_ACTIONS = ("read", "unread", "flag", "unflag", "delete", "categorize", "uncategorize")


def _group_by_folder(message_ids: list[str]) -> dict[tuple[str, int], list[int]]:
    if not message_ids:
        raise BadRequest("Select at least one email.")
    if len(message_ids) > 1000:
        raise BadRequest("Select at most 1000 emails at a time.")
    groups: dict[tuple[str, int], list[int]] = {}
    for mid in message_ids:
        folder, validity, uid = _parse_id(str(mid))
        groups.setdefault((folder, validity), []).append(uid)
    return groups


def bulk_update(message_ids: list[str], action: str, category: str | None = None) -> dict:
    """Applies one action to many emails. Returns how many were changed and which ids were
    deleted/skipped, so the page can update without reloading."""
    if action not in BULK_ACTIONS:
        raise BadRequest("Unknown action.")
    keyword = categories.by_name(category)["keyword"] if action in ("categorize", "uncategorize") else None
    try:
        trash = _folder_name("deleteditems")
    except NotFound:
        trash = None
    c = _imap()
    done = skipped = 0
    permanent = 0
    for (folder, validity), uids in _group_by_folder(message_ids).items():
        try:
            current = _select(folder, readonly=False)
        except IMAPClientError:
            skipped += len(uids)
            continue
        if current != validity:
            skipped += len(uids)
            continue
        present = set(c.search(["UID", ",".join(str(u) for u in uids)]))
        todo = [u for u in uids if u in present]
        skipped += len(uids) - len(todo)
        if not todo:
            continue
        if action in ("read", "unread"):
            (c.add_flags if action == "read" else c.remove_flags)(todo, [imapclient.SEEN])
        elif action in ("flag", "unflag"):
            (c.add_flags if action == "flag" else c.remove_flags)(todo, [imapclient.FLAGGED])
        elif action in ("categorize", "uncategorize"):
            (c.add_flags if action == "categorize" else c.remove_flags)(todo, [keyword])
        elif action == "delete":
            if trash and folder != trash:
                if c.has_capability("MOVE"):
                    c.move(todo, trash)
                else:
                    c.copy(todo, trash)
                    c.add_flags(todo, [imapclient.DELETED])
                    c.uid_expunge(todo) if c.has_capability("UIDPLUS") else c.expunge()
            else:  # already in Deleted Items (or there is none): remove for good
                c.add_flags(todo, [imapclient.DELETED])
                c.uid_expunge(todo) if c.has_capability("UIDPLUS") else c.expunge()
                permanent += len(todo)
        done += len(todo)
    for mid in message_ids:
        _raw_cache.pop(str(mid), None)
    return {"action": action, "changed": done, "skipped": skipped, "permanentlyDeleted": permanent}


def _daily_counts(folder: str, days: int) -> dict[str, int]:
    """Emails per local day (YYYY-MM-DD) for the last `days` days, by arrival time."""
    today = date.today()
    first = today - timedelta(days=days - 1)
    counts = {(first + timedelta(days=i)).isoformat(): 0 for i in range(days)}
    _select(folder, readonly=True)
    # SINCE uses the server's date; ask for one extra day and bucket by local time here.
    uids = _imap().search(["SINCE", first - timedelta(days=1)])
    for i in range(0, len(uids), 500):
        for _uid, data in _imap().fetch(uids[i: i + 500], ["INTERNALDATE"]).items():
            dt = data.get(b"INTERNALDATE")
            if dt is None:
                continue
            day = (dt if dt.tzinfo else dt.astimezone()).astimezone().date().isoformat()
            if day in counts:
                counts[day] += 1
    return counts


DIGEST_MAX = 300  # newest emails summarised per request


def get_digest(days: int = 7) -> dict:
    """Summary of Inbox mail for the last `days` days: totals, top senders, types, a one-line summary
    of each email, and which emails contain tasks (with their status)."""
    import summarizer
    import task_finder

    days = max(1, min(int(days), 90))
    validity = _select("INBOX", readonly=True)
    since = date.today() - timedelta(days=days - 1)
    all_uids = sorted(_imap().search(["SINCE", since]), reverse=True)
    uids = all_uids[:DIGEST_MAX]
    c = _imap()
    fetched = c.fetch(uids, ["FLAGS", "INTERNALDATE", "BODYSTRUCTURE", "RFC822.SIZE", HEADER_FIELDS]) if uids else {}
    texts = _fetch_texts(uids, {u: d.get(b"BODYSTRUCTURE") for u, d in fetched.items()}, 12000) if uids else {}
    me = _my_address()

    tasks = tasks_store.list_tasks(include_completed=True)
    tasks_by_msg: dict[str, list[dict]] = {}
    for t in tasks:
        if t.get("messageId"):
            tasks_by_msg.setdefault(t["messageId"], []).append(t)
    handled = task_finder.handled_keys()
    today = date.today().isoformat()

    emails, senders, kinds, cats = [], {}, {}, {}
    for uid in uids:
        data = fetched.get(uid)
        if not data:
            continue
        mid = _make_id("INBOX", validity, uid)
        summary = _summary(mid, data)
        received = summary["receivedDateTime"] or ""
        if received[:10] < since.isoformat():
            continue  # server SINCE uses its own date; keep only local days in range
        text = texts.get(uid, "")
        flags = data.get(b"FLAGS") or ()
        task_input = _for_tasks(mid, data, text, me)
        suggestions = task_finder.suggest_for_message(task_input)
        linked = tasks_by_msg.get(mid, [])
        if linked:
            status = "done" if all(t["completed"] for t in linked) else "added"
        elif suggestions and all(s["key"] in handled for s in suggestions):
            status = "dismissed"
        elif suggestions:
            status = "new"
        else:
            status = None
        sender = summary["from"] or {"name": "(unknown sender)", "address": ""}
        kind = summarizer.kind_of(summary["subject"], sender.get("address", ""), text, bool(suggestions))
        answered = imapclient.ANSWERED in flags
        emails.append({
            **{k: summary[k] for k in ("id", "subject", "from", "receivedDateTime", "isRead", "flagged",
                                       "hasAttachments", "importance", "categories")},
            "answered": answered,
            "kind": kind,
            "kindLabel": summarizer.KIND_LABELS[kind],
            "summary": summarizer.summarize(summary["subject"], text),
            "tasks": [{k: s[k] for k in ("key", "title", "due", "confidence", "quote")} | {"handled": s["key"] in handled}
                      for s in suggestions],
            "taskStatus": status,
            "linkedTasks": [{"id": t["id"], "title": t["title"], "due": t["due"], "completed": t["completed"]} for t in linked],
            "needsReply": bool(suggestions) and not answered and kind == "request",
        })
        key = (sender.get("address") or sender.get("name") or "?").lower()
        s = senders.setdefault(key, {"name": sender.get("name") or key, "address": sender.get("address") or "", "count": 0, "unread": 0})
        s["count"] += 1
        s["unread"] += 0 if summary["isRead"] else 1
        kinds[kind] = kinds.get(kind, 0) + 1
        for cat in summary["categories"]:
            cats[cat] = cats.get(cat, 0) + 1

    task_mails = [e for e in emails if e["taskStatus"]]
    open_dues = [t["due"] for e in task_mails if e["taskStatus"] == "new" for t in e["tasks"] if t["due"] and not t["handled"]]
    open_dues += [t["due"][:10] for e in task_mails for t in e["linkedTasks"] if t["due"] and not t["completed"]]
    week_end = (date.today() + timedelta(days=7)).isoformat()
    return {
        "days": days,
        "since": since.isoformat(),
        "truncated": len(all_uids) > DIGEST_MAX,
        "stats": {
            "received": len(emails),
            "unread": sum(1 for e in emails if not e["isRead"]),
            "answered": sum(1 for e in emails if e["answered"]),
            "needsReply": sum(1 for e in emails if e["needsReply"]),
            "attachments": sum(1 for e in emails if e["hasAttachments"]),
            "highImportance": sum(1 for e in emails if e["importance"] == "high"),
            "senders": len(senders),
        },
        "topSenders": sorted(senders.values(), key=lambda s: (-s["count"], s["name"].lower()))[:8],
        "kinds": [{"kind": k, "label": summarizer.KIND_LABELS[k], "count": n}
                  for k, n in sorted(kinds.items(), key=lambda kv: -kv[1])],
        "categories": [{"name": k, "count": n} for k, n in sorted(cats.items(), key=lambda kv: -kv[1])],
        "taskStats": {
            "emails": len(task_mails),
            "new": sum(1 for e in task_mails if e["taskStatus"] == "new"),
            "added": sum(1 for e in task_mails if e["taskStatus"] in ("added", "done")),
            "done": sum(1 for e in task_mails if e["taskStatus"] == "done"),
            "dismissed": sum(1 for e in task_mails if e["taskStatus"] == "dismissed"),
            "overdue": sum(1 for d in open_dues if d < today),
            "dueThisWeek": sum(1 for d in open_dues if today <= d <= week_end),
        },
        "emails": emails,
    }


def get_overview(days: int = 7) -> dict:
    c = _imap()
    inbox = c.folder_status("INBOX", ["MESSAGES", "UNSEEN"])
    _select("INBOX", readonly=True)
    flagged = len(c.search(["FLAGGED"]))
    received = _daily_counts("INBOX", days)
    try:
        sent_folder = _folder_name("sentitems")
        sent = _daily_counts(sent_folder, days)
    except NotFound:
        sent = {d: 0 for d in received}
    try:
        drafts = int(c.folder_status(_folder_name("drafts"), ["MESSAGES"]).get(b"MESSAGES", 0))
    except NotFound:
        drafts = 0
    recent_unread = list_messages(folder="inbox", limit=5, unread=True)["messages"]
    today = date.today().isoformat()
    return {
        "inboxUnread": int(inbox.get(b"UNSEEN", 0)),
        "inboxTotal": int(inbox.get(b"MESSAGES", 0)),
        "flagged": flagged,
        "drafts": drafts,
        "receivedToday": received.get(today, 0),
        "daily": [{"date": d, "received": received[d], "sent": sent.get(d, 0)} for d in received],
        "recentUnread": recent_unread,
    }


def get_folder_summary(folder: str = "inbox") -> dict:
    name = _folder_name(folder)
    st = _imap().folder_status(name, ["MESSAGES", "UNSEEN"])
    return {"id": name, "key": folder.lower() if folder.lower() in SPECIAL or folder.lower() == "inbox" else None,
            "name": name, "unreadCount": int(st.get(b"UNSEEN", 0)), "totalCount": int(st.get(b"MESSAGES", 0))}


def _search(criteria: list, search: str | None) -> list[int]:
    c = _imap()
    if search:
        term = search.strip()[:200]
        crit = criteria + ["OR", "FROM", term, "SUBJECT", term]
        try:
            return c.search(crit, charset="UTF-8")
        except IMAPClientError:
            if term.isascii():
                return c.search(crit)
            raise BadRequest("The mail server couldn't search for that text.") from None
    return c.search(criteria or ["ALL"])


SORTS = ("newest", "oldest", "sender", "subject", "size")
_SERVER_SORT = {
    "sender": ["DISPLAYFROM", "REVERSE", "DATE"],
    "subject": ["SUBJECT", "REVERSE", "DATE"],
    "size": ["REVERSE", "SIZE"],
}
SORT_FALLBACK_LIMIT = 5000
_RE_PREFIX = re.compile(r"^\s*((re|fw|fwd|aw|wg|sv|vs)\s*(\[\d+\])?\s*:\s*)+", re.I)


def base_subject(subject: str) -> str:
    """Subject without Re:/Fw: prefixes, used to group a conversation."""
    return re.sub(r"\s+", " ", _RE_PREFIX.sub("", subject or "")).strip().lower()


def _sorted_uids(criteria: list, search: str | None, sort: str) -> list[int]:
    if sort in ("newest", "oldest") or sort not in _SERVER_SORT:
        return sorted(_search(criteria, search), reverse=(sort != "oldest"))  # UIDs grow with arrival
    c = _imap()
    if c.has_capability("SORT"):
        keys = list(_SERVER_SORT[sort])
        if sort == "sender" and not c.has_capability("SORT=DISPLAY"):
            keys[0] = "FROM"
        crit = list(criteria) or ["ALL"]
        if search:
            crit = list(criteria) + ["OR", "FROM", search.strip()[:200], "SUBJECT", search.strip()[:200]]
        try:
            return list(c.sort(keys, crit, charset="UTF-8"))
        except IMAPClientError:
            if not search or search.isascii():
                return list(c.sort(keys, crit, charset="US-ASCII"))
            raise BadRequest("The mail server couldn't search for that text.") from None
    # No server-side SORT: sort the newest few thousand here.
    uids = sorted(_search(criteria, search), reverse=True)[:SORT_FALLBACK_LIMIT]
    if not uids:
        return []
    keyed = {}
    for i in range(0, len(uids), 500):
        chunk = uids[i: i + 500]
        for uid, data in c.fetch(chunk, ["RFC822.SIZE", "BODY.PEEK[HEADER.FIELDS (FROM SUBJECT)]"]).items():
            h = _headers(data)
            p = _person(str(h.get("From") or "")) or {"name": "", "address": ""}
            if sort == "sender":
                keyed[uid] = (p["name"] or p["address"]).lower()
            elif sort == "subject":
                keyed[uid] = base_subject(str(h.get("Subject") or ""))
            else:
                keyed[uid] = -int(data.get(b"RFC822.SIZE") or 0)
    # Python's sort is stable: within equal keys the newest-first order is kept.
    return sorted(uids, key=lambda u: keyed.get(u, ""))


def list_messages(folder="inbox", start=0, limit=PAGE_SIZE_DEFAULT, search=None, unread=False, flagged=False,
                  has_attachments=False, date_from=None, date_to=None, sort="newest", category=None) -> dict:
    start = max(0, int(start))
    limit = max(1, min(int(limit), PAGE_SIZE_MAX))
    if sort not in SORTS:
        raise BadRequest("Unknown sort order.")
    name = _folder_name(folder)
    validity = _select(name, readonly=True)

    criteria: list = []
    if unread:
        criteria.append("UNSEEN")
    if flagged:
        criteria.append("FLAGGED")
    if category:
        criteria += ["KEYWORD", categories.by_name(category)["keyword"]]
    try:
        if date_from:
            criteria += ["SINCE", datetime.strptime(date_from, "%Y-%m-%d").date()]
        if date_to:  # BEFORE is exclusive, so use the next day
            criteria += ["BEFORE", datetime.strptime(date_to, "%Y-%m-%d").date() + timedelta(days=1)]
    except ValueError:
        raise BadRequest("Invalid date. Use YYYY-MM-DD.") from None

    uids = _sorted_uids(criteria, search, sort)
    c = _imap()
    if has_attachments:
        keep = set()
        candidates = sorted(uids, reverse=True)[:ATTACHMENT_SCAN_LIMIT]  # the newest ones
        for i in range(0, len(candidates), 200):
            chunk = candidates[i: i + 200]
            for uid, data in c.fetch(chunk, ["BODYSTRUCTURE"]).items():
                if _has_attachments(data[b"BODYSTRUCTURE"]):
                    keep.add(uid)
        uids = [u for u in uids if u in keep]  # keep the chosen sort order

    total = len(uids)
    page = uids[start: start + limit]
    messages = []
    if page:
        fetched = c.fetch(page, ["FLAGS", "INTERNALDATE", "BODYSTRUCTURE", "RFC822.SIZE", HEADER_FIELDS])
        previews = _fetch_texts(page, {u: d.get(b"BODYSTRUCTURE") for u, d in fetched.items()}, PREVIEW_BYTES)
        for uid in page:
            if uid in fetched:
                messages.append(_summary(_make_id(name, validity, uid), fetched[uid], previews.get(uid, "")))
    end = start + len(page)
    return {"messages": messages, "total": total, "start": start, "nextStart": end if end < total else None}


# ---------------------------------------------------------------------------
# Single message
# ---------------------------------------------------------------------------

_raw_cache: "OrderedDict[str, bytes]" = OrderedDict()  # memory only


def _raw(message_id: str) -> bytes:
    if message_id in _raw_cache:
        _raw_cache.move_to_end(message_id)
        return _raw_cache[message_id]
    _folder, uid = _open(message_id)
    data = _imap().fetch([uid], ["BODY.PEEK[]"]).get(uid, {})
    raw = data.get(b"BODY[]")
    if raw is None:
        raise NotFound("That email no longer exists.")
    _raw_cache[message_id] = raw
    while len(_raw_cache) > 6:
        _raw_cache.popitem(last=False)
    return raw


def _parsed(message_id: str) -> EmailMessage:
    return email.message_from_bytes(_raw(message_id), policy=email.policy.default)


def _parts(msg: EmailMessage) -> list:
    return list(msg.walk())


def _attachment_infos(msg: EmailMessage, body_html: str) -> list[dict]:
    out = []
    lower = body_html.lower()
    body_part = msg.get_body(preferencelist=("html", "plain"))
    plain_part = msg.get_body(preferencelist=("plain",))
    for index, part in enumerate(_parts(msg)):
        if part.is_multipart() or part is body_part or part is plain_part:
            continue
        disposition = part.get_content_disposition()
        filename = part.get_filename()
        if not filename and disposition is None and part.get_content_maintype() == "text":
            continue  # alternative text bodies, not attachments
        cid = (part.get("Content-ID") or "").strip().strip("<>")
        name = filename or ("message.eml" if part.get_content_type() == "message/rfc822" else f"attachment-{index}")
        payload = part.get_payload(decode=True) or b""
        out.append({
            "index": str(index),
            "id": str(index),
            "name": name,
            "size": len(payload),
            "mimeType": part.get_content_type(),
            "contentId": cid,
            "inline": bool(cid) and f"cid:{cid.lower()}" in lower,
        })
    return out


def get_message(message_id: str) -> dict:
    folder, uid = _open(message_id)
    meta = _imap().fetch([uid], ["FLAGS", "INTERNALDATE", "BODYSTRUCTURE", HEADER_FIELDS]).get(uid)
    if not meta:
        raise NotFound("That email no longer exists.")
    msg = _parsed(message_id)
    detail = _summary(message_id, meta)
    detail.pop("preview", None)

    html_part = msg.get_body(preferencelist=("html",))
    text_part = msg.get_body(preferencelist=("plain",))
    if html_part is not None:
        body, body_type = html_part.get_content(), "html"
    elif text_part is not None:
        body, body_type = text_part.get_content(), "text"
    else:
        body, body_type = "", "text"

    detail.update({
        "recipients": {"to": _people(str(msg.get("To") or "")), "cc": _people(str(msg.get("Cc") or "")),
                       "bcc": _people(str(msg.get("Bcc") or ""))},
        "sentDateTime": _iso_local(_date_header(msg)),
        "bodyType": body_type,
        "body": body,
        "attachments": _attachment_infos(msg, body if body_type == "html" else ""),
        "isDraft": imapclient.DRAFT in (meta.get(b"FLAGS") or ()),
        "folder": folder,
    })
    if detail["isDraft"]:
        # Plain text the compose box can edit (the dashboard saves drafts as text + HTML).
        detail["draftText"] = text_part.get_content() if text_part is not None else _strip_html(body).strip()
        detail["draftText"] = "" if detail["draftText"].strip() == "" else detail["draftText"]
    # Opening an email marks it read (like Outlook); the frontend asks for that separately.
    return detail


def _date_header(msg) -> datetime | None:
    try:
        return parsedate_to_datetime(str(msg.get("Date"))) if msg.get("Date") else None
    except (TypeError, ValueError):
        return None


def get_attachment(message_id: str, attachment_id) -> tuple[str, str, bytes]:
    msg = _parsed(message_id)
    parts = _parts(msg)
    try:
        part = parts[int(attachment_id)]
    except (ValueError, IndexError):
        raise NotFound("That attachment no longer exists.") from None
    if part.is_multipart():
        raise NotFound("That attachment no longer exists.")
    data = part.get_payload(decode=True)
    if data is None and part.get_content_type() == "message/rfc822":
        inner = part.get_payload(0) if part.is_multipart() else part.get_payload()
        data = inner.as_bytes() if hasattr(inner, "as_bytes") else b""
    name = part.get_filename() or ("message.eml" if part.get_content_type() == "message/rfc822" else "attachment")
    return name, part.get_content_type(), data or b""


def _set_flag(message_id: str, flag: bytes, on: bool) -> None:
    _folder, uid = _open(message_id, readonly=False)
    (_imap().add_flags if on else _imap().remove_flags)([uid], [flag])
    _raw_cache.pop(message_id, None)


def set_read(message_id: str, read: bool) -> dict:
    _set_flag(message_id, imapclient.SEEN, read)
    return {"id": message_id, "isRead": read}


def set_flag(message_id: str, flagged: bool) -> dict:
    _set_flag(message_id, imapclient.FLAGGED, flagged)
    return {"id": message_id, "flagged": flagged}


def _move(uid: int, dest: str) -> None:
    c = _imap()
    if c.has_capability("MOVE"):
        c.move([uid], dest)
    else:
        c.copy([uid], dest)
        c.add_flags([uid], [imapclient.DELETED])
        _expunge(uid)


def _expunge(uid: int) -> None:
    c = _imap()
    if c.has_capability("UIDPLUS"):
        c.uid_expunge([uid])
    else:
        c.expunge()


def delete_message(message_id: str, permanent: bool = False) -> dict:
    """Moves the email to Deleted Items (Trash). Emails already in Trash, and drafts the dashboard
    replaces, are removed for good."""
    folder, uid = _open(message_id, readonly=False)
    try:
        trash = _folder_name("deleteditems")
    except NotFound:
        trash = None
    if permanent or not trash or folder == trash:
        _imap().add_flags([uid], [imapclient.DELETED])
        _expunge(uid)
    else:
        _move(uid, trash)
    _raw_cache.pop(message_id, None)
    return {"id": message_id, "deleted": True}


# ---------------------------------------------------------------------------
# Compose
# ---------------------------------------------------------------------------

RESPONSE_MODES = ("reply", "replyall", "forward")


def _my_address() -> str:
    return imap_account.get_account()["email"].lower()


def _quote_block(msg: EmailMessage) -> str:
    """Outlook-style header block + original body, used below a reply/forward."""
    html_part = msg.get_body(preferencelist=("html",))
    text_part = msg.get_body(preferencelist=("plain",))
    if html_part is not None:
        original = html_part.get_content()
        match = re.search(r"(?is)<body[^>]*>(.*)</body>", original)
        original = match.group(1) if match else original
    elif text_part is not None:
        original = html.escape(text_part.get_content()).replace("\n", "<br>\n")
    else:
        original = ""
    sent = _date_header(msg)
    rows = [("From", str(msg.get("From") or "")),
            ("Sent", sent.astimezone().strftime("%A, %d %B %Y %I:%M %p") if sent else ""),
            ("To", str(msg.get("To") or "")), ("Cc", str(msg.get("Cc") or "")),
            ("Subject", str(msg.get("Subject") or ""))]
    header = "".join(f"<b>{k}:</b> {html.escape(v)}<br>" for k, v in rows if v)
    return ('<html><body><br><hr style="border:none;border-top:1px solid #b5c4df">'
            f'<div style="font-family:Calibri,Arial,sans-serif;font-size:11pt">{header}</div><br>'
            f"{original}</body></html>")


def _prefixed(subject: str, prefix: str) -> str:
    s = subject.strip()
    if re.match(rf"^\s*{prefix}\s*:", s, re.I) or (prefix == "FW" and re.match(r"^\s*fwd?\s*:", s, re.I)):
        return s
    return f"{prefix}: {s}"


def get_compose_prefill(source_id: str, mode: str) -> dict:
    if mode not in RESPONSE_MODES:
        raise BadRequest("Unknown compose mode.")
    msg = _parsed(source_id)
    me = _my_address()
    to, cc = [], []
    if mode in ("reply", "replyall"):
        to = _people(str(msg.get("Reply-To") or msg.get("From") or ""))
    if mode == "replyall":
        seen = {p["address"].lower() for p in to} | {me}
        for p in _people(str(msg.get("To") or "")) + _people(str(msg.get("Cc") or "")):
            if p["address"] and p["address"].lower() not in seen:
                seen.add(p["address"].lower())
                cc.append(p)
    subject = str(msg.get("Subject") or "")
    files = []
    if mode == "forward":
        files = [{"id": a["id"], "name": a["name"], "size": a["size"]}
                 for a in _attachment_infos(msg, "") if not a["inline"]]
    return {
        "mode": mode,
        "sourceId": source_id,
        "to": to,
        "cc": cc,
        "subject": _prefixed(subject, "FW" if mode == "forward" else "RE"),
        "quotedHtml": _quote_block(msg),
        "attachments": files,
    }


def _text_to_html(text: str) -> str:
    escaped = html.escape(text.replace("\r\n", "\n")).replace("\n", "<br>\n")
    return f'<div style="font-family:Calibri,Arial,sans-serif;font-size:11pt">{escaped}</div>'


def _with_user_text(quoted_html: str, user_html: str) -> str:
    match = re.search(r"<body[^>]*>", quoted_html, flags=re.IGNORECASE)
    if not match:
        return f"<html><body>{user_html}<br>{quoted_html}</body></html>"
    return quoted_html[: match.end()] + user_html + quoted_html[match.end():]


def _check_recipients(values: list[str], field: str) -> list[str]:
    bad = [v for v in values if not EMAIL_RE.match(v)]
    if bad:
        raise BadRequest(f"Please use full email addresses in {field}: " + ", ".join(bad[:5]))
    return values


def _carry_attachments(source: EmailMessage, keep_ids: set[str] | None, removed: set[str]) -> list:
    """Attachment parts (and inline images) to copy from an earlier draft or a forwarded email."""
    out = []
    body_html = ""
    html_part = source.get_body(preferencelist=("html",))
    if html_part is not None:
        body_html = html_part.get_content()
    for info in _attachment_infos(source, body_html):
        if info["id"] in removed or (keep_ids is not None and info["id"] not in keep_ids and not info["inline"]):
            continue
        out.append(_parts(source)[int(info["id"])])
    return out


def compose(action, mode="new", source_id=None, draft_id=None, to=None, cc=None, bcc=None, subject="", body="",
            remove_attachments=None, uploads=None, quoted_html=None) -> dict:
    if action not in ("send", "draft"):
        raise BadRequest("Unknown action.")
    if mode not in ("new",) + RESPONSE_MODES:
        raise BadRequest("Unknown compose mode.")
    to = _check_recipients(to or [], "To")
    cc = _check_recipients(cc or [], "Cc")
    bcc = _check_recipients(bcc or [], "Bcc")
    if action == "send" and not (to or cc or bcc):
        raise BadRequest("Add at least one recipient.")

    acc = imap_account.get_account()
    msg = EmailMessage()
    msg["From"] = formataddr((acc.get("name") or "", acc["email"]))
    if to:
        msg["To"] = ", ".join(to)
    if cc:
        msg["Cc"] = ", ".join(cc)
    if bcc:
        msg["Bcc"] = ", ".join(bcc)
    msg["Subject"] = subject[:255]
    msg["Date"] = format_datetime(datetime.now().astimezone())
    msg["Message-ID"] = make_msgid(domain=acc["email"].split("@")[-1])

    source = _parsed(source_id) if source_id and mode != "new" else None
    if source is not None and mode in ("reply", "replyall"):
        original_id = str(source.get("Message-ID") or "").strip()
        if original_id:
            msg["In-Reply-To"] = original_id
            refs = str(source.get("References") or "").split()
            msg["References"] = " ".join(refs[-20:] + [original_id])

    user_html = _text_to_html(body)
    if mode != "new":
        if not quoted_html and source is not None:
            quoted_html = _quote_block(source)
        html_body = _with_user_text(quoted_html or "<html><body></body></html>", user_html)
    else:
        html_body = f"<html><body>{user_html}</body></html>"
    msg.set_content(body or " ")
    msg.add_alternative(html_body, subtype="html")

    # Attachments carried over from the saved draft (or from the forwarded email).
    removed = set(remove_attachments or [])
    carried = []
    if draft_id:
        carried = _carry_attachments(_parsed(draft_id), None, removed)
    elif mode == "forward" and source is not None:
        carried = _carry_attachments(source, None, removed)
    elif source is not None:  # reply: keep only the inline images the quoted text shows
        carried = [p for p in _carry_attachments(source, set(), removed)]
    for part in carried:
        data = part.get_payload(decode=True) or b""
        maintype, subtype = part.get_content_type().split("/", 1)
        cid = part.get("Content-ID")
        if cid and f"cid:{cid.strip('<>').lower()}" in html_body.lower():
            msg.add_attachment(data, maintype=maintype, subtype=subtype, filename=part.get_filename(),
                               disposition="inline", cid=cid)
        else:
            msg.add_attachment(data, maintype=maintype, subtype=subtype,
                               filename=part.get_filename() or "attachment")
    for name, data in uploads or []:
        ctype = mimetypes.guess_type(name)[0] or "application/octet-stream"
        maintype, subtype = ctype.split("/", 1)
        msg.add_attachment(data, maintype=maintype, subtype=subtype, filename=_safe_filename(name))

    raw = msg.as_bytes(policy=email.policy.SMTP)
    c = _imap()
    if action == "send":
        smtp = imap_account.open_smtp(acc)
        try:
            smtp.send_message(msg, from_addr=acc["email"], to_addrs=to + cc + bcc)
        finally:
            try:
                smtp.quit()
            except Exception:
                pass
        # Keep a copy in Sent Items, like Outlook does for IMAP accounts.
        try:
            c.append(_folder_name("sentitems"), raw, flags=[imapclient.SEEN])
        except (NotFound, IMAPClientError):
            log.warning("Sent, but couldn't save a copy to Sent Items")
        if source is not None and mode in ("reply", "replyall"):
            try:
                _set_flag(source_id, imapclient.ANSWERED, True)
            except (NotFound, IMAPClientError):
                pass
        if draft_id:
            _delete_quietly(draft_id)
        return {"status": "sent", "messageIdHeader": str(msg["Message-ID"] or "")}

    drafts = _folder_name("drafts")
    resp = c.append(drafts, raw, flags=[imapclient.DRAFT, imapclient.SEEN])
    new_id = _find_appended(drafts, resp, msg["Message-ID"])
    if draft_id:
        _delete_quietly(draft_id)  # IMAP messages can't be edited: the new copy replaces the old draft
    infos = _attachment_infos(email.message_from_bytes(raw, policy=email.policy.default), html_body)
    return {"status": "saved", "draftId": new_id,
            "attachments": [{"id": a["id"], "name": a["name"], "size": a["size"]} for a in infos if not a["inline"]]}


def _delete_quietly(message_id: str) -> None:
    try:
        delete_message(message_id, permanent=True)
    except NotFound:
        pass


def _find_appended(folder: str, append_response: bytes, message_id_header: str) -> str:
    validity = _select(folder, readonly=True)
    m = re.search(rb"APPENDUID \d+ (\d+)", append_response or b"")
    if m:
        uid = int(m.group(1))
    else:
        found = _imap().search(["HEADER", "Message-ID", message_id_header])
        if not found:
            raise OutlookError("The draft was saved, but couldn't be found again. Check your Drafts folder.")
        uid = max(found)
    return _make_id(folder, validity, uid)


_BAD_FILENAME_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def _safe_filename(name: str) -> str:
    name = (name or "").replace("\\", "/").rsplit("/", 1)[-1]
    name = _BAD_FILENAME_CHARS.sub("_", name).strip(" .")
    return name[:150] or "attachment"


# ---------------------------------------------------------------------------
# Task finder input
# ---------------------------------------------------------------------------


def _for_tasks(message_id: str, data: dict, text: str, me: str) -> dict:
    h = _headers(data)
    to_addrs = {p["address"].lower() for p in _people(str(h.get("To") or ""))}
    return {
        "id": message_id,
        "subject": str(h.get("Subject") or "").strip(),
        "from": _person(str(h.get("From") or "")),
        "receivedDateTime": _iso_local(data.get(b"INTERNALDATE")),
        "text": text[:20000],
        "toMe": (me in to_addrs) if to_addrs else True,
    }


# Emails already read for task suggestions, kept in memory only (never on disk): a re-scan then downloads
# just the emails that arrived since, so the Tasks page can check for new requests every minute.
_TASK_MSG_CACHE: "OrderedDict[tuple[int, int], dict]" = OrderedDict()
_TASK_MSG_CACHE_MAX = 300


def recent_messages_for_tasks(days: int = 7, limit: int = 40) -> list[dict]:
    validity = _select("INBOX", readonly=True)
    since = date.today() - timedelta(days=days)
    uids = sorted(_imap().search(["SINCE", since]), reverse=True)[:limit]
    if not uids:
        return []
    new = [u for u in uids if (validity, u) not in _TASK_MSG_CACHE]
    if new:
        fetched = _imap().fetch(new, ["INTERNALDATE", "BODYSTRUCTURE", HEADER_FIELDS])
        texts = _fetch_texts(new, {u: d.get(b"BODYSTRUCTURE") for u, d in fetched.items()}, 20000)
        me = _my_address()
        for u in new:
            if u in fetched:
                _TASK_MSG_CACHE[(validity, u)] = _for_tasks(_make_id("INBOX", validity, u), fetched[u], texts.get(u, ""), me)
        while len(_TASK_MSG_CACHE) > _TASK_MSG_CACHE_MAX:
            _TASK_MSG_CACHE.popitem(last=False)
    return [_TASK_MSG_CACHE[(validity, u)] for u in uids if (validity, u) in _TASK_MSG_CACHE]


def get_message_for_tasks(message_id: str) -> dict:
    _folder, uid = _open(message_id)
    data = _imap().fetch([uid], ["INTERNALDATE", "BODYSTRUCTURE", HEADER_FIELDS]).get(uid)
    if not data:
        raise NotFound("That email no longer exists.")
    text = _fetch_texts([uid], {uid: data.get(b"BODYSTRUCTURE")}, 20000).get(uid, "")
    return _for_tasks(message_id, data, text, _my_address())


# Sent emails already read for Given tasks (memory only, like the Inbox cache above).
_SENT_TASK_CACHE: "OrderedDict[tuple[int, int], dict]" = OrderedDict()


def sync_given_tasks(days: int = 30, limit: int = 100) -> int:
    """Task emails you sent from anywhere (this dashboard, Outlook, your phone) -> Tasks > Given.
    Reads Sent Items; each sent email is added once (by its Message-ID). Returns how many were added."""
    import task_finder

    folder = _folder_name("sentitems")
    validity = _select(folder, readonly=True)
    since = date.today() - timedelta(days=days)
    uids = sorted(_imap().search(["SINCE", since]), reverse=True)[:limit]
    new = [u for u in uids if (validity, u) not in _SENT_TASK_CACHE]
    if new:
        fetched = _imap().fetch(new, ["INTERNALDATE", "BODYSTRUCTURE", HEADER_FIELDS])
        texts = _fetch_texts(new, {u: d.get(b"BODYSTRUCTURE") for u, d in fetched.items()}, 20000)
        for u in new:
            if u not in fetched:
                continue
            h = _headers(fetched[u])
            msg = _for_tasks(_make_id(folder, validity, u), fetched[u], texts.get(u, ""), "")
            msg["toMe"] = True  # read as if addressed to the recipient
            msg["to"] = [p for p in _people(str(h.get("To") or "")) if p.get("address")]
            msg["messageIdHeader"] = str(h.get("Message-ID") or "").strip() or f"{folder}:{validity}:{u}"

            _SENT_TASK_CACHE[(validity, u)] = msg
        while len(_SENT_TASK_CACHE) > 300:
            _SENT_TASK_CACHE.popitem(last=False)
    known = tasks_store.source_keys()
    added = 0
    for u in uids:
        msg = _SENT_TASK_CACHE.get((validity, u))
        if not msg or not msg["to"]:
            continue
        for t in task_finder.given_from_sent(msg):
            key = f"{msg['messageIdHeader']}#{t['n']}"
            # n=0 also matches a task recorded when it was sent from this dashboard (key = bare Message-ID)
            if key in known or (t["n"] == 0 and msg["messageIdHeader"] in known):
                continue
            tasks_store.create_task(
                title=t["title"], due=t["due"], importance=t["importance"], notes=msg["subject"][:300],
                direction="given", person=", ".join(p.get("name") or p["address"].split("@")[0] for p in msg["to"]),
                person_address=", ".join(p["address"] for p in msg["to"]), source_key=key,
            )
            known.add(key)
            added += 1
    return added


# ---------------------------------------------------------------------------
# Tasks: local dashboard task list (IMAP servers have no task store)
# ---------------------------------------------------------------------------

list_tasks = tasks_store.list_tasks
create_task = tasks_store.create_task
set_task_completed = tasks_store.set_task_completed


# ---------------------------------------------------------------------------
# "Write for me": people you email, and turning a short note into an email
# ---------------------------------------------------------------------------

CONTACT_SCAN = 800  # newest emails per folder whose From/To/Cc headers are read


def _contact_book() -> dict:
    def load():
        rows = []
        folders = [("inbox", "INBOX")]
        try:
            folders.append(("sent", _folder_name("sentitems")))
        except NotFound:
            pass
        field = "BODY.PEEK[HEADER.FIELDS (FROM TO CC)]"
        for kind, folder in folders:
            _select(folder, readonly=True)
            uids = sorted(_imap().search(["ALL"]))[-CONTACT_SCAN:]
            for i in range(0, len(uids), 400):
                for _uid, data in _imap().fetch(uids[i: i + 400], [field]).items():
                    h = _headers(data)
                    rows.append((kind, {k: str(h.get(k) or "") for k in ("From", "To", "Cc")}))
        return contacts.build(rows, _my_address())

    return contacts.cached(load)


def search_contacts(q: str = "") -> dict:
    return {"contacts": contacts.search(q, _contact_book()["people"])}


def _default_name() -> str:
    acc = imap_account.get_account()
    for name in ((acc.get("name") or "").strip(), _contact_book().get("myName") or ""):
        if name and "@" not in name:
            return name
    return ""


def get_signature() -> dict:
    return contacts.get_signature(_default_name())


def save_signature(values: dict) -> dict:
    return contacts.save_signature(values)


SIGN_OFF = re.compile(r"\n\s*(?:best regards|kind regards|warm regards|regards|sincerely|yours sincerely|yours faithfully|"
                      r"thanks (?:and|&) regards|thank you and regards)\b[\s\S]*$", re.I)


def write_email(note: str, choices: dict | None = None, remember: bool = True, polish: bool = False,
                task: dict | None = None) -> dict:
    """note -> {subject, body, intent, to:[resolved], cc:[resolved], ready}.
    choices: {"to": [{"phrase", "address"}], "cc": [...]} picked by the user in the dialog.
    task: {"due": "YYYY-MM-DD" | None, "importance": "normal" | "high"} -> write a task assignment instead."""
    note = (note or "").strip()
    if polish:
        # Polishing typed email text: drop an existing sign-off/signature (a previous polish, or typed by hand).
        note = SIGN_OFF.sub("", "\n" + note).strip()
    if not note:
        raise BadRequest("Write what the email should say.")
    if len(note) > 5000:
        raise BadRequest("Please keep the text under 5000 characters.")
    # Roman Urdu / Hindi / any language -> English first (English lines stay as typed and stay on this PC).
    note, lang = translate.to_english(note)
    book = _contact_book()
    people = book["people"]
    task_parsed = writer.task_parse(note) if task is not None else None
    parsed = ({"to": task_parsed["to"], "cc": task_parsed["cc"], "action": task_parsed["title"]}
              if task_parsed else writer.parse(note))
    if not parsed["action"].strip():
        raise BadRequest("Add what the email should say, not only who it goes to.")

    def side(key):
        if choices is not None:
            picked = []
            for c in choices.get(key) or []:
                addr = str(c.get("address") or "").strip()
                if not addr:
                    continue
                if not EMAIL_RE.match(addr):
                    raise BadRequest(f"'{addr}' is not a full email address.")
                phrase = str(c.get("phrase") or "").strip()
                known = people.get(addr.lower(), {})
                if remember and phrase and phrase.lower() != addr.lower():
                    contacts.remember(phrase, addr)
                picked.append({"phrase": phrase or addr, "address": addr, "name": known.get("name", ""), "candidates": []})
            return picked
        return [contacts.resolve(p, people) for p in parsed[key]]

    to, cc = side("to"), side("cc")
    names = [writer.greet_name(r["phrase"], r["name"]) for r in to]
    sig = get_signature()
    try:
        if task_parsed:
            due = str(task.get("due") or "") or None
            if due and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", due):
                raise BadRequest("Invalid due date.")
            out = writer.task_email(note, names, sig, due=due, importance=str(task.get("importance") or "normal"),
                                    parsed=task_parsed)
            out["task"]["people"] = [{"name": n, "address": r["address"]} for n, r in zip(names, to)]
        else:
            out = writer.write(note, names, sig, parsed=parsed, polish=polish)
    except ValueError:
        raise BadRequest("Add what the email should say.")
    ready = all(r["address"] for r in to + cc)
    return {**out, "to": to, "cc": cc, "ready": ready, "signature": sig, **lang}
