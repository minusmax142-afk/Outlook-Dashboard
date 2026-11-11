"""
"Write for me": turns a short note into a professional email, using rules and templates only
(no AI service; nothing leaves this PC).

    parse(note)                  -> who to send it to (phrases), and the instruction itself
    write(note, recipients, me)  -> {subject, body, intent}

Examples of notes it understands:
    hold salaries of abdul rehman store manager, send to qasim
    tell qasim to release the salary of ahmed driver for october
    ask accounts to send the stock report by friday
    remind bilal about the kitchen inventory, cc qasim
    schedule a meeting with the department heads tomorrow at 3 pm about the new SOP
    inform all staff that the office will be closed on monday
"""

from __future__ import annotations

import re

EMAIL = re.compile(r"^[^@\s<>;,]+@[^@\s<>;,]+\.[^@\s<>;,]+$")

# ---------------------------------------------------------------------------
# Text tidy-up

SHORTHAND = {
    "pls": "please", "plz": "please", "plss": "please", "kindly": "kindly", "u": "you", "ur": "your",
    "r": "are", "asap": "as soon as possible", "thx": "thanks", "thnx": "thanks", "msg": "message",
    "info": "information", "mgr": "manager", "dept": "department", "deptt": "department",
    "bcz": "because", "bcoz": "because", "coz": "because", "cuz": "because", "b/c": "because",
    "tmrw": "tomorrow", "tmr": "tomorrow", "tomorow": "tomorrow", "tommorow": "tomorrow",
    "tommorrow": "tomorrow", "yday": "yesterday", "wk": "week", "hrs": "hours", "mins": "minutes",
    "approx": "approximately", "dont": "do not", "doesnt": "does not", "didnt": "did not",
    "cant": "cannot", "wont": "will not", "isnt": "is not", "arent": "are not", "wasnt": "was not",
    "werent": "were not", "havent": "have not", "hasnt": "has not", "shouldnt": "should not",
    "couldnt": "could not", "im": "I am", "ive": "I have", "id": "I would", "ill": "I will",
    "thats": "that is", "eod": "the end of the day", "eom": "the end of the month",
    "w.e.f": "with effect from", "wef": "with effect from", "acc": "account", "amt": "amount",
    "qty": "quantity", "reqd": "required", "recd": "received", "pmt": "payment", "sal": "salary",
}
SPELLING = {
    "recieve": "receive", "recieved": "received", "seperate": "separate", "untill": "until",
    "wil": "will", "teh": "the", "salry": "salary", "salery": "salary", "salaray": "salary",
    "sallary": "salary", "salaris": "salaries", "managr": "manager", "manger": "manager",
    "maneger": "manager", "accountent": "accountant", "acount": "account", "acounts": "accounts",
    "reprot": "report", "repot": "report", "meating": "meeting", "meetting": "meeting",
    "shedule": "schedule", "schedual": "schedule", "adress": "address", "occured": "occurred",
    "definately": "definitely", "goverment": "government", "buisness": "business",
    "beleive": "believe", "calender": "calendar", "commited": "committed", "concious": "conscious",
    "existance": "existence", "foriegn": "foreign", "garantee": "guarantee", "immediatly": "immediately",
    "imediately": "immediately", "independant": "independent", "maintainance": "maintenance",
    "maintenence": "maintenance", "neccessary": "necessary", "necesary": "necessary",
    "noticable": "noticeable", "payed": "paid", "persue": "pursue", "posession": "possession",
    "prefered": "preferred", "realy": "really", "refered": "referred", "relevent": "relevant",
    "responsibilty": "responsibility", "sucess": "success", "succesful": "successful",
    "tommorow": "tomorrow", "truely": "truly", "wich": "which", "whith": "with", "becuase": "because",
    "becasue": "because", "plese": "please", "pleae": "please", "infrom": "inform", "imform": "inform",
    "staf": "staff", "emplyee": "employee", "employe": "employee", "employes": "employees",
    "attendence": "attendance", "inventry": "inventory", "invoce": "invoice", "quatation": "quotation",
    "qoutation": "quotation", "aproval": "approval", "aprove": "approve", "aproved": "approved",
    "approvel": "approval", "documnet": "document", "docment": "document", "submitt": "submit",
    "recipt": "receipt", "reciept": "receipt", "purchace": "purchase", "dicuss": "discuss",
    "discus": "discuss", "regading": "regarding", "regarging": "regarding", "reagrding": "regarding",
    "mondey": "monday", "tuseday": "tuesday", "tusday": "tuesday", "wenesday": "wednesday",
    "wedensday": "wednesday", "thursady": "thursday", "thrusday": "thursday", "firday": "friday",
    "saturaday": "saturday", "febuary": "february", "agust": "august", "septmber": "september",
    "novmber": "november", "decmber": "december",
}
PROPER = {d: d.capitalize() for d in (
    "monday tuesday wednesday thursday friday saturday sunday january february march april may june "
    "july august september october november december").split()}
PROPER["may"] = "may"  # too ambiguous ("you may ...") — months written as "May 5" stay as typed
ACRONYMS = {"hr": "HR", "it": "it", "ceo": "CEO", "cfo": "CFO", "coo": "COO", "gm": "GM", "agm": "AGM",
            "md": "MD", "sop": "SOP", "sops": "SOPs", "po": "PO", "pkr": "PKR", "rs": "Rs.", "f&b": "F&B",
            "fnb": "F&B", "ac": "AC", "cctv": "CCTV", "pos": "POS", "kpi": "KPI", "kpis": "KPIs", "pdf": "PDF",
            "id": "ID", "vat": "VAT", "gst": "GST", "ntn": "NTN", "eobi": "EOBI", "pessi": "PESSI"}
WORD = re.compile(r"[A-Za-z][A-Za-z.&/']*")


def _fix_word(m: re.Match) -> str:
    w = m.group(0)
    low = w.lower().rstrip(".")
    trail = w[len(low):] if w.lower().startswith(low) else ""
    if low in SPELLING:
        rep = SPELLING[low]
    elif low in SHORTHAND and low not in ("id", "ill", "r", "u") or low in ("u", "r") and len(w) == 1:
        rep = SHORTHAND[low]
    elif low == "i":
        return "I" + trail
    else:
        return w
    if w[:1].isupper() and rep[:1].islower():
        rep = rep[:1].upper() + rep[1:]
    return rep + trail


def tidy(text: str) -> str:
    """Spelling/shorthand fixes, 'i' -> 'I', day/month capitals, spacing and punctuation."""
    t = re.sub(r"\s+", " ", (text or "")).strip()
    t = WORD.sub(_fix_word, t)
    t = re.sub(r"\b(" + "|".join(k for k in PROPER if k != "may") + r")\b",
               lambda m: PROPER[m.group(1).lower()], t, flags=re.I)
    t = re.sub(r"\b(" + "|".join(re.escape(k) for k in ACRONYMS if k not in ("it", "id")) + r")\b",
               lambda m: ACRONYMS[m.group(1).lower()], t, flags=re.I)
    t = re.sub(r"\s+([,.;:!?])", r"\1", t)
    t = re.sub(r"([,;:])(?=[A-Za-z])", r"\1 ", t)
    t = re.sub(r"([.!?]){2,}", r"\1", t)
    t = re.sub(r"\b(\w+) \1\b", r"\1", t, flags=re.I)  # "the the"
    t = re.sub(r"(^|[.!?]\s+)([a-z])", lambda m: m.group(1) + m.group(2).upper(), t)
    return t


def sentence(text: str) -> str:
    t = tidy(text)
    if t and t[-1] not in ".!?":
        t += "."
    return t[:1].upper() + t[1:]


