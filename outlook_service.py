"""
All Outlook COM automation lives in this file.

Talks to the classic Outlook desktop app that is already running and signed in,
through Outlook.Application / the MAPI namespace (pywin32). No cloud, no Azure.

Rules followed here:
- Callers must go through `run(fn, ...)`, which does CoInitialize/CoUninitialize per call.
- Sorting/filtering uses Items.Restrict + Items.Sort, never a loop over every email.
- Nothing in this module prints or stores email content.
"""

from __future__ import annotations

import gc
import html
import mimetypes
import os
import re
import shutil
import subprocess
import tempfile
import threading
import time
from datetime import datetime, timedelta, timezone

import pythoncom
import pywintypes
import win32com.client

# ---------------------------------------------------------------------------
# Outlook constants (hard-coded so we don't need a generated type library cache)
# ---------------------------------------------------------------------------

DEFAULT_FOLDERS = {
    "inbox": 6,         # olFolderInbox
    "sentitems": 5,     # olFolderSentMail
    "drafts": 16,       # olFolderDrafts
    "deleteditems": 3,  # olFolderDeletedItems
    "outbox": 4,        # olFolderOutbox
    "junkemail": 23,    # olFolderJunk
}

OL_FLAG_MARKED = 2
IMPORTANCE = {0: "low", 1: "normal", 2: "high"}

PAGE_SIZE_DEFAULT = 50
PAGE_SIZE_MAX = 200
PREVIEW_CHARS = 160

# DASL property names used with Items.Restrict("@SQL=...")
DASL_READ = "urn:schemas:httpmail:read"
DASL_HAS_ATTACH = "urn:schemas:httpmail:hasattachment"
DASL_SUBJECT = "urn:schemas:httpmail:subject"
DASL_FROM_NAME = "urn:schemas:httpmail:fromname"
DASL_FROM_EMAIL = "urn:schemas:httpmail:fromemail"
DASL_RECEIVED = "urn:schemas:httpmail:datereceived"
DASL_FLAG_STATUS = "http://schemas.microsoft.com/mapi/proptag/0x10900003"  # PR_FLAG_STATUS
# Restrict() on PR_FLAG_STATUS alone misses flagged items in Exchange mailboxes;
# PR_TODO_ITEM_FLAGS (1 = marked for follow-up) is what Outlook actually indexes.
DASL_TODO_FLAGS = "http://schemas.microsoft.com/mapi/proptag/0x0E2B0003"

# MAPI properties read through PropertyAccessor
PR_SMTP_ADDRESS = "http://schemas.microsoft.com/mapi/proptag/0x39FE001F"
PR_ATTACH_DATA_BIN = "http://schemas.microsoft.com/mapi/proptag/0x37010102"
PR_ATTACH_CONTENT_ID = "http://schemas.microsoft.com/mapi/proptag/0x3712001F"
PR_ATTACH_MIME_TAG = "http://schemas.microsoft.com/mapi/proptag/0x370E001F"

OL_BY_VALUE = 1
OL_EMBEDDED_ITEM = 5
OL_MARK_NO_DATE = 4  # MarkAsTask interval for a plain flag with no due date
OL_FORMAT_PLAIN = 1
RECIPIENT_TYPES = {1: "to", 2: "cc", 3: "bcc"}
EXCHANGE_ENTRY_TYPES = {0, 5}  # olExchangeUserAddressEntry, olExchangeRemoteUserAddressEntry

ENTRY_ID_RE = re.compile(r"^[0-9A-Fa-f]{16,1024}$")

# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


from errors import (  # noqa: E402  (shared with graph_service)
    BadRequest,
    NotFound,
    OutlookBusy,
    OutlookError,
    OutlookNotInstalled,
    OutlookNotRunning,
    OutlookPermissionDenied,
)


# HRESULTs we translate into friendly errors
CO_E_CLASSSTRING = -2147221005          # class not registered -> Outlook not installed
REGDB_E_CLASSNOTREG = -2147221164
CO_E_SERVER_EXEC_FAILURE = -2146959355  # usually admin/non-admin mismatch
RPC_E_CALL_REJECTED = -2147418111       # Outlook busy (dialog open)
RPC_E_SERVERCALL_RETRYLATER = -2147417846
RPC_S_SERVER_UNAVAILABLE = -2147023174  # Outlook closed mid-session
RPC_S_CALL_FAILED = -2147023170
E_ABORT = -2147467260                   # user clicked "Deny" on a security prompt
E_ACCESSDENIED = -2147024891
MAPI_E_NOT_FOUND = -2147221233
MAPI_E_NO_ACCESS = -2147024891
DISP_E_EXCEPTION = -2147352567

