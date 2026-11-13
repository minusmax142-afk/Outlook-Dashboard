"""
Clear, business-style subject lines from a short note (rules only, no AI).

    "the generator is not working since morning, pls get it fixed"  -> "Generator – Repair Required"
    "i am on leave from 20 nov to 25 nov"                            -> "Leave Notification – 20 Nov to 25 Nov"
    "please arrange 20 chairs for the conference hall on saturday"  -> "Arrangement of 20 Chairs for the Conference Hall – Saturday"
"""

from __future__ import annotations

import re

import writer as w

NOUNS = {
    "arrange": "Arrangement of", "organise": "Arrangement of", "organize": "Arrangement of", "prepare": "Preparation of",
    "check": "Inspection of", "inspect": "Inspection of", "review": "Review of", "verify": "Verification of",
    "repair": "Repair of", "fix": "Repair of", "resolve": "Resolution of", "clean": "Cleaning of", "submit": "Submission of",
    "send": "Submission of", "share": "Submission of", "provide": "Provision of", "update": "Update on",
    "complete": "Completion of", "finish": "Completion of", "finalise": "Finalisation of", "finalize": "Finalisation of",
    "install": "Installation of", "replace": "Replacement of", "order": "Purchase of", "purchase": "Purchase of",
    "buy": "Purchase of", "book": "Booking of", "cancel": "Cancellation of", "confirm": "Confirmation of",
    "collect": "Collection of", "deliver": "Delivery of", "pay": "Payment of", "clear": "Clearance of",
    "approve": "Approval of", "schedule": "Scheduling of", "investigate": "Investigation into", "handle": "Handling of",
    "process": "Processing of", "issue": "Issuance of", "transfer": "Transfer of", "hire": "Hiring of",
    "recruit": "Recruitment of", "train": "Training of", "assign": "Assignment of", "allocate": "Allocation of",
    "count": "Count of", "audit": "Audit of", "reconcile": "Reconciliation of", "print": "Printing of",
    "remove": "Removal of", "shift": "Relocation of", "move": "Relocation of", "return": "Return of",
    "implement": "Implementation of", "coordinate": "Coordination of", "maintain": "Maintenance of",
    "increase": "Increase in", "reduce": "Reduction in", "stop": "Discontinuation of", "start": "Commencement of",
    "plan": "Planning of", "settle": "Settlement of", "secure": "Security of", "lock": "Locking of",
}
PROBLEM = re.compile(r"^(?:the\s+|our\s+|my\s+)?(?P<thing>.{2,60}?)\s+(?:is|are|has been|have been|was|were|seems?|keeps?)?\s*"
                     r"(?P<what>(?:has |have )?not been (?:working|functioning)|not working|not functioning|broken|leaking|out of order|damaged|faulty|malfunctioning|"
                     r"down|stuck|blocked|jammed|tripping|making noise|overheating|not cooling|not heating|dead)\b", re.I)
WHEN_SUFFIX = re.compile(r"\b(today|tonight|tomorrow|this week|next week|this month|next month|(?:on\s+)?"
                         r"(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday))\b", re.I)


def _clean(text: str) -> str:
    t = w.formalize(w.tidy(text or ""))
    t = re.sub(r"(?i)^(?:dear|hi|hello)\b[^.,!?]*[.,!?]\s*", "", t)
    t = re.sub(r"(?i)^(?:please|kindly|pls|plz)\s+", "", t)
    t = re.sub(r"(?i)^(?:could|can|would|will) you (?:kindly |please )?", "", t)
    return t.strip(" .")


def _cap(text: str, words: int = 8) -> str:
    """Shorten a phrase at a natural break, at most `words` words."""
    t = re.split(r"\s*[,;:]\s*|\s+(?:and then|so that|because|as|since|which|who)\s+", text.strip())[0]
    parts = t.split()
    if len(parts) > words:
        # cut before a later preposition so the subject doesn't end mid-phrase
        cut = words
        for i in range(words, 2, -1):
            if parts[i].lower() in ("for", "to", "from", "with", "in", "on", "at", "by", "of", "and", "after", "before"):
                cut = i
                break
        parts = parts[:cut]
    while parts and parts[-1].lower() in w.SMALL_WORDS | {"the", "a", "an", "is", "are", "be", "your", "our", "my"}:
        parts.pop()
    return " ".join(parts)


def _when(text: str) -> str:
    m = WHEN_SUFFIX.search(text)
    if not m:
        return ""
    v = re.sub(r"(?i)^on\s+", "", m.group(1))
    return v[:1].upper() + v[1:]