def _lower_first(text: str) -> str:
    """Lower-cases the first letter unless the first word is a name/acronym ('I', 'HR', 'Friday')."""
    if not text:
        return text
    first = text.split(" ", 1)[0]
    if first == "I" or first.isupper() and len(first) > 1 or first.rstrip(".,") in PROPER.values():
        return text
    return text[:1].lower() + text[1:]


def _strip_end(text: str) -> str:
    return re.sub(r"[\s.,;:!]+$", "", text or "")


# ---------------------------------------------------------------------------
# People and job titles

ROLE_PREFIX = (r"(?:assistant|asst\.?|deputy|senior|sr\.?|junior|jr\.?|head|chief|general|store|stores|accounts?|"
               r"hr|it|sales|purchase|purchasing|procurement|front ?office|f&b|fnb|admin|administration|"
               r"maintenance|operations|marketing|finance|kitchen|restaurant|banquet|housekeeping|security|"
               r"duty|night|shift|site|project|office|branch|area|regional|executive|sous|pastry|outlet|"
               r"inventory|payroll|cash|guest relations?)")
ROLE_CORE = (r"(?:manager|officer|supervisor|accountant|chef|cashier|receptionist|keeper|storekeeper|guard|"
             r"driver|waiter|waitress|engineer|technician|clerk|executive|coordinator|assistant|director|"
             r"lead|incharge|in-charge|head|attendant|steward|cook|helper|electrician|plumber|carpenter|"
             r"gardener|cleaner|sweeper|peon|operator|analyst|controller|auditor|admin|associate|captain|"
             r"bartender|barista|host|hostess|porter|bellboy|concierge|trainee|intern|staff)")
ROLE = re.compile(rf"\b((?:{ROLE_PREFIX}\s+){{0,2}}{ROLE_CORE}|ceo|cfo|coo|gm|agm|md)\b", re.I)
ROLE_AT_END = re.compile(rf"[\s,(-]*\b((?:{ROLE_PREFIX}\s+){{0,2}}{ROLE_CORE}|ceo|cfo|coo|gm|agm|md)\)?\s*$", re.I)

COMMON = set("""
a an the and or of for to from with by on in at as is are was were be been being this that these those
it its our your my his her their them him he she they we you i me us all any each every some no not
please kindly hold stop release salary salaries pay payment wages employee employees staff team
department month week day today tomorrow yesterday until till before after about regarding against
immediately effect notice further new old next last this current report reports send share submit
meeting meet call schedule approve approved reject leave request ask tell inform remind email mail
also only just very more less due because since so but if then than when where who what which how
manager officer supervisor store accounts account hr office will would should could can may must
have has had do does did done get got make made take given give keep put set up down out
""".split())


def _title_name(words: str) -> str:
    out = []
    for w in words.split():
        if any(c.isupper() for c in w):
            out.append(w)
        elif w.lower() in ("bin", "binte", "bint", "ul", "ud", "un", "al", "e", "van", "de"):
            out.append(w.lower())
        else:
            out.append("-".join(p[:1].upper() + p[1:] for p in w.split("-")))
    return " ".join(out)


def _title_role(role: str) -> str:
    parts = []
    for w in re.sub(r"\s+", " ", role.strip()).split(" "):
        low = w.lower().rstrip(".")
        if low in ACRONYMS and low not in ("it",) or low in ("it", "hr", "gm", "md", "ceo", "cfo", "coo", "agm"):
            parts.append(ACRONYMS.get(low, low.upper()) if low != "it" else "IT")
        elif low in ("asst", "sr", "jr"):
            parts.append({"asst": "Assistant", "sr": "Senior", "jr": "Junior"}[low])
        elif low == "fnb":
            parts.append("F&B")
        else:
            parts.append("-".join(p[:1].upper() + p[1:].lower() for p in w.split("-")))
    return " ".join(parts)


def person(phrase: str) -> dict:
    """'abdul rehman store manager' -> {name: 'Abdul Rehman', role: 'Store Manager'}."""
    p = re.sub(r"^(?:the|our|my|mr\.?|mrs\.?|ms\.?|miss|sir|madam|dr\.?|engr\.?)\s+", "", phrase.strip(" ,.;"), flags=re.I)
    p = re.sub(r"^(?:the|our|my)\s+", "", p, flags=re.I)
    role = ""
    m = ROLE_AT_END.search(p)
    if m:
        role = _title_role(m.group(1))
        p = p[: m.start()].strip(" ,(-")
    p = re.sub(r"\s*\b(?:who is|who's|working as|as)\s*$", "", p, flags=re.I)
    name = _title_name(p) if p else ""
    return {"name": name, "role": role}


def person_text(pp: dict, style: str = "body") -> str:
    name, role = pp["name"], pp["role"]
    if name and role:
        return f"{name} ({role})" if style == "subject" else f"{name}, {role}"
    if role:
        return role if style == "subject" else f"the {role}"
    return name


def _people_in(phrase: str) -> list[dict]:
    parts = [x for x in re.split(r"\s*(?:,|\band\b|&|\+)\s*", phrase or "", flags=re.I) if x.strip()]
    people = [person(x) for x in parts]
    # "abdul rehman and ahmed, store managers" -> leave as-is; drop empties.
    return [p for p in people if p["name"] or p["role"]]


NAME_ROLE = re.compile(rf"\b(of|for|to|from|with|by|against)\s+((?:(?!(?:the|a|an|all|our|my|your|new|old|this|that)\b)[a-z][a-z'-]*\s+){{1,3}}?)({ROLE.pattern[2:-2]})\b", re.I)
COMPANY = re.compile(r"\b((?:[a-z][\w&'-]*\s+){1,3})(traders|enterprises|industries|corporation|company|associates|"
                     r"sons|brothers|group|pvt\.?|ltd\.?|limited|llc|inc\.?|international|solutions|services)\b", re.I)


def names_in(text: str) -> str:
    """'leave of ali receptionist' -> 'leave of Ali (Receptionist)'; 'abc traders' -> 'ABC Traders'."""
    def nr(m):
        name = m.group(2).strip()
        if not name or all(w.lower() in COMMON for w in name.split()):
            return m.group(0)
        return f"{m.group(1)} {person_text({'name': _title_name(name), 'role': _title_role(m.group(3))}, 'subject')}"

    def co(m):
        allw = m.group(1).split()
        n = 0  # company name = the words right before "Traders" that aren't ordinary words
        while n < len(allw) and allw[-1 - n].lower() not in COMMON and allw[-1 - n].lower() not in SMALL_WORDS \
                and allw[-1 - n].lower() not in ("pending", "invoices", "invoice", "payment", "payments", "order", "orders"):
            n += 1
        if not n:
            return m.group(0)
        lead = " ".join(allw[: len(allw) - n])
        fixed = " ".join(w.upper() if len(w) <= 3 else _title_name(w) for w in allw[len(allw) - n:])
        return f"{lead}{' ' if lead else ''}{fixed} {_title_role(m.group(2))}"

    return COMPANY.sub(co, NAME_ROLE.sub(nr, text))


def _list_text(items: list[str]) -> str:
    if len(items) <= 1:
        return "".join(items)
    return ", ".join(items[:-1]) + " and " + items[-1]


# ---------------------------------------------------------------------------
# Time, reason, amount

DAY = r"(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday)"
MONTH = r"(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|june?|july?|aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)"
DATEWORD = (rf"(?:today|tonight|tomorrow|day after tomorrow|(?:this|next|coming)\s+(?:week|month|{DAY})|{DAY}|"
            rf"(?:the\s+)?end\s+of\s+(?:the\s+)?(?:day|week|month)|eod|eom|"
            rf"\d{{1,2}}(?:st|nd|rd|th)?\s+(?:of\s+)?{MONTH}(?:\s+\d{{4}})?|{MONTH}\s+\d{{1,2}}(?:st|nd|rd|th)?(?:,?\s+\d{{4}})?|"
            rf"\d{{1,2}}[/.-]\d{{1,2}}(?:[/.-]\d{{2,4}})?|{MONTH}(?:\s+\d{{4}})?)")