NOT_RUNNING_MSG = (
    "Outlook isn't running. Open the classic Outlook desktop app (not \"New Outlook\"), "
    "make sure it's signed in to your work account, then click Retry."
)


def _hresults(err: pywintypes.com_error) -> set[int]:
    """Return the outer HRESULT plus the inner scode from excepinfo, if any."""
    codes = {err.args[0]} if err.args else set()
    excepinfo = err.args[2] if len(err.args) > 2 else None
    if excepinfo and len(excepinfo) > 5 and isinstance(excepinfo[5], int):
        codes.add(excepinfo[5])
    return codes


def translate_com_error(err: pywintypes.com_error) -> OutlookError:
    codes = _hresults(err)
    if codes & {CO_E_CLASSSTRING, REGDB_E_CLASSNOTREG}:
        return OutlookNotInstalled(
            "Classic Outlook doesn't seem to be installed. This dashboard needs the classic Outlook "
            "desktop app — \"New Outlook\" and Outlook on the web don't support automation."
        )
    if CO_E_SERVER_EXEC_FAILURE in codes:
        return OutlookNotRunning(
            "Couldn't connect to Outlook. This usually happens when Outlook and the dashboard run with "
            "different permissions — start both normally (not \"Run as administrator\"), or both as administrator."
        )
    if codes & {RPC_S_SERVER_UNAVAILABLE, RPC_S_CALL_FAILED}:
        return OutlookNotRunning(NOT_RUNNING_MSG)
    if codes & {RPC_E_CALL_REJECTED, RPC_E_SERVERCALL_RETRYLATER}:
        return OutlookBusy(
            "Outlook is busy — it may have a dialog box open. Switch to Outlook, close any open dialogs, then retry."
        )
    if E_ABORT in codes:
        return OutlookPermissionDenied(
            "Outlook blocked access (the security prompt was denied). Click Retry and choose \"Allow\" "
            "in Outlook's prompt, or ask IT to check Outlook's Programmatic Access settings."
        )
    if E_ACCESSDENIED in codes:
        return OutlookPermissionDenied("Outlook denied access to that item.")
    if MAPI_E_NOT_FOUND in codes:
        return NotFound("That item or folder no longer exists. It may have been moved or deleted.")
    return OutlookError("Outlook returned an unexpected error. Please try again.")


# ---------------------------------------------------------------------------
# Connection
# ---------------------------------------------------------------------------

# Outlook's object model is effectively single-threaded; serialize our calls to avoid "busy" errors.
_outlook_lock = threading.RLock()

_running_cache: tuple[float, bool] = (0.0, False)


def is_outlook_running() -> bool:
    """Checks the process list (cached for 3 s) so we never launch Outlook by accident."""
    global _running_cache
    checked_at, running = _running_cache
    if time.monotonic() - checked_at < 3:
        return running
    try:
        out = subprocess.run(
            ["tasklist", "/FI", "IMAGENAME eq OUTLOOK.EXE", "/NH", "/FO", "CSV"],
            capture_output=True,
            text=True,
            timeout=5,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        ).stdout
        running = "OUTLOOK.EXE" in out.upper()
    except Exception:
        running = False
    _running_cache = (time.monotonic(), running)
    return running


def run(fn, *args, **kwargs):
    """
    Runs fn(*args, **kwargs) in a COM session: CoInitialize -> call -> CoUninitialize.

    Every Outlook COM object must be released *before* CoUninitialize, or the process can
    crash with an access violation. Exceptions keep the failing frames (and the COM objects
    in them) alive through their tracebacks, so errors are converted to fresh, traceback-free
    exceptions inside the session and only raised after it has been closed.
    """
    error: OutlookError | None = None
    pythoncom.CoInitialize()
    try:
        with _outlook_lock:
            try:
                return fn(*args, **kwargs)
            except OutlookError as err:
                error = type(err)(err.message)
            except pywintypes.com_error as err:
                error = translate_com_error(err)
            except Exception as err:  # unexpected bug: report its type only, never data
                error = OutlookError(f"Unexpected error ({type(err).__name__}). Please try again.")
            # Leaving the except block drops `err` and its traceback; collect any cycles too.
            gc.collect()
    finally:
        pythoncom.CoUninitialize()
    raise error


