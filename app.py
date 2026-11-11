"""
Outlook Dashboard: local Flask server (http://127.0.0.1:5000 only).

Backend (see config.py / settings.json):
  imap    - your mail server directly over IMAP/SMTP. Works with New Outlook, classic Outlook, or neither.
  outlook - classic Outlook desktop app on this PC (COM).
"""

from __future__ import annotations

import io
import json
import logging
import sys
import threading
import webbrowser
from functools import wraps

from flask import Flask, Response, abort, jsonify, render_template, request, send_file

import categories
import config
import task_finder
from errors import BadRequest, OutlookError

if config.BACKEND == "outlook":
    import outlook_service as mail
else:
    import imap_account
    import imap_service as mail

HOST = "127.0.0.1"
PORT = 5000
ALLOWED_HOSTS = {f"127.0.0.1:{PORT}", f"localhost:{PORT}"}

app = Flask(__name__)
app.json.sort_keys = False
app.config["MAX_CONTENT_LENGTH"] = 30 * 1024 * 1024  # one compose request

# Werkzeug's per-request log lines include query strings (e.g. search text). Keep the console quiet.
logging.getLogger("werkzeug").setLevel(logging.WARNING)


@app.before_request
def guard_request():
    # Blocks DNS-rebinding: only accept requests addressed to this machine's loopback name.
    if request.host not in ALLOWED_HOSTS:
        abort(403)
    # Blocks cross-site requests: every state-changing API call must come from our own JavaScript.
    if request.path.startswith("/api/") and request.method not in ("GET", "HEAD", "OPTIONS"):
        if request.headers.get("X-Requested-With") != "outlook-dashboard":
            abort(403)


@app.after_request
def security_headers(resp):
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["X-Frame-Options"] = "DENY"
    resp.headers["Referrer-Policy"] = "no-referrer"
    if request.path.startswith("/api/"):
        resp.headers["Cache-Control"] = "no-store"
    return resp


def mail_api(fn):
    """Runs the handler through the backend's run() and turns errors into JSON."""

    @wraps(fn)
    def wrapper(*args, **kwargs):
        try:
            result = mail.run(fn, *args, **kwargs)
            return result if isinstance(result, Response) else jsonify(result)
        except OutlookError as err:
            app.logger.warning("Mail error: %s", err.code)  # code only, never email data
            return jsonify({"code": err.code, "message": err.message}), err.status
        except Exception as err:  # pragma: no cover - last-resort safety net
            app.logger.error("Unexpected error: %s", type(err).__name__)
            return jsonify({"code": "server_error", "message": "Something went wrong. Please try again."}), 500

    return wrapper


def _flag(name: str) -> bool:
    return request.args.get(name) in ("1", "true", "yes")


def _json() -> dict:
    body = request.get_json(silent=True)
    return body if isinstance(body, dict) else {}


def _json_bool(key: str) -> bool:
    value = _json().get(key)
    if not isinstance(value, bool):
        raise BadRequest(f"'{key}' must be true or false.")
    return value


# ---------------------------------------------------------------------------
# Pages
# ---------------------------------------------------------------------------


@app.get("/")
def index():
    return render_template("index.html", backend=config.BACKEND)


# ---------------------------------------------------------------------------
# Sign-in (IMAP backend only; classic Outlook needs none)
# ---------------------------------------------------------------------------


@app.get("/api/auth/status")
def api_auth_status():
    if config.BACKEND != "imap":
        return jsonify({"backend": config.BACKEND, "signedIn": True})
    return jsonify({"backend": "imap", **imap_account.status()})


@app.post("/api/auth/login")
def api_auth_login():
    if config.BACKEND != "imap":
        return jsonify({"backend": config.BACKEND, "signedIn": True})
    try:
        return jsonify({"backend": "imap", **imap_account.sign_in(_json())})
    except OutlookError as err:
        return jsonify({"code": err.code, "message": err.message}), err.status