TIMEWORD = r"(?:\d{1,2}(?::\d{2})?\s*(?:am|pm|a\.m\.|p\.m\.)|\d{1,2}:\d{2}|noon|midday)"
WHEN = re.compile(
    rf"\b(?:(?:by|before|until|till|on|from|starting(?:\s+from)?|effective(?:\s+from)?|with effect from|w\.?e\.?f\.?|"
    rf"for|of|after|at|within)\s+)?(?:{DATEWORD})(?:\s+(?:at|by|around)\s+{TIMEWORD})?"
    rf"|\b(?:at|by|around)\s+{TIMEWORD}(?:\s+(?:on\s+)?{DATEWORD})?"
    rf"|\bwith immediate effect\b|\bimmediately\b|\buntil further (?:notice|orders?|instructions?)\b"
    rf"|\bfor (?:the )?(?:current|this|next|last|previous) (?:month|week)\b|\bfor \d+ (?:days?|weeks?|months?)\b"
    rf"|\bwithin \d+ (?:days?|hours?|weeks?)\b|\bas soon as possible\b|\basap\b",
    re.I,
)
REASON = re.compile(r"[,;]?\s*\b(?:due to|because of|because|owing to|on account of|in view of|as a result of|"
                    r"for the reason that|since|reason:?)\s+(.+?)(?=\s*(?:[,;.]|$|\b(?:until|till|from|by|and send|send)\b))",
                    re.I)
AMOUNT = re.compile(r"(?:rs\.?|pkr|rupees)\s?[\d,]+(?:\.\d+)?(?:\s?(?:k|lac|lakh|million))?|[\d,]+(?:\.\d+)?\s?(?:k|lac|lakh|million)?\s?(?:rs\.?|pkr|rupees)\b|"
                    r"\b\d+\s+days?(?:'s)?\s+(?:salary|pay|wages)\b|\b\d+(?:\.\d+)?\s?%", re.I)


def _take(rx: re.Pattern, text: str, group: int = 0) -> tuple[str, str]:
    """(match, text without it)."""
    m = rx.search(text)
    if not m:
        return "", text
    rest = (text[: m.start()] + " " + text[m.end():])
    return m.group(group).strip(), re.sub(r"\s+", " ", rest).strip(" ,;")


BARE_MONTH = re.compile(rf"(?i){MONTH}(?:\s+\d{{4}})?")


def _take_when(text: str) -> tuple[str, str]:
    for m in WHEN.finditer(text):
        if BARE_MONTH.fullmatch(m.group(0).strip()):
            continue
        rest = text[: m.start()] + " " + text[m.end():]
        return m.group(0).strip(), re.sub(r"\s+", " ", rest).strip(" ,;")
    return "", text


def _when_text(when: str) -> str:
    w = _lower_first(tidy(when))
    w = re.sub(r"^(?i:eod)$", "the end of the day", w)
    return w


def _with_when(when: str, default: str = "") -> str:
    w = _when_text(when) if when else default
    if not w:
        return ""
    if re.match(rf"(?i)({DAY}|{DATEWORD})$", w) and not re.match(r"(?i)(today|tonight|tomorrow|this|next|coming)", w):
        w = "by " + w
    return " " + w


# ---------------------------------------------------------------------------
# Who to send it to

SEND_TO = re.compile(r"[,.;]?\s*(?:and\s+|then\s+)?(?:please\s+)?(?:send|mail|email|e-mail|forward|address|write)\s+"
                     r"(?:(?:it|this|that|the (?:mail|email|message))\s+)?(?:to|for)\s*:?\s+(?P<who>[^,.;]+?(?:\s*(?:,|and|&)\s*[^,.;]+?)*)\s*\.?$",
                     re.I)
TO_LABEL = re.compile(r"(?:^|[,.;]\s*)to\s*:\s*(?P<who>[^.;]+?)\s*(?=$|[.;]|\bcc\b)", re.I)
CC = re.compile(r"[,.;]?\s*(?:and\s+)?(?:(?:cc|c\.c\.?)(?:\s+to)?\s*:?\s+(?P<who>[^.;]+?)|(?:mark\s+)?(?:a\s+)?copy\s+to\s+(?P<who2>[^.;]+?)|"
                r"keep\s+(?P<who3>[^.;]+?)\s+in\s+(?:cc|copy|the loop))\s*\.?$", re.I)
LEAD = re.compile(
    r"^\s*(?:please\s+|kindly\s+|pls\s+)?(?P<verb>email|e-mail|mail|message|write\s+(?:an?\s+)?(?:e-?mail\s+|mail\s+|letter\s+)?to|"
    r"send\s+(?:an?\s+)?(?:e-?mail|mail|message|note|letter)\s+to|tell|ask|inform|notify|remind|request|instruct|direct|"
    r"advise|let|warn|thank|congratulate|invite|update|urge)\s+"
    r"(?P<who>(?:(?!(?:to|that|about|regarding|re|for|know|on|of|if|whether|why|when|what|how|we|i)\b)[\w.@'&-]+\s*?){1,6}?)\s*"
    r"(?P<link>,|:|\bto\b|\bthat\b|\babout\b|\bregarding\b|\bre\b|\bfor\b|\bknow(?:\s+that)?\b|\bon\b|\bof\b|\bif\b|\bwhether\b|\bwhy\b|\bwhen\b|\bwhat\b|\bhow\b|$)\s*"
    r"(?P<rest>.*)$",
    re.I,
)
LEAD_NOT_A_PERSON = re.compile(r"^(?:the|a|an|for|approval|leave|permission|salary|salaries|payment|meeting|report|it|this|me|us)\b", re.I)


def _split_people(who: str) -> list[str]:
    who = re.sub(r"^(?:mr\.?|mrs\.?|ms\.?|sir|madam|dr\.?|engr\.?)\s+", "", who.strip(), flags=re.I)
    parts = re.split(r"\s*(?:,|;|\band\b|&|\+)\s*", who, flags=re.I)
    out = []
    for p in parts:
        p = re.sub(r"^(?:to|the|mr\.?|mrs\.?|ms\.?|sir|madam)\s+", "", p.strip(" .:"), flags=re.I).strip()
        if p and p.lower() not in ("me", "him", "her", "them", "it", "this"):
            out.append(p)
    return out