def _application():
    """Attach to the running Outlook instance (never starts a new one)."""
    if not is_outlook_running():
        raise OutlookNotRunning(NOT_RUNNING_MSG)
    # Retry briefly if Outlook is momentarily busy (e.g. just started).
    for attempt in range(3):
        try:
            return win32com.client.Dispatch("Outlook.Application")
        except pywintypes.com_error as err:
            if attempt < 2 and _hresults(err) & {RPC_E_CALL_REJECTED, RPC_E_SERVERCALL_RETRYLATER}:
                time.sleep(0.5 * (attempt + 1))
                continue
            raise


def _namespace():
    """The MAPI namespace of the running Outlook instance."""
    return _application().GetNamespace("MAPI")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get(obj, attr: str, default=None):
    """Read a COM property without failing the whole request if one item misbehaves."""
    try:
        value = getattr(obj, attr)
        return default if value is None else value
    except Exception:
        return default


def _iso(value) -> str | None:
    """pywin32 returns Outlook times as local wall-clock time tagged as UTC; fix that."""
    if not value:
        return None
    try:
        naive = datetime(value.year, value.month, value.day, value.hour, value.minute, value.second)
        if naive.year < 1990 or naive.year > 4000:  # Outlook uses 4501-01-01 for "none"
            return None
        return naive.astimezone().isoformat()
    except Exception:
        return None


def _dasl_date(day: str, end_of_day: bool) -> str:
    """'YYYY-MM-DD' (local calendar day) -> UTC string for a DASL comparison."""
    try:
        d = datetime.strptime(day, "%Y-%m-%d")
    except ValueError:
        raise BadRequest(f"Invalid date: {day!r}. Use YYYY-MM-DD.") from None
    if end_of_day:
        d = d.replace(hour=23, minute=59, second=59)
    return d.astimezone().astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def _dasl_text(value: str) -> str:
    return value.replace("'", "''")


def _preview(item) -> str:
    body = _get(item, "Body", "") or ""
    # Only the first chunk is used; collapse whitespace for a one-line preview.
    return re.sub(r"\s+", " ", body[: PREVIEW_CHARS * 3]).strip()[:PREVIEW_CHARS]


def _sender(item) -> dict | None:
    name = _get(item, "SenderName", "") or ""
    address = ""
    if _get(item, "SenderEmailType", "") == "SMTP":
        address = _get(item, "SenderEmailAddress", "") or ""
    if not name and not address:
        return None
    return {"name": name or address, "address": address}


def _received(item) -> str | None:
    return _iso(_get(item, "ReceivedTime")) or _iso(_get(item, "SentOn")) or _iso(_get(item, "CreationTime"))


def _summary(item) -> dict:
    attachments = _get(item, "Attachments")
    categories = _get(item, "Categories", "") or ""
    return {
        "id": _get(item, "EntryID", ""),
        "conversationId": _get(item, "ConversationID", "") or "",
        "subject": (_get(item, "Subject", "") or "").strip() or "(no subject)",
        "preview": _preview(item),
        "from": _sender(item),
        "receivedDateTime": _received(item),
        "isRead": not bool(_get(item, "UnRead", False)),
        "hasAttachments": bool(attachments is not None and _get(attachments, "Count", 0) > 0),
        "flagged": _get(item, "FlagStatus", 0) == OL_FLAG_MARKED,
        "importance": IMPORTANCE.get(_get(item, "Importance", 1), "normal"),
        "categories": [c.strip() for c in categories.split(",") if c.strip()],
    }


def _resolve_folder(ns, folder: str):
    """Accepts a well-known name (inbox, sentitems, drafts, ...) or a folder EntryID."""
    key = (folder or "inbox").lower()
    if key in DEFAULT_FOLDERS:
        return ns.GetDefaultFolder(DEFAULT_FOLDERS[key])
    try:
        return ns.GetFolderFromID(folder)
    except pywintypes.com_error:
        raise NotFound("That folder couldn't be found. It may have been renamed, moved or deleted.") from None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def get_status() -> dict:
    """Confirms Outlook is reachable and returns the signed-in account."""
    ns = _namespace()
    user = ""
    try:
        user = ns.CurrentUser.Name or ""
    except Exception:
        pass
    accounts = []
    try:
        for i in range(1, ns.Accounts.Count + 1):
            accounts.append(ns.Accounts.Item(i).SmtpAddress)
    except Exception:
        pass
    return {"connected": True, "user": user, "accounts": accounts}


