"""
Short, rule-based email summaries (no AI service; nothing leaves this PC).

summarize() picks the one or two most informative sentences of the *new* part of an email
(quoted history, greetings, pleasantries and signatures removed). kind_of() gives a rough type.
"""

from __future__ import annotations

import re

import task_finder

MAX_LEN = 240

GREETING = re.compile(r"^\s*(dear|hi|hello|hey|good (morning|afternoon|evening)|greetings|salam|assalam[a-z ]*)\b[^\n]{0,60}$",
                      re.I | re.M)
FLUFF = re.compile(
    r"^(i hope (this|you)|hope (this|you)|trust (this|you)|i trust|thank(s| you) for your (email|mail|message|reply)|"
    r"thanks? (in advance|again)|thank you\.?$|thanks\.?$|good (morning|afternoon|evening)|please (do )?let me know if you have any questions|"
    r"feel free to|looking forward|have a (great|good|nice)|this (e-?mail|message) (and any|is confidential|may contain)|"
    r"disclaimer|confidentiality notice|sent from my|get outlook for)",
    re.I,
)
CUE_WORDS = re.compile(
    r"\b(please|kindly|request|attached|attachment|deadline|due|meeting|call|update|approved?|approval|confirm|"
    r"invoice|payment|quotation|report|schedule|urgent|asap|issue|problem|required|pending|reminder|decision|"
    r"agenda|minutes|delivery|order|contract|proposal|budget)\b",
    re.I,
)
URL = re.compile(r"https?://\S+|www\.\S+", re.I)

KINDS = [
    ("meeting", re.compile(r"\b(meeting|invitation|invite|agenda|minutes|call|zoom|teams|webinar|conference|appointment|schedule[ds]?)\b", re.I)),
    ("finance", re.compile(r"\b(invoice|payment|paid|quotation|quote|receipt|bill|purchase order|\bpo\b|salary|payroll|tax|budget|refund|statement)\b", re.I)),
    ("report", re.compile(r"\b(report|summary|update|status|progress|weekly|monthly|daily)\b", re.I)),
]
KIND_LABELS = {"request": "Request", "meeting": "Meeting", "finance": "Finance", "report": "Update",
               "notification": "Notification", "automatic": "Automatic", "info": "Info"}


HEADER_LINE = re.compile(r"^\s*>*\s*(from|sent|date|to|cc|bcc|subject|reply-to)\s*:.*$", re.I | re.M)
ORIGINAL = re.compile(r"^\s*>*\s*(-{2,}\s*(original|forwarded) message\s*-{2,}|begin forwarded message:?|_{8,})\s*$", re.I | re.M)


def _forwarded_body(text: str) -> str:
    """For a forward (nothing new above the quoted email): the forwarded email's own text."""
    text = re.sub(r"^[ \t]*>+[ \t]?", "", text or "", flags=re.M)  # "> " quote markers
    text = ORIGINAL.sub("", text)
    # Drop the forwarded header block (From:/Sent:/To:/Subject: lines) at the top.
    lines = text.splitlines()
    i = 0
    while i < len(lines) and (not lines[i].strip() or HEADER_LINE.match(lines[i])):
        i += 1
    return task_finder._new_part("\n".join(lines[i:]))


def _clean(text: str) -> str:
    new = task_finder._new_part(text or "")
    if len(new.strip()) < 20:
        new = _forwarded_body(text) or new
    new = GREETING.sub("", new)
    new = URL.sub("", new)
    return new


SIGNATURE_LINE = re.compile(
    r"^(?:[A-Z][\w.'&-]*\.?(?:\s+(?:[A-Z&][\w.'&-]*\.?|of|and|for|the)){1,7}\.?"  # Name / Job Title / Company (2+ words)
    r"|(?i:.*(?:\b(?:tel|phone|mobile|cell|fax|ext|whatsapp)\b\.?\s*[:#]?\s*[+\d(]|@[\w-]+\.\w|www\.).*)"  # contact lines
    r"|[+\d][\d\s().-]{6,})$",
)


SIGN_OFF_LINE = re.compile(r"^(best|kind|warm)?\s*regards|^thanks|^thank you|^sincerely|^cheers", re.I)


def _looks_like_signature(sentence: str) -> bool:
    s = sentence.strip()
    return len(s) <= 70 and bool(SIGNATURE_LINE.match(s))


def summarize(subject: str, text: str) -> str:
    sentences = [s for s in task_finder._sentences(_clean(text))
                 if not FLUFF.search(s.strip()) and not _looks_like_signature(s)]
    if not sentences:
        # Very short emails ("Noted.", "Done, thanks"): the first line that isn't a signature.
        lines = [ln.strip(" -*\t") for ln in _clean(text).splitlines()]
        lines = [ln for ln in lines if ln and not FLUFF.search(ln) and not _looks_like_signature(ln)
                 and not SIGN_OFF_LINE.match(ln)]
        flat = lines[0] if lines else ""
        return (flat[: MAX_LEN - 1] + "…") if len(flat) > MAX_LEN else flat
    subj_words = {w for w in re.findall(r"[a-z]{4,}", (subject or "").lower())}
    scored = []
    for i, s in enumerate(sentences[:25]):
        score = 0.0
        score += 2.0 if i == 0 else 1.0 if i == 1 else 0.0
        score += min(2, len(CUE_WORDS.findall(s))) * 1.0
        score += 1.0 if task_finder.REQUEST_CUES.search(s) else 0.0
        score += 0.5 if re.search(r"\d", s) else 0.0
        score += 0.5 * min(2, len(subj_words & set(re.findall(r"[a-z]{4,}", s.lower()))))
        score += 1.0 if 40 <= len(s) <= 220 else -0.5 if len(s) < 25 else 0.0
        score -= 1.5 if sum(c.isupper() for c in s) > 0.6 * max(1, sum(c.isalpha() for c in s)) else 0.0
        scored.append((score, i, s))
    best = sorted(scored, key=lambda t: (-t[0], t[1]))[:2]
    chosen = sorted(i for _sc, i, _s in best)
    # A sentence ending in ":" introduces what follows: take the next line with it.
    if sentences[chosen[0]].rstrip().endswith(":") and chosen[0] + 1 < len(sentences):
        chosen = sorted({chosen[0], chosen[0] + 1})
    picked = [sentences[i] for i in chosen]
    out = picked[0]
    if len(picked) > 1 and len(out) + len(picked[1]) + 1 <= MAX_LEN:
        end = out.rstrip()
        out = end + ("" if end.endswith((".", "!", "?", ":")) else ".") + " " + picked[1]
    out = re.sub(r"\s+", " ", out).strip()
    return (out[: MAX_LEN - 1].rsplit(" ", 1)[0] + "…") if len(out) > MAX_LEN else out


def kind_of(subject: str, sender_address: str, text: str, has_tasks: bool) -> str:
    if task_finder.AUTO_SUBJECTS.search(subject or ""):
        return "automatic"
    if task_finder.SKIP_SENDERS.search(sender_address or ""):
        return "notification"
    if has_tasks:
        return "request"
    head = f"{subject} {(text or '')[:600]}"
    for kind, rx in KINDS:
        if rx.search(head):
            return kind
    return "info"