@app.post("/api/auth/logout")
def api_auth_logout():
    if config.BACKEND != "imap":
        return jsonify({"backend": config.BACKEND, "signedIn": True})
    mail.run(lambda: mail._drop())
    return jsonify({"backend": "imap", **imap_account.sign_out()})


# ---------------------------------------------------------------------------
# Mail
# ---------------------------------------------------------------------------


@app.get("/api/status")
@mail_api
def api_status():
    return {**mail.get_status(), "backend": config.BACKEND}


def _need(name: str):
    fn = getattr(mail, name, None)
    if fn is None:
        raise BadRequest("Folders are only available when connected to the mail server (IMAP).")
    return fn


@app.get("/api/folders")
@mail_api
def api_folders():
    return _need("list_folders")()


@app.post("/api/folders")
@mail_api
def api_create_folder():
    body = _json()
    return _need("create_folder")(str(body.get("name") or ""), body.get("parent") or None)


@app.post("/api/folders/rename")
@mail_api
def api_rename_folder():
    body = _json()
    return _need("rename_folder")(str(body.get("folder") or ""), str(body.get("name") or ""))


@app.post("/api/folders/delete")
@mail_api
def api_delete_folder():
    return _need("delete_folder")(str(_json().get("folder") or ""))


@app.post("/api/messages/move")
@mail_api
def api_move_messages():
    body = _json()
    ids = body.get("ids")
    if not isinstance(ids, list) or not all(isinstance(x, str) for x in ids):
        raise BadRequest("'ids' must be a list of email ids.")
    return _need("move_messages")(ids, str(body.get("destination") or ""))


@app.get("/api/summary")
@mail_api
def api_summary():
    try:
        days = int(request.args.get("days", 7))
    except ValueError:
        raise BadRequest("days must be a number.") from None
    return _need("get_digest")(days=days)


@app.get("/api/contacts")
@mail_api
def api_contacts():
    return _need("search_contacts")((request.args.get("q") or "")[:100])


@app.post("/api/write")
@mail_api
def api_write():
    """{note, choices?: {to:[{phrase,address}], cc:[...]}, remember?: bool} -> a ready-to-check email."""
    body = _json()
    choices = body.get("choices")
    if choices is not None and not isinstance(choices, dict):
        raise BadRequest("Invalid recipients.")
    return _need("write_email")(str(body.get("note") or ""), choices, remember=body.get("remember", True) is not False,
                                polish=body.get("polish") is True)


@app.get("/api/signature")
@mail_api
def api_signature():
    return _need("get_signature")()


@app.post("/api/signature")
@mail_api
def api_save_signature():
    return _need("save_signature")(_json())


@app.get("/api/overview")
@mail_api
def api_overview():
    data = _need("get_overview")(days=7)
    # Task numbers come from the local task list.
    from datetime import date

    today = date.today().isoformat()
    open_tasks = [t for t in mail.list_tasks(include_completed=False) if not t["completed"]]
    open_tasks.sort(key=lambda t: (t["due"] or "9999-12-31", t["createdDateTime"] or ""))
    data["tasks"] = {
        "open": len(open_tasks),
        "overdue": sum(1 for t in open_tasks if t["due"] and t["due"][:10] < today),
        "dueToday": sum(1 for t in open_tasks if t["due"] and t["due"][:10] == today),
        "upcoming": open_tasks[:5],
    }
    return data


@app.get("/api/folders/<path:folder>/summary")
@mail_api
def api_folder_summary(folder: str):
    return mail.get_folder_summary(folder)


@app.get("/api/messages")
@mail_api
def api_messages():
    try:
        start = int(request.args.get("start", 0))
        limit = int(request.args.get("limit", 50))
    except ValueError:
        raise BadRequest("start and limit must be numbers.") from None
    extra = {}
    if config.BACKEND == "imap":  # sorting and categories are IMAP-backend features
        extra = {"sort": request.args.get("sort") or "newest", "category": request.args.get("category") or None}
    return mail.list_messages(
        folder=request.args.get("folder", "inbox"),
        start=start,
        limit=limit,
        search=request.args.get("q") or None,
        unread=_flag("unread"),
        flagged=_flag("flagged"),
        has_attachments=_flag("attachments"),
        date_from=request.args.get("from") or None,
        date_to=request.args.get("to") or None,
        **extra,
    )