def get_folder_summary(folder: str = "inbox") -> dict:
    ns = _namespace()
    f = _resolve_folder(ns, folder)
    return {
        "id": f.EntryID,
        "key": folder.lower() if folder.lower() in DEFAULT_FOLDERS else None,
        "name": f.Name,
        "unreadCount": int(_get(f, "UnReadItemCount", 0)),
        "totalCount": int(_get(f.Items, "Count", 0)),
    }


def list_messages(
    folder: str = "inbox",
    start: int = 0,
    limit: int = PAGE_SIZE_DEFAULT,
    search: str | None = None,
    unread: bool = False,
    flagged: bool = False,
    has_attachments: bool = False,
    date_from: str | None = None,
    date_to: str | None = None,
) -> dict:
    """
    Newest-first page of emails in a folder.
    Filters are applied with Items.Restrict (DASL) and ordering with Items.Sort, so Outlook
    does the work instead of Python looping over the whole folder.
    """
    start = max(0, int(start))
    limit = max(1, min(int(limit), PAGE_SIZE_MAX))

    ns = _namespace()
    items = _resolve_folder(ns, folder).Items

    clauses: list[str] = []
    if unread:
        clauses.append(f'"{DASL_READ}" = 0')
    if flagged:
        clauses.append(f'("{DASL_TODO_FLAGS}" = 1 OR "{DASL_FLAG_STATUS}" = 2)')
    if has_attachments:
        clauses.append(f'"{DASL_HAS_ATTACH}" = 1')
    if date_from:
        clauses.append(f"\"{DASL_RECEIVED}\" >= '{_dasl_date(date_from, False)}'")
    if date_to:
        clauses.append(f"\"{DASL_RECEIVED}\" <= '{_dasl_date(date_to, True)}'")
    if search:
        term = _dasl_text(search.strip()[:200])
        clauses.append(
            "("
            + " OR ".join(f"\"{p}\" LIKE '%{term}%'" for p in (DASL_SUBJECT, DASL_FROM_NAME, DASL_FROM_EMAIL))
            + ")"
        )

    if clauses:
        try:
            items = items.Restrict("@SQL=" + " AND ".join(clauses))
        except pywintypes.com_error:
            raise BadRequest("Outlook couldn't apply that search or filter. Try simpler search text.") from None

    items.Sort("[ReceivedTime]", True)  # newest first
    total = int(items.Count)

    messages = []
    end = min(start + limit, total)
    for index in range(start + 1, end + 1):  # COM collections are 1-based
        try:
            messages.append(_summary(items.Item(index)))
        except pywintypes.com_error:
            continue  # item deleted or inaccessible while we were reading; skip it

    return {
        "messages": messages,
        "total": total,
        "start": start,
        "nextStart": end if end < total else None,
    }


# ---------------------------------------------------------------------------
# Single message: reading pane, attachments, actions
# ---------------------------------------------------------------------------


def _get_item(ns, message_id: str):
    if not ENTRY_ID_RE.match(message_id or ""):
        raise BadRequest("Invalid message id.")
    try:
        return ns.GetItemFromID(message_id)
    except pywintypes.com_error as err:
        translated = translate_com_error(err)
        if isinstance(translated, (OutlookNotRunning, OutlookBusy, OutlookPermissionDenied)):
            raise translated from None
        raise NotFound("That email no longer exists. It may have been moved or deleted.") from None


def _prop(accessor, name: str):
    try:
        return accessor.GetProperty(name)
    except Exception:
        return None


def _smtp_from_entry(entry, fallback: str = "") -> str:
    """Resolves an AddressEntry to an SMTP address (Exchange users have X.500 addresses otherwise)."""
    if entry is None:
        return fallback
    try:
        if _get(entry, "AddressEntryUserType", -1) in EXCHANGE_ENTRY_TYPES:
            user = entry.GetExchangeUser()
            if user is not None and user.PrimarySmtpAddress:
                return user.PrimarySmtpAddress
        address = _get(entry, "Address", "") or ""
        return address if "@" in address else fallback
    except Exception:
        return fallback


