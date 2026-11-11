"""
Finds task-like requests in emails with plain rules (no AI service, no cost, runs locally).

It looks for:
  - request phrases: "please", "kindly", "could you", "action required", "awaiting your approval" ...
  - action verbs: send, share, submit, review, approve, confirm, prepare, arrange ...
  - deadlines: "by Friday", "before 15 Nov", "tomorrow", "EOD", "end of the month", "15/11/2026" ...
and suggests a task title + due date. You approve each suggestion before a task is created.

The only thing stored on disk is a list of suggestion keys you've added or dismissed
(email id + short hash), so the same suggestion isn't shown again. No email content is stored.
"""

from __future__ import annotations

import calendar
import hashlib
import json
import re
import threading
from datetime import date, datetime, timedelta

import config

# ---------------------------------------------------------------------------
# Patterns
# ---------------------------------------------------------------------------

REQUEST_CUES = re.compile(
    r"\b(please|pls|plz|kindly|could you|can you|would you|will you|i need you to|we need you to|"
    r"you are requested|you're requested|request(?:ed)? you|requesting you|you need to|you must|you should|"
    r"make sure|ensure|remember to|don'?t forget|action required|action needed|required from you|"
    r"awaiting your|waiting for your|let me know|let us know|get back to me|get back to us|revert|"
    r"your (?:approval|feedback|input|confirmation|response|review|signature|comments)|"
    r"need your|requires your|at the earliest|asap|urgent(?:ly)?)\b",
    re.I,
)
ACTION_VERBS = re.compile(
    r"\b(send|share|provide|submit|review|approve|confirm|prepare|update|complete|arrange|schedule|check|"
    r"verify|sign|forward|reply|respond|revert|call|contact|follow[- ]up|finali[sz]e|fill|attend|join|pay|"
    r"process|upload|issue|deliver|fix|resolve|investigate|look into|draft|book|order|collect|return|"
    r"submit|compile|coordinate|clear|release|approve|endorse|advise|inform|nominate|register|install)\b",
    re.I,
)
SUBJECT_CUES = re.compile(
    r"\b(action required|action needed|request|required|reminder|urgent|pending|follow[- ]?up|approval|"
    r"deadline|due|asap|important|kindly|please)\b",
    re.I,
)
SKIP_SENDERS = re.compile(
    r"(no-?reply|do-?not-?reply|notifications?@|notify@|mailer-daemon|postmaster|newsletter|marketing|bounce|alerts?@)",
    re.I,
)
AUTO_SUBJECTS = re.compile(
    r"^\s*(automatic reply|auto(?:matic)?[- ]?reply|out of (the )?office|undeliverable|delivery (status|has failed)|"
    r"read:|accepted:|declined:|tentative:|canceled:|cancelled:)",
    re.I,
)
# Where the new message ends and the quoted conversation / signature begins.
QUOTE_START = re.compile(
    r"^\s*(from:\s|-{2,}\s*original message|on .{5,80} wrote:|sent from my|_{8,}|>)",
    re.I | re.M,
)
SIGN_OFF = re.compile(
    r"^\s*(best regards|kind regards|warm regards|regards|thanks(?: (?:&|and) regards)?|thank you|many thanks|"
    r"sincerely|cheers|br)\s*[,.!]?\s*$",
    re.I | re.M,
)
LEADING_FILLER = re.compile(
    r"^(?:(?:dear|hi|hello|hey)\b[^,]{0,40},\s*)?(?:and\s+|also\s+|further(?:more)?,?\s+|moreover,?\s+)?"
    r"(?:(?:please|pls|plz|kindly|could you|can you|would you|will you|i need you to|we need you to|"
    r"you are requested to|you're requested to|request(?:ed)? you to|requesting you to|you need to|you must|"
    r"you should|make sure to|remember to|don'?t forget to)\s+)+",
    re.I,
)