@app.post("/api/messages/bulk")
@mail_api
def api_bulk():
    """{ids: [...], action: read|unread|flag|unflag|delete|categorize|uncategorize, category?}"""
    body = _json()
    ids = body.get("ids")
    if not isinstance(ids, list) or not all(isinstance(x, str) for x in ids):
        raise BadRequest("'ids' must be a list of email ids.")
    return _need("bulk_update")(ids, str(body.get("action") or ""), body.get("category") or None)


# ---------------------------------------------------------------------------
# Categories (names/colours on this PC; assignments stored on the mail server)
# ---------------------------------------------------------------------------


@app.get("/api/categories")
@mail_api
def api_categories():
    _need("bulk_update")
    return {"categories": categories.list_categories(), "colors": categories.COLORS}


@app.post("/api/categories")
@mail_api
def api_create_category():
    body = _json()
    return categories.create(str(body.get("name") or ""), str(body.get("color") or ""))


@app.post("/api/categories/update")
@mail_api
def api_update_category():
    body = _json()
    return categories.update(str(body.get("keyword") or ""), str(body.get("name") or ""), str(body.get("color") or ""))


@app.post("/api/categories/delete")
@mail_api
def api_delete_category():
    return categories.delete(str(_json().get("keyword") or ""))


@app.get("/api/messages/<message_id>")
@mail_api
def api_message(message_id: str):
    return mail.get_message(message_id)


# Only these types may be displayed inline (e.g. images embedded in an email body).
INLINE_SAFE_TYPES = {"image/png", "image/jpeg", "image/gif", "image/webp", "image/bmp"}


@app.get("/api/messages/<message_id>/attachments/<attachment_ref>")
@mail_api
def api_attachment(message_id: str, attachment_ref: str):
    # Classic Outlook numbers attachments 1..n; the IMAP backend uses part ids.
    ref = int(attachment_ref) if config.BACKEND == "outlook" and attachment_ref.isdigit() else attachment_ref
    name, mime, data = mail.get_attachment(message_id, ref)
    inline = request.args.get("inline") == "1" and mime.lower() in INLINE_SAFE_TYPES
    resp = send_file(
        io.BytesIO(data),
        mimetype=mime if inline else "application/octet-stream",
        as_attachment=not inline,
        download_name=name,
        max_age=0,
    )
    resp.headers["Content-Security-Policy"] = "default-src 'none'; img-src 'self'; sandbox"
    return resp


@app.post("/api/messages/<message_id>/read")
@mail_api
def api_set_read(message_id: str):
    return mail.set_read(message_id, _json_bool("read"))


@app.post("/api/messages/<message_id>/flag")
@mail_api
def api_set_flag(message_id: str):
    return mail.set_flag(message_id, _json_bool("flagged"))


@app.delete("/api/messages/<message_id>")
@mail_api
def api_delete(message_id: str):
    return mail.delete_message(message_id, permanent=request.args.get("permanent") == "1")


@app.get("/api/messages/<message_id>/compose")
@mail_api
def api_compose_prefill(message_id: str):
    """Prefill for Reply / Reply all / Forward."""
    return mail.get_compose_prefill(message_id, request.args.get("mode", ""))


def _form_list(name: str) -> list[str]:
    raw = request.form.get(name, "")
    return [part.strip() for part in raw.replace("\n", ";").split(";") if part.strip()]