def _with_when(subject: str, text: str) -> str:
    wv = _when(text)
    if wv and wv.lower() not in subject.lower() and len(subject) < 60:
        return f"{subject} – {w._title_subject(wv)}"
    return subject


def _strip_when(text: str) -> str:
    t = text
    while True:
        found, rest = w._take_when(t)
        if not found:
            return t
        t = rest


def make_subject(note: str) -> str:
    """Best-effort subject for free text (first meaningful sentence decides)."""
    sents = [s for s in w._split_sentences(note or "") if not w.FILLER_SENTENCE.match(s.strip())]
    if not sents:
        return "Message"
    full = " ".join(sents)
    s = _clean(sents[0])
    T = w._title_subject

    # "have the AC of room 204 repaired" -> "Repair of AC of Room 204"
    m = re.match(r"(?i)^(?:get|have)\s+(?:the\s+)?(.+?)\s+(repaired|fixed|resolved|cleaned|checked|replaced|installed|serviced)\b(.*)$", s)
    if m:
        noun = {"repaired": "Repair of", "fixed": "Repair of", "resolved": "Resolution of", "cleaned": "Cleaning of",
                "checked": "Inspection of", "replaced": "Replacement of", "installed": "Installation of",
                "serviced": "Servicing of"}[m.group(2).lower()]
        return _with_when(f"{noun} {T(_cap(_strip_when(m.group(1)), 7))}", full)

    # "I have not yet received the report" -> "Report Not Yet Received"
    m = re.match(r"(?i)^(?:I|we)\s+(?:have|has)\s+not\s+(?:yet\s+)?received\s+(?:the\s+|your\s+|any\s+)?(.+?)(?:\s+yet)?$", s)
    if m:
        return f"{T(_cap(_strip_when(m.group(1)), 6))} Not Yet Received"

    # "Please find the attached invoice" -> "Invoice"
    m = re.match(r"(?i)^find\s+(?:the\s+|herewith\s+)?(?:attached|enclosed)\s+(?:the\s+)?(.+)$", s)
    if m:
        return _with_when(T(_cap(m.group(1), 7)), full)

    # Leave / absence / late arrival (about me)
    m = re.search(r"(?i)\b(?:I am|I will be|I'll be|I shall be)\s+on\s+leave\b(.*)", s)
    if m or re.search(r"(?i)\bI (?:would like to|want to|need to) (?:take|apply for|request) (?:a )?leave\b", s):
        dates = re.search(r"(?i)\bfrom\s+(.+?)\s+(?:to|till|until)\s+([^,.;]+?)(?=$|[,.;]|\s+(?:and|ahmed|\w+ will))", s)
        when = f"{dates.group(1)} to {dates.group(2)}" if dates else _when(s)
        label = "Leave Notification" if m else "Leave Request"
        return f"{label} – {T(when)}" if when else label
    if re.search(r"(?i)\bI (?:will|shall) be (?:late|delayed)\b", s):
        return _with_when("Late Arrival", s)
    if re.search(r"(?i)\bI (?:will|shall) (?:not be (?:available|in the office|coming)|be (?:absent|out of (?:the )?office|unavailable))\b", s):
        return _with_when("Unavailability Notice", s)

    # Something broken
    m = PROBLEM.search(s)
    if m:
        thing = _cap(re.sub(r"(?i)^(?:the|our|my)\s+", "", m.group("thing")), 6)
        what = m.group("what").lower()
        label = "Leakage Repair Required" if what == "leaking" else "Repair Required"
        return f"{T(thing)} – {label}"

    # Payment pending
    m = re.search(r"(?i)^(?:the\s+)?(.{3,60}?)\s+(?:is|are|has|have)\s+(?:not been|not|still not)\s+(?:paid|cleared|settled)", s)
    if m:
        thing = m.group(1)
        month = re.search(r"(?i)\bfor\s+((?:january|february|march|april|may|june|july|august|september|october|november|december)(?:\s+\d{4})?)", thing)
        thing = _strip_when(re.sub(r"(?i)\s+for\s+(?:january|february|march|april|may|june|july|august|september|october|november|december)(?:\s+\d{4})?", "", thing))
        return f"Pending Payment – {T(_cap(thing, 6))}" + (f" ({T(month.group(1))})" if month else "")

    # Non-compliance
    m = re.search(r"(?i)^(?:the\s+)?(.{3,40}?)\s+(?:is|are|was|were)\s+not\s+(wearing|following|using|maintaining|complying with|attending|reporting)\s+(.+)$", s)
    if m:
        return f"Non-Compliance – {T(_cap(m.group(1), 4))} Not {T(m.group(2))} {T(_cap(_strip_when(m.group(3)), 5))}"

    # Why wasn't X done -> clarification
    m = re.search(r"(?i)\bwhy\s+(?:the\s+)?(.{3,50}?)\s+(?:was|were|is|are|has|have)\s+not\s+(?:been\s+)?(\w+)", s)
    if m:
        return f"{T(_cap(m.group(1), 5))} Not {T(m.group(2))} – Clarification Required"

    # Arrivals / visits / events
    m = re.search(r"(?i)\b(?:we have |there is |there will be )?(?:an? )?((?:vip |important |foreign |new )?(?:guest|guests|visitor|visitors|delegation|client|clients|inspection|auditor|auditors|team))\s+(?:is |are |will be )?(arriving|visiting|coming|checking in|expected)", s)
    if m:
        label = "Arrival" if m.group(2).lower() in ("arriving", "coming", "checking in", "expected") else "Visit"
        return _with_when(f"{T(m.group(1))} {label}", full)

    # Deliveries: "the new staff uniforms have arrived"
    m = re.search(r"(?i)^(?:the\s+)?(.{3,50}?)\s+(?:has|have)\s+(?:arrived|been delivered|been received|reached)\b", s)
    if m:
        return f"Arrival of {T(_cap(m.group(1), 6))}"

    # Needs / requests
    m = re.search(r"(?i)^(?:I|we)?\s*(?:need|require|would like(?: to request)?|request)\s+(?:a |an |the )?(quotations?|quotes?)\s+(?:for|of)\s+(.+)$", s)
    if m:
        item = re.sub(r"(?i)\s+from\s+\d+\s+(?:suppliers|vendors).*$", "", m.group(2))
        return f"Request for Quotation – {T(_cap(_strip_when(item), 6))}"
    m = re.search(r"(?i)^(?:I|we)?\s*(?:need|require|would like to request|would like|request)\s+(?:a |an |the )?(.+)$", s)
    if m and not re.match(r"(?i)(to|you|your|that)\b", m.group(1)):
        return _with_when(f"Request for {T(_cap(_strip_when(m.group(1)), 7))}", s)

    # "X is due (this week)"
    m = re.search(r"(?i)^(?:the\s+)?(.{3,50}?)\s+(?:is|are)\s+(?:due|pending|overdue)\b", s)
    if m:
        state = re.search(r"(?i)\b(due|pending|overdue)\b", s).group(1).title()
        return _with_when(f"{T(_cap(m.group(1), 6))} {state}", s)

    # Instruction: verb + object -> "Arrangement of 20 Chairs ..."
    m = re.match(r"(?i)^(?:ensure|make sure)\s+(?:that\s+)?(.+)$", s)
    if m:
        obj = re.sub(r"(?i)\b(is|are)\s+(\w+ed)\b", r"to Be \2", _strip_when(m.group(1)), count=1)
        return f"Action Required – {T(_cap(obj, 8))}"
    m = re.match(r"(?i)^(\w+)\s+(.+)$", s)
    if m and m.group(1).lower() in NOUNS:
        obj = _strip_when(m.group(2))
        obj = re.sub(r"(?i)^(?:me|us)\s+", "", obj)
        obj = re.sub(r"(?i)^(?:it|this|that|them)\b\s*", "", obj).strip()
        obj = re.sub(r"(?i)^(?:the|a|an|our|my|your)\s+", "", obj)
        if obj:
            return _with_when(f"{NOUNS[m.group(1).lower()]} {T(_cap(obj, 7))}", full)

    # Statement about the company/team: "we have ...", "the office will be closed on monday"
    m = re.match(r"(?i)^(?:the\s+)?(.{3,40}?)\s+will be\s+(closed|open|shut|unavailable|off|renovated|painted|serviced|inspected)\b", s)
    if m:
        return _with_when(f"{T(_cap(m.group(1), 5))} {T(m.group(2))}", s)

    # Fallback: first clause, without "I/we ..." openers, timing kept as a suffix
    base = re.sub(r"(?i)^(?:I|we)\s+(?:would like to|have to|need to|want to|am|are|have|will|shall)\s+", "", s)
    base = re.sub(r"(?i)^(?:there (?:is|are)\s+)", "", base)
    base = re.sub(r"(?i)^(?:the|a|an)\s+", "", _strip_when(base))
    return _with_when(T(_cap(base, 7)) or "Message", full)