MONTHS = {m.lower(): i for i, m in enumerate(calendar.month_abbr) if m}
MONTHS.update({m.lower(): i for i, m in enumerate(calendar.month_name) if m})
MONTH_RE = r"(jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|june?|july?|aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)"
WEEKDAYS = {name.lower(): i for i, name in enumerate(calendar.day_name)}
WEEKDAYS.update({name.lower(): i for i, name in enumerate(calendar.day_abbr)})
WEEKDAY_RE = r"(monday|tuesday|wednesday|thursday|friday|saturday|sunday|mon|tue|tues|wed|thu|thur|thurs|fri|sat|sun)"

# ---------------------------------------------------------------------------
# Due dates
# ---------------------------------------------------------------------------


def _safe_date(y: int, m: int, d: int) -> date | None:
    try:
        return date(y, m, d)
    except ValueError:
        return None


def _with_year(m: int, d: int, year: int | None, ref: date) -> date | None:
    if year is not None:
        return _safe_date(year if year > 100 else 2000 + year, m, d)
    found = _safe_date(ref.year, m, d)
    if found and found < ref - timedelta(days=30):  # "5 Jan" written in December means next year
        found = _safe_date(ref.year + 1, m, d)
    return found


def find_due_date(text: str, ref: date) -> date | None:
    """Returns the first deadline-like date in text, relative to ref (the email's received date)."""
    t = text.lower()

    explicit = [
        # 2026-11-15
        (r"\b(\d{4})-(\d{1,2})-(\d{1,2})\b", lambda g: _safe_date(int(g[0]), int(g[1]), int(g[2]))),
        # 15/11/2026, 15-11-26, 15.11.2026 (day first, as used in PK/UK/EU)
        (r"\b(\d{1,2})[/.-](\d{1,2})[/.-](\d{2,4})\b", lambda g: _with_year(int(g[1]), int(g[0]), int(g[2]), ref)),
        # 15 Nov 2026, 15th of November, 06-Oct-2026
        (rf"\b(\d{{1,2}})(?:st|nd|rd|th)?(?:\s+of)?[\s-]+{MONTH_RE}\.?(?:[\s,-]+(\d{{4}}))?\b",
         lambda g: _with_year(MONTHS[g[1][:3]], int(g[0]), int(g[2]) if g[2] else None, ref)),
        # November 15, Nov 15th 2026
        (rf"\b{MONTH_RE}\.?\s+(\d{{1,2}})(?:st|nd|rd|th)?(?:,?\s+(\d{{4}}))?\b",
         lambda g: _with_year(MONTHS[g[0][:3]], int(g[1]), int(g[2]) if g[2] else None, ref)),
    ]
    candidates: list[tuple[int, date]] = []
    for pattern, build in explicit:
        for m in re.finditer(pattern, t):
            d = build(m.groups())
            if d:
                candidates.append((m.start(), d))

    relative = [
        (r"\b(today|tonight|eod|end of (?:the )?day|cob|close of business)\b", lambda m: ref),
        (r"\bday after tomorrow\b", lambda m: ref + timedelta(days=2)),
        (r"\btomorrow\b", lambda m: ref + timedelta(days=1)),
        (r"\b(?:within|in)\s+(\d{1,2})\s+(?:working\s+|business\s+)?days?\b", lambda m: ref + timedelta(days=int(m.group(1)))),
        (r"\b(?:end of (?:the |this )?week|eow|this week)\b", lambda m: ref + timedelta(days=max(0, 4 - ref.weekday()))),
        (r"\bnext week\b", lambda m: ref + timedelta(days=7 - ref.weekday())),
        (r"\b(?:end of (?:the |this )?month|month[- ]end|eom)\b",
         lambda m: date(ref.year, ref.month, calendar.monthrange(ref.year, ref.month)[1])),
        (rf"\b(next\s+)?{WEEKDAY_RE}\b", lambda m: _next_weekday(ref, WEEKDAYS[m.group(2)[:3]], bool(m.group(1)))),
    ]
    for pattern, build in relative:
        for m in re.finditer(pattern, t):
            candidates.append((m.start(), build(m)))

    # Prefer a date that follows a deadline word ("by", "before", "until", "deadline", "due") ...
    for m in re.finditer(r"\b(by|before|until|till|no later than|not later than|deadline|due|latest by|on or before)\b", t):
        after = [(pos, d) for pos, d in candidates if 0 <= pos - m.end() <= 25]
        if after:
            d = min(after)[1]
            if d >= ref:
                return d
    # ... otherwise the first future date mentioned.
    for _, d in sorted(candidates, key=lambda c: c[0]):
        if d >= ref:
            return d
    return None


