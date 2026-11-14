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
    "implement": "Implementation of", "distribute": "Distribution of", "execute": "Execution of", "deploy": "Deployment of",
    "launch": "Launch of", "test": "Testing of", "conduct": "Conduct of", "present": "Presentation of",
    "design": "Design of", "create": "Creation of", "write": "Drafting of", "draft": "Drafting of", "coordinate": "Coordination of", "maintain": "Maintenance of",
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
    # "Qasim, the generator ..." -> "the generator ..." (the person being addressed)
    t = re.sub(r"^(?:[A-Z][a-z]+(?: [A-Z][a-z]+)?|Sir|Madam)\s*,\s+(?=[a-z]|The\b|Please\b|Kindly\b)", "", t)
    t = re.sub(r"(?i)^(?:please|kindly|pls|plz)\s+", "", t)
    # "please note that X" / "I would like to inform you that X" -> "X"
    t = re.sub(r"(?i)^(?:note that|please note that|kindly note that|this is to inform you that|I (?:would like to|want to|wish to) "
               r"(?:inform|let) you (?:know )?that|I am writing to (?:inform you|let you know) that|for your information,?)\s+", "", t)
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
    t = re.sub(r"(?i)\s*\b(?:of|from|during|for)?\s*(?:last night|yesterday(?: night)?|this morning|this evening|tonight|last evening)\b", "", text)
    while True:
        found, rest = w._take_when(t)
        if not found:
            return t
        t = rest


ROLES_TO_CALL = r"(plumber|electrician|technician|carpenter|mechanic|painter|cleaner|security|guard|driver|doctor|it team|it support|engineer|vendor|supplier)"
VAGUE = re.compile(r"^(?:do the needful|look into (?:this|the|it)(?: matter| issue)?|take (?:the )?(?:necessary )?action|"
                   r"(?:please )?handle (?:this|it)|check (?:this|it)|see (?:this|to it)|as discussed|for your information|fyi|"
                   r"for your (?:kind )?(?:attention|action|review|approval))$", re.I)
ADJ = r"(very |too |so |extremely |quite )?(high|low|late|slow|poor|bad|dirty|noisy|expensive|delayed|incorrect|wrong|missing)"


def _special(s: str, full: str) -> str | None:
    """Patterns the general rules got wrong (each checked on the first sentence, `full` for context)."""
    T = w._title_subject
    low = s.lower().strip(" .")

    # "the package should be prepared by 16 november and implemented by 23 november"
    #   -> "Preparation and Implementation of Package – By Mon 16 Nov"
    m = re.match(r"(?i)^(?:the\s+|our\s+|your\s+|this\s+|all\s+(?:the\s+)?)?(.{2,60}?)\s+(?:should|must|shall|needs? to|has to|"
                 r"have to|is to|are to|will need to|is required to|ought to)\s+be\s+(\w+)\b(.*)$", s)
    if m:
        import task_finder
        verbs = [m.group(2)] + re.findall(r"(?i)\band\s+(?:then\s+)?(\w+ed)\b", m.group(3))
        nouns = []
        for v in verbs:
            base = task_finder.TO_BASE.get(v.lower())
            if base and base in NOUNS:
                nouns.append(NOUNS[base].rsplit(" ", 1)[0])  # "Preparation of" -> "Preparation"
        if nouns:
            when, _ = w._take_when(m.group(3))
            head = " and ".join(dict.fromkeys(nouns))
            sub = f"{head} of {T(_cap(m.group(1), 6))}"
            return f"{sub} – {w.deadline_label(when)}" if when else sub

    # "kindly look into this matter", "please do the needful" -> nothing specific to name
    if VAGUE.match(low):
        return "Action Required"
    # "please call the plumber, there is a leakage in the washroom of 2nd floor"
    m = re.match(rf"(?i)^(?:call|contact|send|arrange|get)\s+(?:the\s+|a\s+|an\s+)?{ROLES_TO_CALL}\b(.*)$", s)
    if m:
        why = re.search(r"(?i)\b(leak(?:age)?|blockage|short circuit|fault|breakdown|damage|fire|fight|theft)\b(?:\s+(?:in|at|of|on)\s+(?:the\s+)?([^,.;]+))?", full)
        role = T(m.group(1).title() if m.group(1).lower() not in ("it team", "it support") else "IT Support")
        if why:
            place = f" in {T(_cap(_strip_when(why.group(2)), 6))}" if why.group(2) else ""
            return f"{T(why.group(1).capitalize())}{place} – {role} Required"
        return _with_when(f"{role} Required", full)
    # "make a list of all broken furniture" / "prepare a report on ..."
    m = re.match(r"(?i)^(?:make|prepare|create|compile)\s+(?:a\s+|an\s+|the\s+)?(list|report|summary|record|schedule|plan|roster)\s+(of|on|for|about)\s+(?:all\s+(?:the\s+)?|the\s+)?(.+)$", s)
    if m:
        return _with_when(f"{T(m.group(1).capitalize())} of {T(_cap(_strip_when(m.group(3)), 6))} Required", full)
    # "update me about the guest complaint of room 305"
    m = re.match(r"(?i)^(?:update|inform|brief)\s+(?:me|us)\s+(?:about|on|regarding|of)\s+(?:the\s+)?(.+)$", s)
    if m:
        return f"Update Requested – {T(_cap(_strip_when(m.group(1)), 7))}"
    # "i want to discuss the budget with you"
    m = re.match(r"(?i)^(?:I|we)\s+(?:would like|want|need|wish)\s+to\s+(?:discuss|talk about|talk to you about|speak (?:to you )?about)\s+(?:the\s+)?(.+?)(?:\s+with\s+you)?$", s)
    if m:
        return _with_when(f"Discussion: {T(_cap(_strip_when(m.group(1)), 6))}", full)
    # "electricity bill of last month is very high, find out the reason"
    m = re.match(rf"(?i)^(?:the\s+|our\s+)?(.{{3,50}}?)\s+(?:is|are|was|were|seems?|has been|have been)\s+{ADJ}\b", s)
    if m:
        thing = _cap(re.sub(r"(?i)\s+(?:of|for)\s+(?:the\s+)?(?:last|this|previous|current)\s+(?:month|week)$", "", m.group(1)), 6)
        return f"{T(m.group(3).capitalize())} {T(thing)} – Review Required"
    # "tell ahmed his performance is very good this month" / "great work on the audit"
    if re.search(r"(?i)\b(?:performance|work|effort|job)\b.*\b(?:good|great|excellent|outstanding|appreciated)\b|"
                 r"\b(?:good|great|excellent|outstanding)\s+(?:work|job|performance|effort)\b", low):
        return _with_when("Appreciation for Your " + ("Performance" if "performance" in low else "Work"), full)
    # payments: "dont release any payment to abc traders" / "do not stop payment of abc traders"
    m = re.match(r"(?i)^(?:do not|don't|dont|never)\s+(release|make|process|stop|hold)\s+(?:any\s+)?(?:further\s+)?payments?\s+(?:to|of|for)\s+(.+?)(?:\s+(?:until|till)\b.*)?$", s)
    if m:
        who = T(_cap(_strip_when(m.group(2)), 5))
        return f"Payment on Hold – {who}" if m.group(1).lower() in ("release", "make", "process") else f"Continue Payment – {who}"
    # "the new staff will join from monday, please arrange their id cards"
    m = re.match(r"(?i)^(?:the\s+)?(.{3,40}?)\s+(?:will|is going to|are going to|shall)\s+(join|start|arrive|visit|leave|resign)\b", s)
    if m:
        verb = {"join": "Joining", "start": "Starting", "arrive": "Arrival", "visit": "Visit", "leave": "Leaving",
                "resign": "Resignation"}[m.group(2).lower()]
        return _with_when(f"{T(_cap(m.group(1), 5))} {verb}", s)
    # "make sure all staff wear uniform from tomorrow"
    m = re.match(r"(?i)^(?:ensure|make sure)\s+(?:that\s+)?(all\s+(?:the\s+)?staff|everyone|all employees|staff|the team|all departments)\s+(?:should\s+|must\s+|will\s+)?(\w+)\s+(.+)$", s)
    if m:
        return _with_when(f"Action Required: {T(m.group(1).replace('the ', ''))} to {T(m.group(2))} {T(_cap(_strip_when(m.group(3)), 5))}", full)
    return None