def parse(note: str) -> dict:
    """{to: [phrase], cc: [phrase], verb, link, action}"""
    text = re.sub(r"\s+", " ", (note or "").strip())
    addrs: list[str] = []

    def hide(m):
        addrs.append(m.group(0))
        return f"ADDR{len(addrs) - 1}Z"

    text = re.sub(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+", hide, text)
    to, cc = [], []
    # Trailing "..., send to X" / "cc Y" (in either order, repeated).
    for _ in range(4):
        m = CC.search(text)
        if m and m.start() > 0:
            cc += _split_people(m.group("who") or m.group("who2") or m.group("who3"))
            text = text[: m.start()].strip(" ,;")
            continue
        m = SEND_TO.search(text)
        if m and m.start() > 0:
            to += _split_people(m.group("who"))
            text = text[: m.start()].strip(" ,;")
            continue
        break
    # "issue a warning to kamran driver for ..." -> goes to that person.
    m = re.match(r"^(?:please\s+)?(?:issue|give|send)\s+(?:an?\s+)?(?:written\s+|formal\s+|final\s+)?(?:warning|explanation(?:\s+letter)?|show\s+cause(?:\s+notice)?)(?:\s+letter)?\s+to\s+(.+?)\s+(for|regarding|about|on)\s+(.+)$", text, re.I)
    if m:
        to += _split_people(m.group(1))
        kind = "warning" if "warning" in text.lower() else "explain"
        text = f"{kind} {m.group(2)} {m.group(3)}"
    m = TO_LABEL.search(text)
    if m:
        to += _split_people(m.group("who"))
        text = (text[: m.start()] + text[m.end():]).strip(" ,;")
    # Leading "tell X to ...", "ask X to ...", "inform X that ...", "email X: ..."
    verb = link = ""
    m = LEAD.match(text)
    if m and m.group("rest") and not LEAD_NOT_A_PERSON.match(m.group("who")):
        who_v = m.group("verb").lower().split()[0]
        if not (who_v == "request" and m.group("who").split()[0].lower() in COMMON):
            to += _split_people(m.group("who"))
            verb, link, text = who_v, (m.group("link") or "").lower().strip(), m.group("rest").strip()
            if verb == "let" and not link.startswith("know"):
                verb, link = "inform", link
            if link.startswith("know"):
                verb, link = "inform", "that"
    # Bare email addresses anywhere become recipients.
    for token in re.findall(r"ADDR\d+Z", text):
        if token not in to:
            to.append(token)
        text = re.sub(r"\s+", " ", text.replace(token, "")).strip(" ,;")
    text = re.sub(r"\s+(?:to|for|and)\s*$", "", text, flags=re.I)
    unhide = lambda x: re.sub(r"ADDR(\d+)Z", lambda m: addrs[int(m.group(1))], x)
    to, cc = [unhide(x) for x in to], [unhide(x) for x in cc]
    text = re.sub(r"^(?:please|kindly|pls|plz)\s+", "", text, flags=re.I).strip()
    return {"to": _dedupe(to), "cc": _dedupe(cc), "verb": verb, "link": link, "action": text}


def _dedupe(items: list[str]) -> list[str]:
    seen, out = set(), []
    for x in items:
        if x.lower() not in seen:
            seen.add(x.lower())
            out.append(x)
    return out


# ---------------------------------------------------------------------------
# Templates

CONFIRM = "Kindly confirm by return email once the necessary action has been taken."
HOPE = "I hope this email finds you well."
CLARIFY = "Should you require any clarification, please do not hesitate to contact me."


def _you(text: str) -> str:
    """'tell qasim to send his report' -> 'send your report' (instruction addressed to the reader)."""
    t = re.sub(r"\b(?:his|her|their)\b", "your", text, flags=re.I)
    t = re.sub(r"\b(?:himself|herself|themselves)\b", "yourself", t, flags=re.I)
    t = re.sub(r"\b(?:he|she|they) (?:is|are)\b", "you are", t, flags=re.I)
    t = re.sub(r"\b(?:he|she|they) (?:has|have)\b", "you have", t, flags=re.I)
    t = re.sub(r"\b(?:he|she|they) (?:was|were)\b", "you were", t, flags=re.I)
    t = re.sub(r"\b(?:he|she|they)\b", "you", t, flags=re.I)
    return t


def _salary(action: str) -> dict | None:
    m = re.search(r"\b(hold|stop|withhold|freeze|block|release|resume|unhold|un-hold|clear|deduct|cut|increase|raise|"
                  r"increment|revise|pay|process|disburse|transfer|issue)(?:s|ed|ing|d)?\b", action, re.I)
    if not m or not re.search(r"\b(salar(?:y|ies)|wages?|dues|increment)\b|\bpayroll\b", action[m.start():], re.I):
        return None
    if re.match(r"(?i)^(?:send|share|submit|prepare|provide|forward)\b", action):
        return None
    verb = m.group(1).lower()
    kind = ("hold" if verb in ("hold", "stop", "withhold", "freeze", "block") else
            "release" if verb in ("release", "resume", "unhold", "un-hold", "clear", "pay", "process", "disburse", "transfer", "issue") else
            "deduct" if verb in ("deduct", "cut") else "increase")
    rest = action
    reason, rest = _take(REASON, rest, 1)
    amount, rest = _take(AMOUNT, rest)
    if not reason and kind in ("deduct", "hold"):
        # "deduct 3 days salary of imran guard for late coming": a trailing "for <not a date>" is the reason.
        mfor = re.search(r"\s+for\s+(?!(?:the\s+)?(?:current|this|next|last|previous|month|week|\d))((?:(?!\bfor\b).)+)$", rest, re.I)
        if mfor and not WHEN.fullmatch(mfor.group(0).strip()) and re.search(r"\b(?:of|for)\b.*\bfor\b", rest, re.I):
            reason, rest = mfor.group(1), rest[: mfor.start()]
    whens = []
    while True:
        w, rest2 = _take_when(rest)
        if not w:
            break
        whens.append(w)
        rest = rest2
    m2 = re.search(r"\b(?:of|for|to|from)\s+(?!(?:the\s+)?(?:month|week|salary|salaries|pay)\b)(.+)$", rest, re.I)
    who_phrase = m2.group(1) if m2 else re.sub(
        r"\b(?:hold|stop|withhold|freeze|block|release|resume|unhold|clear|deduct|cut|increase|raise|increment|revise|pay|process|disburse|transfer|issue)\w*\b"
        r"|\b(?:the|salar(?:y|ies)|pay|wages?|payroll|dues|increment|please|kindly|amount|by|of)\b", " ", rest, flags=re.I)
    who_phrase = re.sub(r"\b(?:salar(?:y|ies)|wages?|pay)\b", " ", who_phrase, flags=re.I)
    people = _people_in(re.sub(r"\s+", " ", who_phrase).strip(" ,.;"))
    names_s = _list_text([person_text(p, "subject") for p in people]) or "Staff"
    many = len(people) > 1
    sal = "salaries" if many or not people else "salary"
    if people and not many:
        whose = f"the {sal} of {person_text(people[0])}" + ("," if people[0]["role"] and people[0]["name"] else "")
    elif many:
        whose = f"the {sal} of the following staff members"
    else:
        whose = "the salaries concerned"
    period = " ".join(_when_text(w) for w in whens)
    reason_s = f", due to {_strip_end(tidy(reason))[:1].lower() + _strip_end(tidy(reason))[1:]}" if reason else ""
    listing = ("\n\n" + "\n".join(f"- {person_text(p)}" for p in people) + "\n") if many else ""

    if kind == "hold":
        subject = f"Salary Hold – {names_s}"
        when = period or "with immediate effect until further notice"
        first = f"I am writing to instruct you to place {whose} on hold {when}{reason_s}" + (":" if many else ".")
        emp = "employees" if many else "employee"
        paras = [first + listing,
                 f"Accordingly, no salary payment should be released to the above-mentioned {emp} until further written "
                 "instructions are received from the undersigned. Please ensure that the payroll records are updated to "
                 "reflect this instruction.",
                 CONFIRM + " " + CLARIFY]
    elif kind == "release":
        subject = f"Salary Release – {names_s}"
        when = f" {period}" if period else ""
        paras = [f"I am writing to authorise the release of {whose}{when}{reason_s}" + (":" + listing if many else "."),
                 "Please arrange for the payment to be processed at the earliest and ensure that the payroll records are "
                 "updated accordingly.",
                 "Kindly confirm by return email once the payment has been disbursed. " + CLARIFY]
    elif kind == "deduct":
        subject = f"Salary Deduction – {names_s}"
        when = f" {period}" if period else ""
        if amount and re.search(r"(?i)salary|pay|wages", amount):
            amt = re.sub(r"(?i)(\d+)\s+days?(?:'s)?\s+",
                         lambda x: f"{x.group(1)} day's " if x.group(1) == "1" else f"{x.group(1)} days' ", tidy(amount))
            target = whose.replace(f"the {sal} of ", "", 1).rstrip(",") if people and not many else whose
            paras = [f"I am writing to instruct you to deduct {_lower_first(amt)} from {target}{when}{reason_s}." + listing,
                     "Please ensure that this deduction is reflected in the upcoming payroll and that the employee concerned "
                     "is duly informed.",
                     CONFIRM + " " + CLARIFY]
        else:
            amt = f" {tidy(amount)}" if amount else " the applicable amount"
            paras = [f"I am writing to instruct you to deduct{amt} from {whose}{when}{reason_s}." + listing,
                     "Please ensure that this deduction is reflected in the upcoming payroll and that the employee concerned "
                     "is duly informed.",
                     CONFIRM + " " + CLARIFY]
    else:
        subject = f"Salary Revision – {names_s}"
        amt = f" by {tidy(amount)}" if amount else ""
        when = f" {_with_when(period).strip()}" if period else ""
        paras = [f"I am writing to inform you that {whose} is to be revised{amt}{when}{reason_s}." + listing,
                 "Please update the payroll records accordingly and ensure that the revised amount is reflected in the "
                 "next salary disbursement.",
                 CONFIRM + " " + CLARIFY]
    return {"intent": "salary", "subject": subject, "paragraphs": paras}


def _meeting(action: str) -> dict | None:
    if not re.search(r"\b(meeting|meet|call|session|briefing|discussion)\b", action, re.I):
        return None
    if not re.search(r"\b(schedule|arrange|set up|setup|organi[sz]e|call|book|fix|plan|hold|have|meet|invite|conduct)\b|^meeting", action, re.I):
        return None
    rest = action
    topic, rest = _take(re.compile(r"\b(?:about|regarding|re|on the topic of|to discuss|for discussing|to review|to talk about|concerning)\s+(.+?)(?=\s*(?:$|[,;.]|\b(?:on|at|by|tomorrow|today|with)\b))", re.I), rest, 1)
    when_parts = []
    while True:
        w, rest2 = _take_when(rest)
        if not w:
            break
        when_parts.append(_when_text(w))
        rest = rest2
    place, rest = _take(re.compile(r"\b(?:in|at)\s+(?:the\s+)?((?:conference|meeting|board|my|gm'?s?|ceo'?s?)\s+(?:room|office|hall)|office|lobby|restaurant|online|zoom|teams)\b", re.I), rest, 1)
    with_who, rest = _take(re.compile(r"\bwith\s+(.+?)(?=\s*(?:$|[,;.]|\b(?:on|at|by|about|regarding|to discuss|tomorrow|today|in)\b))", re.I), rest, 1)
    when = " ".join(when_parts)
    when = re.sub(r"(?i)^(?:by|before)\s+", "", when)
    if when and not re.match(r"(?i)(on|at|today|tomorrow|this|next|coming|tonight)\b", when):
        when = ("on " if re.match(rf"(?i){DAY}|\d", when) else "") + when
    topic_s = _title_subject(re.sub(r"(?i)^the\s+", "", tidy(topic))) if topic else ""
    subject = "Meeting" + (f": {topic_s}" if topic else "") + (f" – {tidy(when)[:1].upper() + tidy(when)[1:]}" if when else "")
    s = "I would like to schedule a meeting"
    if with_who:
        s += f" with {_lower_first(tidy(with_who))}"
    if when:
        s += f" {_lower_first(tidy(when))}"
    if place:
        s += f" in the {tidy(place).lower()}" if not re.match(r"(?i)online|zoom|teams", place) else f" ({tidy(place)})"
    if topic:
        s += f" to discuss {_lower_first(_strip_end(tidy(topic)))}"
    s += ", and I would request your attendance."
    paras = [s,
             "Your presence and input will be highly valued. I would appreciate it if you could come prepared with any "
             "relevant updates or information pertaining to the agenda.",
             "Kindly confirm your availability at your earliest convenience. Should the proposed timing not be suitable, "
             "please let me know so that an alternative arrangement can be made."]
    return {"intent": "meeting", "subject": subject, "paragraphs": paras}


DOC_WORDS = (r"report|reports|statement|statements|list|details|file|files|sheet|summary|invoice|invoices|quotation|"
             r"quotations|data|record|records|plan|update|attendance|inventory|stock|documents?|bills?|receipts?|"
             r"proposal|budget|figures|numbers|minutes|schedule|roster|analysis|reconciliation|ledger|cv|resume|"
             r"payslips?|vouchers?|requisition|forecast|feedback|photos?|pictures?|checklist|sop")


def _request_doc(action: str) -> dict | None:
    m = re.match(rf"^(?:(?:please|kindly)\s+)?(send|share|submit|provide|prepare|forward|email|mail|give|bring|compile|finali[sz]e|update|complete)\s+(?:me\s+|us\s+)?(.*\b(?:{DOC_WORDS})\b.*)$", action, re.I)
    if not m:
        return None
    verb, obj = m.group(1).lower(), m.group(2)
    reason, obj = _take(REASON, obj, 1)
    when, obj = _take_when(obj)
    obj = _strip_end(tidy(obj))
    if verb in ("email", "mail", "give", "forward"):
        verb = "share"
    objl = _lower_first(obj)
    if not re.match(r"(?i)(the|a|an|my|our|your|all|this|these|those|\d)\b", objl):
        objl = "the " + objl
    subject = "Request: " + _title_subject(re.sub(r"(?i)^(the|a|an|your|our|my)\s+", "", obj))
    s = f"I would be grateful if you could {verb} {objl}{_with_when(when)}"
    if reason:
        s += f", as {_lower_first(_strip_end(tidy(reason)))}"
    short = re.sub(r"(?i)^(?:the|a|an|your|our|my)\s+", "", objl)
    paras = [HOPE + " " + s + ".",
             f"Kindly ensure that the {short} is complete and accurate, and that any relevant supporting details are included.",
             "Should you have any questions or require any further information from my side, please feel free to contact me."]
    return {"intent": "request", "subject": subject, "paragraphs": paras}


def _reminder(action: str, verb: str) -> dict | None:
    if verb != "remind" and not re.match(r"^(?:a\s+)?(?:gentle\s+|friendly\s+)?remind(?:er)?\b", action, re.I):
        return None
    topic = re.sub(r"^(?:a\s+)?(?:gentle\s+|friendly\s+)?remind(?:er)?(?:\s+(?:about|of|regarding|that|to))?\s*", "", action, flags=re.I)
    when, topic = _take_when(topic)
    topic = _you(_strip_end(tidy(topic)))
    if re.match(r"(?i)(send|submit|share|complete|finish|pay|prepare|update|bring|call|check|fix|arrange|clear|return)\b", topic):
        body = f"This is a gentle reminder to {_lower_first(topic)}{_with_when(when)}."
        subject = "Reminder: " + _title_subject(re.sub(r"(?i)^(?:send|submit|share|complete|finish|prepare|update)\s+(?:the\s+)?", "", topic))
    else:
        body = f"This is a gentle reminder regarding {_lower_first(topic)}{_with_when(when)}."
        subject = "Reminder: " + _title_subject(re.sub(r"(?i)^the\s+", "", topic))
    return {"intent": "reminder", "subject": subject,
            "paragraphs": ["I hope you are doing well. " + body,
                           "As this matter is time-sensitive, I would appreciate it if you could treat it as a priority.",
                           "If you have already attended to this, please disregard this reminder. Otherwise, kindly let me "
                           "know if there is anything preventing its completion."]}


def _approval(action: str) -> dict | None:
    m = re.match(r"^(?:(?:please|kindly)\s+)?(?:(?:i\s+)?(?:have\s+)?)(approve[ds]?|sanction(?:ed)?|grant(?:ed)?|accept(?:ed)?|reject(?:ed)?|decline[ds]?|disapprove[ds]?|not approved?|deny|denied)\s+(.+)$", action, re.I) \
        or re.match(r"^(.+?)\s+(?:is|are|has been|have been|stands?)\s+(approved|sanctioned|granted|accepted|rejected|declined|not approved|denied)\b(.*)$", action, re.I)
    if not m:
        return None
    if m.re.pattern.startswith("^(?:(?:please"):
        word, thing = m.group(1).lower(), m.group(2)
    else:
        thing, word = m.group(1) + " " + m.group(3), m.group(2).lower()
    positive = not re.match(r"(reject|declin|disapprov|not|deny|denied)", word)
    reason, thing = _take(REASON, thing, 1)
    when, thing = _take_when(thing)
    thing = _strip_end(tidy(thing))
    thing_l = _lower_first(thing)
    if not re.match(r"(?i)(the|a|an|your|our|his|her|their|this|these|\d)\b", thing_l):
        thing_l = "the " + thing_l
    thing_l = _you(thing_l)
    subject = ("Approved: " if positive else "Not Approved: ") + _title_subject(re.sub(r"(?i)^(the|a|an|your|his|her|their)\s+", "", thing))
    if positive:
        s = f"I am pleased to inform you that {thing_l} has been approved{_with_when(when)}."
        paras = [s, "Please proceed accordingly and ensure that all relevant records are updated.",
                 "Should you require any further information, please feel free to contact me."]
    else:
        s = f"After careful consideration, I regret to inform you that {thing_l} has not been approved at this time"
        s += f", as {_lower_first(_strip_end(tidy(reason)))}." if reason else "."
        paras = [s, "This decision may be reviewed should circumstances change in the future.",
                 "Please feel free to discuss the matter with me should you require any further clarification."]
    return {"intent": "approval", "subject": subject, "paragraphs": paras}


def _explanation(action: str) -> dict | None:
    m = re.match(r"^(?:(?:please|kindly)\s+)?(?:explain|give\s+(?:an?\s+)?explanation|provide\s+(?:an?\s+)?explanation|submit\s+(?:an?\s+)?explanation|"
                 r"show\s+cause|(?:issue\s+)?(?:a\s+)?(?:written\s+)?warning(?:\s+letter)?|warn)\b(?:\s+(?:for|about|regarding|on|to|of)\b)?\s*(.*)$", action, re.I)
    if not m:
        return None
    warning = bool(re.match(r"(?i)^(?:(?:please|kindly)\s+)?(?:issue|(?:a\s+)?(?:written\s+)?warning|warn)", action))
    issue = m.group(1)
    when, issue = _take_when(issue)
    issue = _you(_strip_end(tidy(issue)))
    if warning:
        subject = "Warning" + (f": {_title_subject(issue)}" if issue else "")
        paras = [f"This email serves as a formal warning regarding {_lower_first(issue) or 'the matter discussed'}.",
                 "Such conduct is not in line with the standards and policies of the organisation and cannot be accepted.",
                 "You are hereby advised to ensure that this does not recur. Please note that any repetition may result in "
                 "further disciplinary action, in accordance with company policy.",
                 "Kindly acknowledge receipt of this email."]
    else:
        subject = "Explanation Required" + (f": {_title_subject(issue)}" if issue else "")
        why = (f" of {_lower_first(issue)}" if re.match(r"(?i)(why|how|what)\b", issue) else f" regarding {_lower_first(issue)}") if issue else ""
        paras = [f"You are hereby requested to submit a written explanation{why}{_with_when(when, ' within 24 hours')}.",
                 "Your explanation should include all relevant facts and circumstances. Please note that your response "
                 "will be reviewed before any further action is taken.",
                 "Kindly treat this matter with due seriousness."]
    return {"intent": "explanation", "subject": subject, "paragraphs": paras}


def _thanks(action: str, verb: str) -> dict | None:
    if verb not in ("thank", "congratulate") and not re.match(r"^(?:thank|thanks|appreciate|congratulat)", action, re.I):
        return None
    congr = verb == "congratulate" or bool(re.match(r"(?i)^congratulat", action))
    thing = re.sub(r"^(?:thank(?:s)?(?:\s+you)?|appreciate|congratulat\w*)\s*(?:you\s+)?(?:for|on)?\s*", "", action, flags=re.I)
    thing = _you(_strip_end(tidy(thing)))
    if congr:
        return {"intent": "thanks", "subject": "Congratulations" + (f" on {_title_subject(thing)}" if thing else ""),
                "paragraphs": [f"Please accept my heartfelt congratulations on {_lower_first(thing) or 'your achievement'}.",
                               "This achievement is a testament to your dedication and hard work, and it is truly well deserved.",
                               "I wish you continued success in all your future endeavours."]}
    thing_s = _title_subject(re.sub(r"(?i)^(?:the|your)\s+", "", thing)) if thing else ""
    return {"intent": "thanks", "subject": "Thank You" + (f" – {thing_s}" if thing else ""),
            "paragraphs": [f"I would like to take this opportunity to express my sincere appreciation for {_lower_first(thing) or 'your support'}.",
                           "Your dedication, professionalism and attention to detail are truly commendable and greatly valued.",
                           "Thank you once again for your continued hard work."]}


def _follow_up(action: str) -> dict | None:
    m = re.match(r"^(?:(?:please|kindly)\s+)?(?:follow[\s-]?up\s+(?:on|about|regarding|with)?|(?:get|give|share|send)\s+(?:me\s+)?(?:an?\s+)?(?:status|update|progress)\s+(?:on|of|about|regarding)|status\s+(?:of|on)|update\s+(?:on|about|regarding)|what is the status of|where are we (?:on|with))\s+(.+)$", action, re.I)
    if not m:
        return None
    topic = m.group(1)
    when, topic = _take_when(topic)
    topic = _strip_end(tidy(topic))
    return {"intent": "follow-up", "subject": "Follow-up: " + _title_subject(re.sub(r"(?i)^the\s+", "", topic)),
            "paragraphs": [f"{HOPE} I am writing to follow up on {_lower_first(topic)}.",
                           f"I would be grateful if you could provide an update on the current status{_with_when(when)}, "
                           "including any issues or challenges that may require attention.",
                           "Thank you for your prompt attention to this matter."]}


QUESTION = re.compile(r"^(?:what|when|why|how|where|who|which|is|are|was|were|can|could|would|will|do|does|did|has|have|should)\b", re.I)
IMPERATIVE = re.compile(r"^(?:make|ensure|check|fix|repair|arrange|organi[sz]e|clean|stop|start|close|open|order|buy|purchase|"
                        r"collect|deliver|bring|take|call|contact|book|cancel|confirm|verify|review|update|complete|finish|"
                        r"prepare|send|share|submit|provide|keep|maintain|hand over|handover|return|pay|clear|move|shift|"
                        r"remove|replace|install|implement|follow|inform|visit|attend|join|report|coordinate|resolve|settle|"
                        r"investigate|look into|handle|process|issue|transfer|hire|recruit|train|assign|allocate|"
                        r"lock|secure|print|scan|file|record|note|count|audit|reconcile|submit|get|do|give|put|set|let|"
                        r"avoid|don't|do not|never|always|stay|be|come|go|use|apply|approve|plan|schedule|reduce|increase)\b", re.I)


def _general(action: str, verb: str, link: str) -> dict:
    a = _strip_end(tidy(action))
    if verb in ("tell", "ask", "instruct", "direct", "request", "urge", "advise") and link == "to" or (
            not verb and IMPERATIVE.match(a)):
        a = _you(a) if verb else a
        a2 = re.sub(r"(?i)^(?:please|kindly)\s+", "", a)
        body = f"I am writing to request that you {_lower_first(a2)}."
        subject = _subject(a2)
        return {"intent": "instruction", "subject": subject,
                "paragraphs": [body, "Kindly ensure that this is given due priority and completed in a timely manner.",
                               CONFIRM + " " + CLARIFY]}
    if QUESTION.match(a) or action.strip().endswith("?") or link in ("if", "whether", "why", "when", "what", "how"):
        q = a
        if link in ("if", "whether", "why", "when", "what", "how"):
            q = f"{link} {_you(a)}"
            body = f"Could you please let me know {_lower_first(q)}?"
        else:
            body = sentence(q).rstrip(".") + ("" if q.endswith("?") else "?")
        return {"intent": "question", "subject": _subject(a, query=True),
                "paragraphs": [HOPE + " " + body, "I look forward to your response at your earliest convenience."]}
    if link in ("about", "regarding", "re", "on", "of", "for"):
        topic = _lower_first(a)
        return {"intent": "inform", "subject": _subject(a),
                "paragraphs": [f"{HOPE} I am writing to you regarding {topic}.",
                               "I would appreciate the opportunity to discuss this matter with you at your earliest convenience.",
                               "Please let me know a suitable time, or feel free to contact me should you require any further details."]}
    # A statement: "inform X that ...", or plain text.
    stmt = _lower_first(a)
    if verb in ("inform", "notify", "tell", "update", "warn") or link == "that" or re.match(r"(?i)^that\b", a):
        stmt = re.sub(r"(?i)^that\s+", "", stmt)
        body = f"I would like to inform you that {stmt}."
    else:
        return _freeform(a)
    return {"intent": "inform", "subject": _subject(re.sub(r"(?i)^that\s+", "", a)),
            "paragraphs": [body, "Please take note of the above and plan accordingly.",
                           "Should you have any questions, please do not hesitate to contact me."]}


SMALL_WORDS = {"a", "an", "the", "and", "or", "of", "for", "to", "in", "on", "at", "by", "with", "from", "as"}


def _subject(text: str, query: bool = False) -> str:
    import subjects  # local import: subjects imports this module
    sub = subjects.make_subject(text)
    if query and not re.search(r"(?i)clarification|query|request", sub):
        sub = "Query – " + sub
    return sub


def _title_subject(text: str, limit: int = 70) -> str:
    t = re.sub(r"\s+", " ", _strip_end(text or "")).strip()
    if len(t) > limit:
        t = t[:limit].rsplit(" ", 1)[0]
    words = t.split(" ")
    out = []
    for i, w in enumerate(words):
        if any(c.isupper() for c in w[1:]) or w.isupper() and len(w) > 1:
            out.append(w)
        elif i and w.lower() in SMALL_WORDS:
            out.append(w.lower())
        else:
            out.append(w[:1].upper() + w[1:])
    return " ".join(out)


# ---------------------------------------------------------------------------


TEAMS = {"accounts", "account", "finance", "hr", "admin", "administration", "sales", "purchase", "purchasing",
         "procurement", "store", "stores", "housekeeping", "kitchen", "it", "maintenance", "security", "operations",
         "marketing", "reception", "front office", "f&b", "management", "audit", "payroll", "info", "office"}


def greet_name(phrase: str, contact_name: str = "") -> str:
    """How to address one recipient in 'Dear ...,'."""
    ph = (phrase or "").strip().lower()
    if re.search(r"\b(all|everyone|everybody|staff|team|heads|members|colleagues)\b", ph):
        return "All"
    if ph in TEAMS:
        return _title_role(ph) + " Team"
    if ROLE.fullmatch(ph):
        return _title_role(ph)
    name = (contact_name or "").strip().strip('"')
    if name and "@" not in name:
        return name
    pp = person(phrase or "")
    if pp["name"] and "@" not in pp["name"]:
        return pp["name"]
    if "@" in ph or not ph:
        local = (name or ph).split("@")[0]
        return (_title_role(local) + " Team") if local.lower() in TEAMS else _title_name(re.sub(r"[._-]+", " ", local))
    return _title_name(phrase)


def greeting(names: list[str]) -> str:
    names = [n for n in names if n]
    if "All" in names:
        return "Dear All,"
    if not names:
        return "Dear Sir/Madam,"
    if len(names) == 1:
        return f"Dear {names[0]},"
    if len(names) == 2:
        return f"Dear {names[0]} and {names[1]},"
    return "Dear All,"


FORMAL = [
    (r"\bcan't\b", "cannot"), (r"\bwon't\b", "will not"), (r"\bdon't\b", "do not"), (r"\bdoesn't\b", "does not"),
    (r"\bdidn't\b", "did not"), (r"\bisn't\b", "is not"), (r"\baren't\b", "are not"), (r"\bwasn't\b", "was not"),
    (r"\bweren't\b", "were not"), (r"\bhaven't\b", "have not"), (r"\bhasn't\b", "has not"), (r"\bshouldn't\b", "should not"),
    (r"\bcouldn't\b", "could not"), (r"\bwouldn't\b", "would not"), (r"\bI'm\b", "I am"), (r"\bI've\b", "I have"),
    (r"\bI'll\b", "I will"), (r"\bI'd\b", "I would"), (r"\bwe're\b", "we are"), (r"\bwe'll\b", "we will"),
    (r"\bwe've\b", "we have"), (r"\byou're\b", "you are"), (r"\byou'll\b", "you will"), (r"\bthey're\b", "they are"),
    (r"\bit's\b", "it is"), (r"\bthat's\b", "that is"), (r"\bthere's\b", "there is"), (r"\blet's\b", "let us"),
    (r"\bgonna\b", "going to"), (r"\bwanna\b", "want to"), (r"\bgotta\b", "have to"),
    (r"\bI want to\b", "I would like to"), (r"\bI want (?=(?:the|a|an|all|your|this|these)\b)", "I would like to request "),
    (r"\bI want\b", "I would like"), (r",\s+there (is|are)\b", r", as there \1"), (r"\bwe want to\b", "we would like to"),
    (r"\bwe want\b", "we would like"), (r"\bI need you to\b", "I would request you to"), (r"\bI need\b", "I require"),
    (r"\bwe need\b", "we require"), (r"\bas soon as possible\b", "at the earliest"), (r"\bget back to me\b", "respond"),
    (r"\bsend me\b", "share with me"), (r"\btell me\b", "inform me"), (r"\blet me know\b", "kindly let me know"),
    (r"\bcan you\b", "could you kindly"), (r"\bthanks a lot\b", "thank you very much"), (r"\bthanks\b", "thank you"),
    (r"\bsorry\b", "I apologise"), (r"\bfix\b", "resolve"), (r"\bfixed\b", "resolved"), (r"\bbuy\b", "purchase"),
    (r"\bbought\b", "purchased"), (r"\ba lot of\b", "a considerable number of"), (r"\blots of\b", "a considerable number of"),
    (r"\bstuff\b", "items"), (r"\bbig\b", "significant"),
    (r"\bget (it|this|them|these|the \w+) (fixed|repaired|resolved|sorted)\b", r"have \1 resolved"),
    (r"\bget (it|this|them|these|the \w+) (done|completed|finished)\b", r"have \1 completed"),
    (r"\bits (done|ready|complete|completed|working|fixed|resolved|finished|over|available)\b", r"it is \1"),
    (r"\bthere (?:is|are) (?:a )?lots? of\b", "there are numerous"), (r"\blots? of\b", "numerous"),
    (r"\b(is|are) not (\w+ing) since\b", lambda m: ("has" if m.group(1).lower() == "is" else "have") + f" not been {m.group(2)} since"),
    (r"\bI want (?=(?:the|a|an|all|your|this|these)\b)", "I would like to request "),
    (r"\bwhen it is done\b", "once it has been completed"),
    (r"\bhelp\b(?=\s+(?:me|us)\b)", "assist"), (r"\bcheck\b(?=\s+(?:the|this|these|all|it)\b)", "review"),
    (r"\bstart\b(?=\s+(?:the|this|work|working)\b)", "commence"), (r"\bmake sure\b", "ensure"),
    (r"\bkindly kindly\b", "kindly"), (r"\bplease kindly\b", "kindly"), (r"\bkindly please\b", "kindly"),
    (r"\bvery very\b", "very"), (r"\breally\s+", ""), (r"\bjust\s+(?=[a-z])", ""), (r"\bbasically,?\s+", ""),
]
FILLER_SENTENCE = re.compile(r"^(?:ok(?:ay)?|(?:hi|hello|hey|dear|salam|assalam\w*|aoa|good (?:morning|afternoon|evening))\b[^.!?]{0,30}|"
                             r"regards.*|thanks?(?: you)?(?: so much| very much)?|thank you\.?|bye|best(?: regards)?.*|sincerely.*|"
                             r"(?:i )?hope (?:you are|you're|u r|this (?:e-?mail|message) finds you) (?:doing )?(?:well|fine|good)|how are you|"
                             r"should you (?:have|require) any (?:questions|clarification|further).*|"
                             r"(?:please )?(?:feel free|do not hesitate) to contact me.*)[.!,]?$", re.I)


def formalize(text: str) -> str:
    t = text
    for rx, rep in FORMAL:
        def sub(m, r=rep):
            out = r(m) if callable(r) else m.expand(r)
            return (out[:1].upper() + out[1:]) if m.group(0)[:1].isupper() and out[:1].islower() else out
        t = re.sub(rx, sub, t, flags=re.I)
    return re.sub(r"[ \t]{2,}", " ", t)


def _split_sentences(text: str) -> list[str]:
    text = re.sub(r"(?i),\s+(?=(?:please|pls|plz|kindly)\b)", ". ", text.strip())
    parts = re.split(r"(?<=[.!?])\s+|\n+", text)
    return [p.strip(" -*•\t") for p in parts if p and p.strip(" -*•\t")]


def _polish_sentence(s: str) -> str:
    s = formalize(tidy(s))
    m = re.match(r"(?i)^(also|and|then|plus)\s+(.*)$", s)
    lead = ""
    if m:
        lead, s = "Additionally, ", m.group(2)
    if IMPERATIVE.match(s) and not re.match(r"(?i)(please|kindly)\b", s):
        s = "please " + _lower_first(s)
    elif re.match(r"(?i)(pls|plz)\b", s):
        s = re.sub(r"(?i)^(pls|plz)\b", "please", s)
    s = (lead + _lower_first(s)) if lead else s
    s2 = sentence(s)
    if QUESTION.match(s2) and not s2.endswith("?"):
        s2 = s2.rstrip(".") + "?"
    return s2


def _freeform(action: str) -> dict:
    """Several sentences typed as the email itself: polish each one and add a proper frame."""
    sentences = [s for s in _split_sentences(action) if not FILLER_SENTENCE.match(s.strip())]
    polished = [_polish_sentence(s) for s in sentences]
    if not polished:
        raise ValueError("empty")
    paras, cur = [], []
    for s in polished:
        cur.append(s)
        if len(cur) == 3:
            paras.append(" ".join(cur))
            cur = []
    if cur:
        paras.append(" ".join(cur))
    first = re.sub(r"(?i)^(?:additionally,\s+)?(?:I am writing to (?:inform you|let you know) that|please|kindly|"
                   r"I would like to request|I would like to|I require|we require)\s+", "", polished[0])
    _w, first = _take_when(first)
    first = re.split(r"[,;:]", first)[0]
    first = re.sub(r"(?i)^(?:the|a|an)\s+", "", _strip_end(first))
    subject = _subject(action)
    return {"intent": "message", "subject": subject,
            "paragraphs": [HOPE] + paras + ["Should you have any questions or require any further information, please do not hesitate to contact me."]}


def signature_block(sig: dict | str | None) -> str:
    if isinstance(sig, str) or sig is None:
        sig = {"name": sig or ""}
    lines = [str(sig.get(k) or "").strip() for k in ("name", "title", "company", "phone")]
    return "Best regards,\n\n" + "\n".join(x for x in lines if x)


def write(note: str, recipient_names: list[str] | None = None, my_name: dict | str = "", parsed: dict | None = None,
          polish: bool = False) -> dict:
    """{subject, body, intent}. recipient_names: display names of the people it goes to.
    my_name: your name, or a signature {name, title, company, phone}. polish: the note is the email text itself."""
    p = parsed or parse(note)
    action, verb, link = p["action"], p["verb"], p["link"]
    if not action.strip():
        raise ValueError("empty")
    # Several sentences: if the first is a known instruction, use its template and keep the rest as an extra
    # paragraph; otherwise polish the text as written instead of squeezing it into a template.
    extra = ""
    sents = [x for x in _split_sentences(action) if not FILLER_SENTENCE.match(x.strip())]
    if not sents:
        raise ValueError("empty")
    if len(sents) >= 2:
        if not _matches_template(sents[0], verb):
            return _finish(_freeform("\n".join(sents)), p, recipient_names, my_name)
        action = sents[0]
        extra = " ".join(sentence(formalize(tidy(x))) for x in sents[1:])
    elif polish:
        action = sents[0]
    # Tidy the instruction once (spelling, shorthand) before matching templates.
    action = re.sub(r"(?i)^(?:can|could|would|will)\s+you\s+(?:please\s+|kindly\s+)?", "", action).rstrip(" ?")
    action_t = tidy(action)
    if not re.match(r"(?i)^\s*(?:hold|stop|withhold|freeze|block|release|resume|deduct|cut|increase|revise|pay|process)\b", action_t):
        action_t = names_in(action_t)
    out = None
    if verb == "remind":
        out = _reminder(action_t, verb)
    if not out and verb in ("thank", "congratulate"):
        out = _thanks(action_t, verb)
    if not out:
        for fn in (_salary, _meeting, _approval, _explanation, _follow_up, _request_doc):
            out = fn(_you(action_t) if verb in ("tell", "ask", "instruct", "direct", "request") and fn in (_request_doc,) else action_t)
            if out:
                break
    if not out:
        out = _reminder(action_t, verb) or _thanks(action_t, verb) or _general(action_t, verb, link)
    if extra:
        out = {**out, "paragraphs": out["paragraphs"][:1] + [extra] + out["paragraphs"][1:]}
    return _finish(out, p, recipient_names, my_name)


def _matches_template(text: str, verb: str = "") -> bool:
    t = names_in(tidy(text))
    return any(fn(t) for fn in (_salary, _meeting, _approval, _explanation, _follow_up, _request_doc)) or bool(
        _reminder(t, verb) or _thanks(t, verb))


def _finish(out: dict, p: dict, recipient_names, my_name) -> dict:
    names = list(recipient_names or [])
    hello = greeting(names) if names else ("Dear All," if any(re.search(r"(?i)\b(all|team|staff|everyone|heads)\b", x) for x in p["to"]) else "Dear Sir/Madam,")
    paragraphs = [formalize(re.sub(r"[ \t]+", " ", x).strip()) for x in out["paragraphs"] if x and x.strip()]
    body = hello + "\n\n" + "\n\n".join(paragraphs) + "\n\n" + signature_block(my_name)
    subject = re.sub(r"\s+", " ", out["subject"]).strip(" –-:")[:120] or "Message"
    return {"subject": subject, "body": body.strip(), "intent": out["intent"]}