def _next_weekday(ref: date, weekday: int, force_next_week: bool) -> date:
    days = (weekday - ref.weekday()) % 7 or 7
    if force_next_week and days < 7 - ref.weekday():
        days += 7
    return ref + timedelta(days=days)


# ---------------------------------------------------------------------------
# Suggestions
# ---------------------------------------------------------------------------


def _new_part(text: str) -> str:
    """Keeps only the new message: drops the quoted conversation and the signature."""
    m = QUOTE_START.search(text)
    if m:
        text = text[: m.start()]
    m = SIGN_OFF.search(text)
    if m and m.start() > 40:
        text = text[: m.start()]
    return text


def _sentences(text: str) -> list[str]:
    # Plain-text emails wrap lines mid-sentence: re-join a line break between a word and a
    # lower-case continuation: "implement a / new SOP" -> "implement a new SOP".
    text = re.sub(r"(?<=[A-Za-z0-9,;])[ \t]*\r?\n[ \t]*(?=[a-z(])", " ", text)
    text = re.sub(r"[ \t ]+", " ", text)
    parts = re.split(r"(?<=[.!?])\s+|\n+|•|•|;\s+", text)
    return [p.strip(" -*\t") for p in parts if 12 <= len(p.strip()) <= 400]


def _title_from(sentence: str) -> str:
    s = LEADING_FILLER.sub("", sentence.strip())
    s = re.sub(r"\s+", " ", s).strip(" ,.;:-?!")
    if len(s) > 110:
        cut = s[:110].rsplit(" ", 1)[0]
        s = cut + "…"
    return s[:1].upper() + s[1:] if s else s


def suggestion_key(message_id: str, title: str) -> str:
    return f"{message_id}:{hashlib.sha1(title.lower().encode('utf-8')).hexdigest()[:10]}"


POLITE_CLOSING = re.compile(
    r"\b(?:should you (?:have|require|need) any|if you (?:have|need|require) any (?:further |more )?(?:questions|clarification|information|assistance)|"
    r"(?:please )?(?:do not|don't) hesitate to (?:contact|reach)|(?:please )?feel free to (?:contact|reach|discuss)|"
    r"I look forward to (?:your|hearing)|let me know if you (?:have|need) any|for any (?:queries|questions)|"
    r"kindly acknowledge receipt|thank you for your (?:prompt )?attention|please disregard this reminder|"
    r"(?:I )?hope (?:this|you)\b)",
    re.I,
)