def _full_sender(item) -> dict | None:
    name = _get(item, "SenderName", "") or ""
    if _get(item, "SenderEmailType", "") == "SMTP":
        address = _get(item, "SenderEmailAddress", "") or ""
    else:
        address = _smtp_from_entry(_get(item, "Sender"))
    if not name and not address:
        return None
    return {"name": name or address, "address": address}


def _recipients(item) -> dict:
    out = {"to": [], "cc": [], "bcc": []}
    recipients = _get(item, "Recipients")
    if recipients is None:
        return out
    for i in range(1, _get(recipients, "Count", 0) + 1):
        try:
            r = recipients.Item(i)
            kind = RECIPIENT_TYPES.get(_get(r, "Type", 1), "to")
            address = _prop(r.PropertyAccessor, PR_SMTP_ADDRESS) or ""
            if not address:
                raw = _get(r, "Address", "") or ""
                address = raw if "@" in raw else _smtp_from_entry(_get(r, "AddressEntry"))
            out[kind].append({"name": _get(r, "Name", "") or address, "address": address})
        except pywintypes.com_error:
            continue
    return out


def _attachment_name(att) -> str:
    name = _get(att, "FileName", "") or _get(att, "DisplayName", "") or "attachment"
    if _get(att, "Type") == OL_EMBEDDED_ITEM and not name.lower().endswith(".msg"):
        name += ".msg"
    return name


def _attachments(item, html: str) -> list[dict]:
    out = []
    atts = _get(item, "Attachments")
    if atts is None:
        return out
    html_lower = html.lower()
    for i in range(1, _get(atts, "Count", 0) + 1):
        try:
            a = atts.Item(i)
            name = _attachment_name(a)
            pa = _get(a, "PropertyAccessor")
            cid = ((_prop(pa, PR_ATTACH_CONTENT_ID) if pa else None) or "").strip().strip("<>")
            mime = (_prop(pa, PR_ATTACH_MIME_TAG) if pa else None) or mimetypes.guess_type(name)[0] or "application/octet-stream"
            out.append({
                "index": i,
                "name": name,
                "size": int(_get(a, "Size", 0) or 0),
                "mimeType": mime,
                "contentId": cid,
                # Inline = an image the HTML body references via cid:, so it isn't listed as a file.
                "inline": bool(cid) and f"cid:{cid.lower()}" in html_lower,
            })
        except pywintypes.com_error:
            continue
    return out


def get_message(message_id: str) -> dict:
    """Full email for the reading pane. HTML is returned as-is; the browser shows it in a sandboxed iframe."""
    ns = _namespace()
    item = _get_item(ns, message_id)

    is_plain = _get(item, "BodyFormat", 2) == OL_FORMAT_PLAIN
    html = "" if is_plain else (_get(item, "HTMLBody", "") or "")
    text = (_get(item, "Body", "") or "") if is_plain or not html else ""

    detail = _summary(item)
    detail.update({
        "from": _full_sender(item),
        "recipients": _recipients(item),
        "sentDateTime": _iso(_get(item, "SentOn")),
        "bodyType": "html" if html else "text",
        "body": html or text,
        "attachments": _attachments(item, html),
        "messageClass": _get(item, "MessageClass", "") or "",
    })
    detail.pop("preview", None)
    return detail


def get_attachment(message_id: str, index: int) -> tuple[str, str, bytes]:
    """
    Returns (filename, mime type, bytes). Reads the bytes straight from MAPI when possible.
    Otherwise Outlook must save to a file: we use a private temp folder and delete it immediately.
    """
    ns = _namespace()
    item = _get_item(ns, message_id)
    atts = item.Attachments
    if not 1 <= index <= atts.Count:
        raise NotFound("That attachment no longer exists.")
    a = atts.Item(index)
    name = _attachment_name(a)
    pa = _get(a, "PropertyAccessor")
    mime = (_prop(pa, PR_ATTACH_MIME_TAG) if pa else None) or mimetypes.guess_type(name)[0] or "application/octet-stream"

    data = None
    if _get(a, "Type") == OL_BY_VALUE and pa is not None:
        raw = _prop(pa, PR_ATTACH_DATA_BIN)
        if raw is not None:
            data = bytes(raw)
    if data is None:
        tmp_dir = tempfile.mkdtemp(prefix="outlook-dashboard-")
        try:
            path = os.path.join(tmp_dir, "attachment")
            a.SaveAsFile(path)
            with open(path, "rb") as fh:
                data = fh.read()
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)
    return name, mime, data