def make_subject(note: str) -> str:
    """Best-effort subject for free text (first meaningful sentence decides)."""
    sents = [s for s in w._split_sentences(note or "") if not w.FILLER_SENTENCE.match(s.strip())]
    if not sents:
        return "Message"
    full = " ".join(sents)
    s = _clean(sents[0])
    T = w._title_subject
    special = _special(s, full)
    if special:
        return special

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
        dates = re.search(r"(?i)\bfrom\s+(.+?)\s+(?:to|till|until)\s+([^,.;]+?)(?=$|[,.;]|\s+(?:and|for|due|because|as|since|\w+ will)\b)", s)
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
    m = re.match(r"(?i)^(?:send|share|submit|provide|forward|email|give)\s+(?:(?:it\s+)?(?:with|to)\s+(?:me|us)\s+|me\s+|us\s+)?(?:the\s+|your\s+|all\s+the\s+)?(.+)$", s)
    if m and re.search(rf"(?i)\b(?:{w.DOC_WORDS})\b", m.group(1)):
        obj, whens = m.group(1), []
        while True:
            found, rest = w._take_when(obj)
            if not found:
                break
            whens.append(found)
            obj = rest
        if re.search(r"(?i)\b(?:at the earliest|as soon as possible|asap|urgently)\b", obj):
            whens.append("as soon as possible")
            obj = re.sub(r"(?i)\s*\b(?:at the earliest|as soon as possible|asap|urgently)\b", "", obj)
        obj = re.sub(r"(?i)\s+(?:with|to)\s+(?:me|us)\b", "", _strip_when(obj)).strip()
        # "for october" belongs to the document ("Sales Figures for October"), not the deadline
        for x in [x for x in whens if w.BARE_MONTH.fullmatch(re.sub(r"(?i)^(?:for|of)\s+", "", x))]:
            whens.remove(x)
            obj = f"{obj} {x}"
        when = whens[0] if whens else ""
        obj = re.sub(r"(?i)\b(for|of) (jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)\b",
                     lambda x: f"{x.group(1)} {x.group(2).capitalize()}", obj)
        sub = f"Request: {T(w.short_title(obj))}"
        return f"{sub} – {w.deadline_label(when)}" if when else sub
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