def suggest_for_message(msg: dict, max_per_email: int = 3) -> list[dict]:
    """msg: {id, subject, from: {name, address}, receivedDateTime, text, toMe}"""
    subject = msg.get("subject") or ""
    sender = msg.get("from") or {}
    if AUTO_SUBJECTS.search(subject) or SKIP_SENDERS.search(sender.get("address") or ""):
        return []
    try:
        ref = datetime.fromisoformat((msg.get("receivedDateTime") or "").replace("Z", "+00:00")).astimezone().date()
    except ValueError:
        ref = date.today()

    subject_hint = bool(SUBJECT_CUES.search(subject))
    found: list[dict] = []
    for sentence in _sentences(_new_part(msg.get("text") or "")):
        if POLITE_CLOSING.search(sentence):
            continue  # "Should you have any questions..., please contact me." is courtesy, not a task
        cue = REQUEST_CUES.search(sentence)
        verb = ACTION_VERBS.search(sentence)
        question_to_me = sentence.endswith("?") and re.search(r"\byou\b", sentence, re.I)
        if not (cue or question_to_me):
            continue
        due = find_due_date(sentence, ref)
        score = (2 if cue else 0) + (1 if verb else 0) + (1 if question_to_me else 0) + (2 if due else 0) \
            + (1 if subject_hint else 0) - (1 if msg.get("toMe") is False else 0)
        if score < 3 or not (verb or due):
            continue
        title = _title_from(sentence)
        if len(title) < 8:
            title = subject[:110] or "Follow up on email"
        reason = []
        if cue:
            reason.append(f"request (“{cue.group(0)}”)")
        if due:
            reason.append(f"deadline {due.strftime('%a %d %b')}")
        if msg.get("toMe") is False:
            reason.append("you were Cc'd")
        found.append({
            "key": suggestion_key(msg["id"], title),
            "messageId": msg["id"],
            "title": title,
            "due": due.isoformat() if due else None,
            "confidence": "high" if score >= 5 else "medium",
            "reason": ", ".join(reason),
            "quote": sentence[:300],
            "subject": subject,
            "from": sender,
            "receivedDateTime": msg.get("receivedDateTime"),
            "_score": score,
        })

    # A strong subject ("Action required: …") with no clear sentence still deserves one suggestion.
    if not found and subject_hint and re.search(r"\b(action required|action needed|approval|request|reminder|pending)\b", subject, re.I):
        due = find_due_date(subject + " " + (msg.get("text") or "")[:1000], ref)
        title = "Respond: " + re.sub(r"^\s*((re|fw|fwd)\s*:\s*)+", "", subject, flags=re.I)[:100]
        found.append({
            "key": suggestion_key(msg["id"], title), "messageId": msg["id"], "title": title,
            "due": due.isoformat() if due else None, "confidence": "medium",
            "reason": "subject looks like a request", "quote": "", "subject": subject, "from": sender,
            "receivedDateTime": msg.get("receivedDateTime"), "_score": 3,
        })

    # Best first, no near-duplicates, at most max_per_email.
    found.sort(key=lambda s: -s["_score"])
    unique: list[dict] = []
    for s in found:
        if not any(s["title"][:40].lower() == u["title"][:40].lower() for u in unique):
            unique.append(s)
    for s in unique:
        s.pop("_score", None)
    return unique[:max_per_email]


# ---------------------------------------------------------------------------
# Remembered decisions (keys only)
# ---------------------------------------------------------------------------

_STATE_FILE = config.DATA_DIR / "task_suggestions.json"
_state_lock = threading.Lock()
MAX_KEYS = 3000


def _load_state() -> dict:
    try:
        data = json.loads(_STATE_FILE.read_text(encoding="utf-8"))
        return {"handled": list(data.get("handled", []))}
    except (OSError, ValueError):
        return {"handled": []}


def mark_handled(key: str) -> None:
    """Remember that a suggestion was added or dismissed, so it isn't suggested again."""
    with _state_lock:
        state = _load_state()
        if key not in state["handled"]:
            state["handled"].append(key)
            state["handled"] = state["handled"][-MAX_KEYS:]
            config.DATA_DIR.mkdir(parents=True, exist_ok=True)
            _STATE_FILE.write_text(json.dumps(state), encoding="utf-8")


def handled_keys() -> set[str]:
    with _state_lock:
        return set(_load_state()["handled"])


def suggest(messages: list[dict]) -> list[dict]:
    handled = handled_keys()
    out = []
    for msg in messages:
        out.extend(s for s in suggest_for_message(msg) if s["key"] not in handled)
    # Soonest deadline first, then high confidence, then newest email.
    out.sort(key=lambda s: (s["due"] or "9999-12-31", s["confidence"] != "high", -(_ts(s["receivedDateTime"]))))
    return out


def _ts(iso: str | None) -> float:
    try:
        return datetime.fromisoformat((iso or "").replace("Z", "+00:00")).timestamp()
    except ValueError:
        return 0.0