def set_read(message_id: str, read: bool) -> dict:
    item = _get_item(_namespace(), message_id)
    if bool(_get(item, "UnRead", False)) == read:  # only write when it changes
        item.UnRead = not read
        item.Save()
    return {"id": message_id, "isRead": read}


def set_flag(message_id: str, flagged: bool) -> dict:
    item = _get_item(_namespace(), message_id)
    try:
        if flagged:
            item.MarkAsTask(OL_MARK_NO_DATE)
        else:
            item.ClearTaskFlag()
        item.Save()
    except pywintypes.com_error as err:
        translated = translate_com_error(err)
        if type(translated) is OutlookError:
            raise BadRequest("This type of item can't be flagged.") from None
        raise translated from None
    return {"id": message_id, "flagged": _get(item, "FlagStatus", 0) == OL_FLAG_MARKED}


def delete_message(message_id: str, permanent: bool = False) -> dict:
    """Moves the email to Deleted Items (same as pressing Delete in Outlook).
    `permanent` exists for API parity with the Graph backend; this backend never creates
    drafts automatically, so a normal delete is always appropriate here."""
    item = _get_item(_namespace(), message_id)
    item.Delete()
    return {"id": message_id, "deleted": True}


# ---------------------------------------------------------------------------
# Compose: new mail, reply, reply all, forward, drafts
# ---------------------------------------------------------------------------

OL_MAIL_ITEM = 0
OL_DISCARD = 1
RESPONSE_MODES = ("reply", "replyall", "forward")
COMPOSE_MODES = ("new",) + RESPONSE_MODES
MAX_RECIPIENTS = 500
_BAD_FILENAME_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def _make_response(source, mode: str):
    try:
        if mode == "reply":
            return source.Reply()
        if mode == "replyall":
            return source.ReplyAll()
        return source.Forward()
    except pywintypes.com_error as err:
        translated = translate_com_error(err)
        if type(translated) is OutlookError:
            raise BadRequest("This item can't be replied to or forwarded.") from None
        raise translated from None


def _discard(item) -> None:
    """Closes an unsaved compose item without saving (Outlook's olDiscard)."""
    try:
        item.Close(OL_DISCARD)
    except Exception:
        pass


def _file_attachments(item) -> list[dict]:
    """Attachments the user would see as files (excludes inline images used by the HTML body)."""
    body = _get(item, "HTMLBody", "") or ""
    return [{"name": a["name"], "size": a["size"]} for a in _attachments(item, body) if not a["inline"]]


def get_compose_prefill(source_id: str, mode: str) -> dict:
    """What a reply / reply all / forward would contain, without saving anything."""
    if mode not in RESPONSE_MODES:
        raise BadRequest("Unknown compose mode.")
    response = _make_response(_get_item(_namespace(), source_id), mode)
    try:
        recipients = _recipients(response)
        return {
            "mode": mode,
            "sourceId": source_id,
            "to": recipients["to"],
            "cc": recipients["cc"],
            "subject": _get(response, "Subject", "") or "",
            "quotedHtml": _get(response, "HTMLBody", "") or "",
            "attachments": _file_attachments(response),
        }
    finally:
        _discard(response)


def _text_to_html(text: str) -> str:
    escaped = html.escape(text.replace("\r\n", "\n")).replace("\n", "<br>\n")
    return f'<div style="font-family:Calibri,Arial,sans-serif;font-size:11pt">{escaped}</div>'


def _with_user_text(quoted_html: str, user_html: str) -> str:
    """Puts the user's text at the top of Outlook's quoted reply/forward body."""
    block = user_html + "<br>"
    match = re.search(r"<body[^>]*>", quoted_html, flags=re.IGNORECASE)
    if not match:
        return block + quoted_html
    return quoted_html[: match.end()] + block + quoted_html[match.end():]


def _recipient_line(values: list[str]) -> str:
    cleaned = [v.strip() for v in values if v and v.strip()]
    if len(cleaned) > MAX_RECIPIENTS:
        raise BadRequest(f"Too many recipients (maximum {MAX_RECIPIENTS}).")
    return "; ".join(cleaned)