@app.post("/api/compose")
def api_compose():
    """multipart/form-data: action, mode, sourceId, draftId, to, cc, bcc, subject, body, quotedHtml,
    removeAttachments (JSON list of attachment ids or names), files (0..n)."""
    try:
        removed = json.loads(request.form.get("removeAttachments") or "[]")
        if not isinstance(removed, list) or not all(isinstance(x, str) for x in removed):
            raise ValueError
    except ValueError:
        return jsonify({"code": "bad_request", "message": "Invalid attachment list."}), 400

    uploads = [(f.filename or "attachment", f.read()) for f in request.files.getlist("files") if f]

    @mail_api
    def handler():
        return mail.compose(
            action=request.form.get("action", ""),
            mode=request.form.get("mode", "new"),
            source_id=request.form.get("sourceId") or None,
            draft_id=request.form.get("draftId") or None,
            to=_form_list("to"),
            cc=_form_list("cc"),
            bcc=_form_list("bcc"),
            subject=request.form.get("subject", ""),
            body=request.form.get("body", ""),
            remove_attachments=removed,
            uploads=uploads,
            quoted_html=request.form.get("quotedHtml") or None,
        )

    return handler()


# ---------------------------------------------------------------------------
# Tasks
# ---------------------------------------------------------------------------


@app.get("/api/tasks")
@mail_api
def api_tasks():
    tasks = mail.list_tasks(include_completed=_flag("completed"))
    tasks.sort(key=lambda t: (t["completed"], t["due"] or "9999-12-31", t["createdDateTime"] or ""))
    return {"tasks": tasks}


@app.post("/api/tasks")
@mail_api
def api_create_task():
    body = _json()
    task = mail.create_task(
        title=str(body.get("title") or ""),
        due=body.get("due") or None,
        notes=str(body.get("notes") or ""),
        message_id=body.get("messageId") or None,
        importance=str(body.get("importance") or "normal"),
    )
    if body.get("suggestionKey"):
        task_finder.mark_handled(str(body["suggestionKey"]))
    return task


@app.post("/api/tasks/<task_id>/complete")
@mail_api
def api_complete_task(task_id: str):
    return mail.set_task_completed(task_id, _json_bool("completed"))


@app.get("/api/tasks/suggestions")
@mail_api
def api_task_suggestions():
    try:
        days = max(1, min(int(request.args.get("days", 7)), 30))
    except ValueError:
        days = 7
    messages = mail.recent_messages_for_tasks(days=days, limit=50)
    return {"suggestions": task_finder.suggest(messages), "scanned": len(messages), "days": days}


@app.get("/api/messages/<message_id>/task-suggestions")
@mail_api
def api_message_task_suggestions(message_id: str):
    msg = mail.get_message_for_tasks(message_id)
    return {"suggestions": task_finder.suggest_for_message(msg)}


@app.post("/api/tasks/suggestions/dismiss")
@mail_api
def api_dismiss_suggestion():
    key = str(_json().get("key") or "")
    if not key or len(key) > 1200:
        raise BadRequest("Missing suggestion key.")
    task_finder.mark_handled(key)
    return {"dismissed": key}


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


@app.errorhandler(413)
def too_large(_):
    limit_mb = app.config["MAX_CONTENT_LENGTH"] // (1024 * 1024)
    return jsonify({"code": "too_large", "message": f"Attachments are too large. The total must be under {limit_mb} MB."}), 413


@app.errorhandler(404)
def not_found(_):
    if request.path.startswith("/api/"):
        return jsonify({"code": "not_found", "message": "Unknown API endpoint."}), 404
    return "Not found", 404


if __name__ == "__main__":
    url = f"http://{HOST}:{PORT}"
    mode = "mail server (IMAP/SMTP)" if config.BACKEND == "imap" else "classic Outlook on this PC"
    print(f"Outlook Dashboard running at {url}  [{mode}]  (press Ctrl+C to stop)")
    if "--no-browser" not in sys.argv:
        threading.Timer(1.2, lambda: webbrowser.open(url)).start()
    app.run(host=HOST, port=PORT, debug=False, threaded=True)
