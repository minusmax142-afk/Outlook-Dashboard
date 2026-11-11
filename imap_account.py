"""
Email account for the IMAP/SMTP backend.

- Non-secret settings (email, display name, server names, ports) are kept in
  %LOCALAPPDATA%\\OutlookDashboard\\account.json.
- The password is kept ONLY in Windows Credential Manager (encrypted by Windows for your
  account), never in a file and never sent to the browser.
"""

from __future__ import annotations

import imaplib
import json
import re
import smtplib
import socket
import ssl
import threading

import keyring

import config
from errors import BadRequest, NotSignedIn, ServiceUnavailable

KEYRING_SERVICE = "OutlookDashboard (IMAP)"
ACCOUNT_FILE = config.DATA_DIR / "account.json"
EMAIL_RE = re.compile(r"^[^@\s<>;,]+@[^@\s<>;,]+\.[^@\s<>;,]+$")
HOST_RE = re.compile(r"^[A-Za-z0-9.-]{1,253}$")

_lock = threading.Lock()
_cached: dict | None = None  # settings + password in memory while the dashboard runs


def defaults_for(email: str) -> dict:
    domain = email.split("@")[-1].strip().lower() if "@" in email else ""
    host = f"mail.{domain}" if domain else ""
    return {"imapHost": host, "imapPort": 993, "smtpHost": host, "smtpPort": 465}


def _load_settings() -> dict | None:
    try:
        data = json.loads(ACCOUNT_FILE.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) and data.get("email") else None
    except (OSError, ValueError):
        return None


def get_account() -> dict:
    """Settings + password, or NotSignedIn."""
    global _cached
    with _lock:
        if _cached:
            return _cached
        settings = _load_settings()
        if not settings:
            raise NotSignedIn("Please sign in with your email address and password.")
        password = keyring.get_password(KEYRING_SERVICE, settings["email"])
        if not password:
            raise NotSignedIn("Please sign in with your email address and password.")
        _cached = {**settings, "password": password}
        return _cached


def _validate(form: dict) -> dict:
    email = str(form.get("email") or "").strip()
    password = str(form.get("password") or "")
    if not EMAIL_RE.match(email):
        raise BadRequest("Enter your full email address, e.g. name@company.com.")
    if not password:
        raise BadRequest("Enter your email password.")
    d = defaults_for(email)
    s = {
        "email": email,
        "name": str(form.get("name") or "").strip()[:100],
        "imapHost": str(form.get("imapHost") or d["imapHost"]).strip().lower(),
        "smtpHost": str(form.get("smtpHost") or d["smtpHost"]).strip().lower(),
    }
    try:
        s["imapPort"] = int(form.get("imapPort") or d["imapPort"])
        s["smtpPort"] = int(form.get("smtpPort") or d["smtpPort"])
    except (TypeError, ValueError):
        raise BadRequest("Ports must be numbers.") from None
    if not (HOST_RE.match(s["imapHost"]) and HOST_RE.match(s["smtpHost"])):
        raise BadRequest("Invalid server name.")
    if not (0 < s["imapPort"] < 65536 and 0 < s["smtpPort"] < 65536):
        raise BadRequest("Invalid port number.")
    return {**s, "password": password}


def open_smtp(acc: dict) -> smtplib.SMTP:
    """SSL on 465; STARTTLS on any other port (e.g. 587). Certificates are always verified."""
    ctx = ssl.create_default_context()
    if acc["smtpPort"] == 465:
        smtp = smtplib.SMTP_SSL(acc["smtpHost"], acc["smtpPort"], context=ctx, timeout=30)
    else:
        smtp = smtplib.SMTP(acc["smtpHost"], acc["smtpPort"], timeout=30)
        smtp.starttls(context=ctx)
    smtp.login(acc["email"], acc["password"])
    return smtp


def sign_in(form: dict) -> dict:
    """Checks the password against BOTH the IMAP and SMTP servers before saving anything."""
    global _cached
    acc = _validate(form)
    ctx = ssl.create_default_context()
    try:
        imap = imaplib.IMAP4_SSL(acc["imapHost"], acc["imapPort"], ssl_context=ctx, timeout=30)
        try:
            imap.login(acc["email"], acc["password"])
        except imaplib.IMAP4.error:
            raise BadRequest("The email address or password was not accepted by the mail server.") from None
        finally:
            try:
                imap.logout()
            except Exception:
                pass
        try:
            open_smtp(acc).quit()
        except smtplib.SMTPAuthenticationError:
            raise BadRequest("Reading mail works, but the outgoing (SMTP) server rejected the password.") from None
    except ssl.SSLCertVerificationError:
        raise BadRequest(f"The security certificate of {acc['imapHost']} couldn't be verified. Check the server name.") from None
    except (socket.gaierror, socket.timeout, ConnectionError, OSError) as err:
        if isinstance(err, BadRequest):
            raise
        raise ServiceUnavailable(
            f"Couldn't reach {acc['imapHost']}. Check the server name, your internet connection or VPN."
        ) from None

    with _lock:
        keyring.set_password(KEYRING_SERVICE, acc["email"], acc["password"])
        config.DATA_DIR.mkdir(parents=True, exist_ok=True)
        settings = {k: v for k, v in acc.items() if k != "password"}
        ACCOUNT_FILE.write_text(json.dumps(settings, indent=2), encoding="utf-8")
        _cached = acc
    return status()


def status() -> dict:
    try:
        acc = get_account()
        return {"signedIn": True, "username": acc["email"], "login": "idle", "error": None}
    except NotSignedIn:
        settings = _load_settings() or {}
        return {"signedIn": False, "username": settings.get("email"), "login": "idle", "error": None,
                "defaults": {k: settings.get(k) for k in ("email", "name", "imapHost", "imapPort", "smtpHost", "smtpPort")}
                if settings else None}


def sign_out() -> dict:
    global _cached
    with _lock:
        settings = _load_settings()
        if settings:
            try:
                keyring.delete_password(KEYRING_SERVICE, settings["email"])
            except keyring.errors.PasswordDeleteError:
                pass
        _cached = None
    return status()


def password_rejected() -> None:
    """Called when the server rejects the saved password (e.g. it was changed): forget it."""
    global _cached
    with _lock:
        _cached = None
        settings = _load_settings()
        if settings:
            try:
                keyring.delete_password(KEYRING_SERVICE, settings["email"])
            except keyring.errors.PasswordDeleteError:
                pass