def safe_filename(name: str) -> str:
    """Keeps the user's file name (including non-English characters) but removes path tricks."""
    name = os.path.basename((name or "").replace("\\", "/"))
    name = _BAD_FILENAME_CHARS.sub("_", name).strip(" .")
    return name[:150] or "attachment"


def compose(
    action: str,
    mode: str = "new",
    source_id: str | None = None,
    draft_id: str | None = None,
    to: list[str] | None = None,
    cc: list[str] | None = None,
    bcc: list[str] | None = None,
    subject: str = "",
    body: str = "",
    remove_attachments: list[str] | None = None,
    uploads: list[tuple[str, bytes]] | None = None,
    quoted_html: str | None = None,  # unused here: Outlook rebuilds the quote itself
) -> dict:
    """
    action "send" sends the email; action "draft" saves it to Drafts.

    Passing draft_id updates that draft instead of creating a new item, so saving twice doesn't
    create duplicates. For replies/forwards Outlook rebuilds the quoted original from source_id
    each time and the user's text is placed above it.

    Uploaded files are written to a private temp folder only because Outlook's Attachments.Add
    needs a file path; the folder is deleted as soon as Outlook has copied them.
    """
    if action not in ("send", "draft"):
        raise BadRequest("Unknown action.")
    if mode not in COMPOSE_MODES:
        raise BadRequest("Unknown compose mode.")
    if mode in RESPONSE_MODES and not source_id:
        raise BadRequest("Missing the original email for this reply/forward.")

    to_line, cc_line, bcc_line = _recipient_line(to or []), _recipient_line(cc or []), _recipient_line(bcc or [])
    if action == "send" and not (to_line or cc_line or bcc_line):
        raise BadRequest("Add at least one recipient.")

    ns = _namespace()
    source = _get_item(ns, source_id) if mode in RESPONSE_MODES else None

    if draft_id:
        item = _get_item(ns, draft_id)
        if _get(item, "Sent", False) or not str(_get(item, "MessageClass", "")).startswith("IPM.Note"):
            raise BadRequest("That draft can't be edited any more.")
        is_new_item = False
    elif source is not None:
        item = _make_response(source, mode)
        is_new_item = True
    else:
        item = _application().CreateItem(OL_MAIL_ITEM)
        is_new_item = True

    tmp_dir = None
    finished = False
    try:
        item.To = to_line
        item.CC = cc_line
        item.BCC = bcc_line
        item.Subject = subject[:255]

        user_html = _text_to_html(body)
        if source is not None:
            if is_new_item:
                quoted = _get(item, "HTMLBody", "") or ""
            else:
                fresh = _make_response(source, mode)  # regenerate the quoted original for the draft
                try:
                    quoted = _get(fresh, "HTMLBody", "") or ""
                finally:
                    _discard(fresh)
            item.HTMLBody = _with_user_text(quoted, user_html)
        else:
            item.HTMLBody = f"<html><body>{user_html}</body></html>"

        # Attachments the user removed (e.g. from a forward or an earlier draft save)
        to_remove = list(remove_attachments or [])
        if to_remove:
            body_now = _get(item, "HTMLBody", "") or ""
            removable = {a["index"]: a["name"] for a in _attachments(item, body_now) if not a["inline"]}
            for index in sorted(removable, reverse=True):  # remove from the end so indexes stay valid
                if removable[index] in to_remove:
                    to_remove.remove(removable[index])
                    item.Attachments.Remove(index)

        if uploads:
            tmp_dir = tempfile.mkdtemp(prefix="outlook-dashboard-")
            for n, (name, data) in enumerate(uploads):
                folder = os.path.join(tmp_dir, str(n))  # one folder per file so equal names don't clash
                os.mkdir(folder)
                path = os.path.join(folder, safe_filename(name))
                with open(path, "wb") as fh:
                    fh.write(data)
                item.Attachments.Add(path)

        if action == "send":
            recipients = item.Recipients
            if not recipients.ResolveAll():
                unresolved = []
                for i in range(1, recipients.Count + 1):
                    r = recipients.Item(i)
                    if not _get(r, "Resolved", True):
                        unresolved.append(_get(r, "Name", "") or "?")
                raise BadRequest(
                    "Outlook couldn't find these recipients: " + ", ".join(unresolved[:10])
                    + ". Check the spelling or use full email addresses."
                )
            item.Send()
            finished = True
            return {"status": "sent"}

        item.Save()
        finished = True
        return {"status": "saved", "draftId": item.EntryID, "attachments": _file_attachments(item)}
    finally:
        if not finished:
            _discard(item)  # drop unsaved changes / the unsent new item
        if tmp_dir:
            shutil.rmtree(tmp_dir, ignore_errors=True)


# ---------------------------------------------------------------------------
# Tasks (Outlook Tasks folder - syncs to Microsoft To Do / New Outlook)
# ---------------------------------------------------------------------------

OL_TASK_ITEM = 3
OL_FOLDER_TASKS = 13
OL_TASK_COMPLETE = 2
OL_TASK_NOT_STARTED = 0
_LINK_PREFIX = "Outlook Dashboard email id: "


def recent_messages_for_tasks(days: int = 7, limit: int = 40) -> list[dict]:
    """Recent inbox mail with plain text, for the task finder. Nothing is stored."""
    since = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
    items = _namespace().GetDefaultFolder(DEFAULT_FOLDERS["inbox"]).Items
    items = items.Restrict(f"@SQL=\"{DASL_RECEIVED}\" >= '{_dasl_date(since, False)}'")
    items.Sort("[ReceivedTime]", True)
    out = []
    for i in range(1, min(items.Count, limit) + 1):
        try:
            it = items.Item(i)
            out.append({
                "id": it.EntryID,
                "subject": (_get(it, "Subject", "") or "").strip(),
                "from": _sender(it),
                "receivedDateTime": _received(it),
                "text": (_get(it, "Body", "") or "")[:20000],
                "toMe": True,
            })
        except pywintypes.com_error:
            continue
    return out


def get_message_for_tasks(message_id: str) -> dict:
    it = _get_item(_namespace(), message_id)
    return {
        "id": message_id,
        "subject": (_get(it, "Subject", "") or "").strip(),
        "from": _sender(it),
        "receivedDateTime": _received(it),
        "text": (_get(it, "Body", "") or "")[:20000],
        "toMe": True,
    }


def _task_dict(t) -> dict:
    body = _get(t, "Body", "") or ""
    link = re.search(re.escape(_LINK_PREFIX) + r"([0-9A-Fa-f]+)", body)
    due = _get(t, "DueDate")
    due_iso = _iso(due)
    return {
        "id": t.EntryID,
        "title": (_get(t, "Subject", "") or "").strip() or "(untitled task)",
        "completed": bool(_get(t, "Complete", False)),
        "due": due_iso[:10] if due_iso else None,
        "importance": IMPORTANCE.get(_get(t, "Importance", 1), "normal"),
        "createdDateTime": _iso(_get(t, "CreationTime")),
        "messageId": link.group(1) if link else None,
    }


def list_tasks(include_completed: bool = False) -> list[dict]:
    items = _namespace().GetDefaultFolder(OL_FOLDER_TASKS).Items
    if not include_completed:
        items = items.Restrict("[Complete] = False")
    out = []
    for i in range(1, min(items.Count, 300) + 1):
        try:
            out.append(_task_dict(items.Item(i)))
        except pywintypes.com_error:
            continue
    return out


def create_task(title: str, due: str | None = None, notes: str = "", message_id: str | None = None,
                importance: str = "normal") -> dict:
    title = (title or "").strip()[:255]
    if not title:
        raise BadRequest("A task needs a title.")
    task = _application().CreateItem(OL_TASK_ITEM)
    task.Subject = title
    if due:
        try:
            # pywin32 converts naive datetimes from local time to UTC, which moves a date-only
            # due date to the previous day east of UTC. Passing it as UTC keeps the calendar date.
            task.DueDate = datetime.strptime(due, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        except ValueError:
            raise BadRequest("Invalid due date. Use YYYY-MM-DD.") from None
    task.Importance = {"low": 0, "normal": 1, "high": 2}.get(importance, 1)
    body = notes.strip()
    if message_id:
        body = (body + "\n\n" if body else "") + _LINK_PREFIX + message_id
    task.Body = body
    task.Save()
    return _task_dict(task)


def set_task_completed(task_id: str, completed: bool) -> dict:
    t = _get_item(_namespace(), task_id)
    if completed:
        t.MarkComplete()
    else:
        t.Status = OL_TASK_NOT_STARTED
        t.Complete = False
    t.Save()
    return _task_dict(t)
