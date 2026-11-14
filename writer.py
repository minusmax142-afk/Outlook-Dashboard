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
            "id": "ID", "vat": "VAT", "gst": "GST", "ntn": "NTN", "eobi": "EOBI", "pessi": "PESSI", "vip": "VIP",
            "vips": "VIPs"}
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
    # Month names inside a date ("20 nov", "nov 20", "may 2025") are capitalised.
    w = re.sub(rf"(?i)\b({MONTH})\b(?=\.?\s*\d)|(?<=\d )({MONTH})\b|(?<=\d(?:st|nd|rd|th) )({MONTH})\b|(?<=of )({MONTH})\b",
               lambda m: next(g for g in m.groups() if g).capitalize(), w)
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
    # One thought per line: a line break without punctuation ends a sentence ("hi qasim\nsend the report").
    text = re.sub(r"(?<![.!?,;:])[ \t]*\n+\s*", ". ", (note or "").strip())
    text = re.sub(r"\s+", " ", text)
    # "Hi Qasim. ..." -> Qasim is who it is for (when nobody else is named).
    greet = re.match(r"(?i)^(?:hi|hello|hey|dear|salam|salaam|assalam\w*(?:\s+o\s+alaikum)?|aoa)\s+((?!all\b|team\b|sir\b|madam\b|everyone\b)"
                     r"[a-z][\w'-]*(?:\s+(?!i\b|we\b|pls\b|please\b|kindly\b)[a-z][\w'-]*)?)\s*[,.!:-]\s*", text)
    greeted = greet.group(1) if greet else ""
    if greet:
        text = text[greet.end():]
    # "get the stock report from accounts by friday" -> "ask accounts to send the stock report by friday"
    text = re.sub(r"(?i)^(?:please\s+)?(?:get|collect|obtain|ask for|request)\s+(?:the\s+)?(.+?)\s+from\s+((?:the\s+)?[a-z][\w&-]*(?:\s+(?:team|department|dept))?)"
                  r"(\s+(?:by|before|until|till|today|tomorrow|on|within)\b.*)?$",
                  lambda m: f"ask {m.group(2)} to send the {m.group(1)}{m.group(3) or ''}", text)
    # "give warning to kamran" (no reason given)
    text = re.sub(r"(?i)^((?:please\s+)?(?:issue|give|send)\s+(?:an?\s+)?(?:written\s+|formal\s+|final\s+)?warning\s+to\s+(?:(?!\b(?:for|regarding|about|on|over)\b)[^.,;])+?)\s*$",
                  r"\1 for the matter discussed", text)
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
    if not to and greeted:
        to = [greeted]
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

# One short, fitting closing line per email: no stacked stock phrases.
CONFIRM = "Kindly confirm once this has been done."
QUESTIONS = "Please let me know if you have any questions."


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
    # "Ahmed Driver's October salary" -> "salary of Ahmed Driver for October"
    rest = action[: m.end()] + re.sub(
        rf"(?i)\b((?:[A-Za-z][\w-]*\s+){{0,3}}?[A-Za-z][\w-]*)'s\s+(?:({MONTH})\s+)?(salar(?:y|ies)|wages?|dues)\b",
        lambda x: f"the {x.group(3)} of {x.group(1)}" + (f" for {x.group(2)}" if x.group(2) else ""), action[m.end():])
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
        first = f"Please place {whose} on hold {when}{reason_s}" + (":" if many else ".")
        paras = [first + listing,
                 "No salary payment should be released until you receive further written instructions from me. "
                 "Please update the payroll records accordingly.",
                 CONFIRM]
    elif kind == "release":
        subject = f"Salary Release – {names_s}"
        when = f" {period}" if period else ""
        paras = [f"I hereby authorise the release of {whose}{when}{reason_s}" + (":" + listing if many else "."),
                 "Please have the payment processed at the earliest, update the payroll records, and confirm once it "
                 "has been disbursed."]
    elif kind == "deduct":
        subject = f"Salary Deduction – {names_s}"
        when = f" {period}" if period else ""
        if amount and re.search(r"(?i)salary|pay|wages", amount):
            amt = re.sub(r"(?i)(\d+)\s+days?(?:'s)?\s+",
                         lambda x: f"{x.group(1)} day's " if x.group(1) == "1" else f"{x.group(1)} days' ", tidy(amount))
            target = whose.replace(f"the {sal} of ", "", 1).rstrip(",") if people and not many else whose
            paras = [f"Please deduct {_lower_first(amt)} from {target}{when}{reason_s}." + listing,
                     "Kindly ensure the deduction is reflected in the upcoming payroll and that the employee concerned is "
                     "informed, and confirm once this has been done."]
        else:
            amt = f" {tidy(amount)}" if amount else " the applicable amount"
            paras = [f"Please deduct{amt} from {whose}{when}{reason_s}." + listing,
                     "Kindly ensure the deduction is reflected in the upcoming payroll and that the employee concerned is "
                     "informed, and confirm once this has been done."]
    else:
        subject = f"Salary Revision – {names_s}"
        amt = f" by {tidy(amount)}" if amount else ""
        when = f" {_with_when(period).strip()}" if period else ""
        paras = [f"Please note that {whose} is to be revised{amt}{when}{reason_s}." + listing,
                 "Kindly update the payroll records so that the revised amount is reflected in the next salary "
                 "disbursement, and confirm once this has been done."]
    return {"intent": "salary", "subject": subject, "paragraphs": paras}


def _meeting(action: str) -> dict | None:
    if not re.search(r"\b(meeting|meet|call|session|briefing|discussion)\b", action, re.I):
        return None
    # "call the plumber" / "call the technician" is an instruction, not a meeting.
    if not re.search(r"\b(meeting|meet|session|briefing|discussion)\b", action, re.I) and not re.search(
            r"\b(?:a|conference|video|zoom|teams|quick|short)\s+call\b|\bcall\s+with\b", action, re.I):
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
    s += ", and would appreciate your attendance. Please come prepared with any relevant updates."
    paras = [s,
             "Kindly confirm your availability, or let me know if another time would suit you better."]
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
    whens = []
    while True:
        w, obj2 = _take_when(obj)
        if not w:
            break
        whens.append(w)
        obj = obj2
    # "for oct" stays with the document ("sales figures for October"); deadlines go after it.
    for w in [x for x in whens if BARE_MONTH.fullmatch(re.sub(r"(?i)^(?:for|of)\s+", "", x))]:
        whens.remove(w)
        obj = _strip_end(obj) + " " + _when_text(w)
    when = " ".join(_when_text(x) for x in whens)
    obj = _strip_end(tidy(obj))
    obj = re.sub(rf"(?i)\b(for|of) ({MONTH})\b", lambda x: f"{x.group(1)} {x.group(2).capitalize()}", obj)
    if verb in ("email", "mail", "give", "forward"):
        verb = "share"
    objl = _lower_first(obj)
    if not re.match(r"(?i)(the|a|an|my|our|your|all|this|these|those|\d)\b", objl):
        objl = "the " + objl
    subject = "Request: " + _title_subject(short_title(re.sub(r"(?i)^(the|a|an|your|our|my)\s+", "", obj)))
    if when:
        subject += f" – {deadline_label(when)}"
    s = f"Could you please {verb} {objl}{_with_when(when)}"
    if reason:
        s += f", as {_lower_first(_strip_end(tidy(reason)))}"
    paras = [s + "? Kindly make sure everything is complete and accurate, with any supporting details included.",
             "Thank you in advance."]
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
            "paragraphs": [body + " As this is time-sensitive, I would appreciate your priority attention.",
                           "If this has already been taken care of, please disregard this note. Otherwise, do let me know "
                           "if anything is holding it up."]}


def _approval(action: str) -> dict | None:
    m = re.match(r"^(?:(?:please|kindly)\s+)?(?:(?:i\s+)?(?:have\s+)?)(approve[ds]?|sanction(?:ed)?|grant(?:ed)?|accept(?:ed)?|reject(?:ed)?|decline[ds]?|disapprove[ds]?|not approved?|deny|denied)\s+(.+)$", action, re.I) \
        or re.match(r"^(.+?)\s+(?:is|are|has been|have been|stands?)\s+(approved|sanctioned|granted|accepted|rejected|declined|not approved|denied)\b(.*)$", action, re.I)
    if not m:
        return None
    if m.re.pattern.startswith("^(?:(?:please"):
        word, thing = m.group(1).lower(), m.group(2)
    else:
        thing, word = m.group(1) + " " + m.group(3), m.group(2).lower()
    if re.match(r"(?i)(?:my|me|our|us)\b", thing.strip()):
        return None  # "approve my leave" asks the reader for approval; it is not a decision
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
        s = f"I am pleased to confirm that {thing_l} has been approved{_with_when(when)}."
        paras = [s + " Please proceed accordingly and update the relevant records."]
    else:
        s = f"After careful consideration, I regret to inform you that {thing_l} has not been approved at this time"
        s += f", as {_lower_first(_strip_end(tidy(reason)))}." if reason else "."
        paras = [s, "This may be reconsidered should circumstances change. Please feel free to speak with me if you "
                    "would like to discuss it further."]
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
        if re.match(r"(?i)the matter discussed$", issue):
            issue = ""
        subject = "Warning" + (f": {_title_subject(issue)}" if issue else "")
        paras = [f"This email serves as a formal warning regarding {_lower_first(issue) or 'the matter discussed'}.",
                 "Such conduct is not in line with the standards and policies of the organisation. You are advised to "
                 "ensure that it does not recur; any repetition may result in further disciplinary action in accordance "
                 "with company policy.",
                 "Kindly acknowledge receipt of this email."]
    else:
        subject = "Explanation Required" + (f": {_title_subject(issue)}" if issue else "")
        why = (f" of {_lower_first(issue)}" if re.match(r"(?i)(why|how|what)\b", issue) else f" regarding {_lower_first(issue)}") if issue else ""
        paras = [f"You are requested to submit a written explanation{why}{_with_when(when, ' within 24 hours')}, "
                 "including all relevant facts and circumstances.",
                 "Your response will be reviewed before any further action is taken, so kindly treat this matter with "
                 "due seriousness."]
    return {"intent": "explanation", "subject": subject, "paragraphs": paras}


def _thanks(action: str, verb: str) -> dict | None:
    if verb not in ("thank", "congratulate") and not re.match(r"^(?:thank|thanks|appreciate|congratulat)", action, re.I):
        return None
    congr = verb == "congratulate" or bool(re.match(r"(?i)^congratulat", action))
    thing = re.sub(r"^(?:thank(?:s)?(?:\s+you)?|appreciate|congratulat\w*)\s*(?:you\s+)?(?:for|on)?\s*", "", action, flags=re.I)
    thing = _you(_strip_end(tidy(thing)))
    if congr:
        return {"intent": "thanks", "subject": "Congratulations" + (f" on {_title_subject(thing)}" if thing else ""),
                "paragraphs": [f"Please accept my warmest congratulations on {_lower_first(thing) or 'your achievement'}. "
                               "It is a well-deserved recognition of your hard work and dedication.",
                               "Wishing you every success in the times ahead."]}
    thing_s = _title_subject(re.sub(r"(?i)^(?:the|your)\s+", "", thing)) if thing else ""
    return {"intent": "thanks", "subject": "Thank You" + (f" – {thing_s}" if thing else ""),
            "paragraphs": [f"I would like to sincerely thank you for {_lower_first(thing) or 'your support'}. "
                           "Your dedication and professionalism are truly appreciated and make a real difference.",
                           "Thank you once again."]}


def _follow_up(action: str) -> dict | None:
    m = re.match(r"^(?:(?:please|kindly)\s+)?(?:follow[\s-]?up\s+(?:on|about|regarding|with)?|(?:get|give|share|send)\s+(?:me\s+)?(?:an?\s+)?(?:status|update|progress)\s+(?:on|of|about|regarding)|status\s+(?:of|on)|update\s+(?:on|about|regarding)|what is the status of|where are we (?:on|with))\s+(.+)$", action, re.I)
    if not m:
        return None
    topic = m.group(1)
    when, topic = _take_when(topic)
    topic = _strip_end(tidy(topic))
    return {"intent": "follow-up", "subject": "Follow-up: " + _title_subject(re.sub(r"(?i)^the\s+", "", topic)),
            "paragraphs": [f"I am writing to follow up on {_lower_first(topic)}. Could you please share an update on the "
                           f"current status{_with_when(when)}, including anything that needs my attention?",
                           "Thank you."]}


UNWELL = re.compile(r"^(?:i\s+am|i'm|im|am)?\s*(?:sick|ill|unwell|not well|not feeling well|having (?:a )?(?:fever|flu|cold))$", re.I)


def _reason_text(reason: str) -> str:
    r = _strip_end(tidy(reason))
    if UNWELL.match(r):
        return "as I am unwell"
    r = re.sub(r"(?i)^i\s+(?:have|am having)\s+", "I have ", r)
    r = re.sub(r"(?i)\b(?:a\s+)?doctor(?:'s)?\s+appointment", "a doctor's appointment", r)
    if re.match(r"(?i)(?:car|bike|vehicle|son|daughter|mother|father|wife|husband|child|kid|brother|sister|family)\b", r):
        r = "my " + _lower_first(r)  # "car broke down" -> "as my car broke down"
    if re.match(r"(?i)^(?:I|my|we|our|there)\b", r):
        return "as " + _lower_first(r)
    return "due to " + _lower_first(re.sub(r"(?i)^(?:a|an)\s+", "a ", r))


LEAVE = re.compile(r"\b(?:leave|day off|days off|time off|off day|holiday|half day)\b", re.I)


def _leave(action: str) -> dict | None:
    """'need leave tomorrow because i am sick', 'i will be on leave from 20 nov to 25 nov'."""
    away = re.match(r"(?i)^(?:i\s+)?(?:will not|won't|wont|cannot|can't|shall not|would not|am not)\s+(?:be\s+able\s+to\s+)?"
                    r"(?:be\s+)?(?:come|coming|attend|attending|make it|join|available|in)\b(?:\s+(?:to\s+)?(?:the\s+)?(?:office|work|duty))?\s*(.*)$",
                    action.strip())
    if away:
        rest = away.group(1)
        reason, rest = _take(REASON, rest, 1)
        m = re.search(r"\s*,\s*((?:my|our|i|we|there)\b.+)$", rest, re.I)  # "..., my mother is in hospital"
        if m and not reason:
            reason, rest = m.group(1), rest[: m.start()]
        whens = []
        while True:
            w, rest2 = _take_when(rest)
            if not w:
                break
            whens.append(_when_text(w))
            rest = rest2
        when = " ".join(whens)
        if when and re.match(rf"(?i){DAY}$|\d", when):
            when = "on " + when
        reason_s = f", {_reason_text(reason)}" if reason else ""
        when_s = f" {when}" if when else ""
        subject = "Absence Notice" + (f" – {_title_subject(re.sub(r'^on ', '', when))}" if when else "")
        return {"intent": "leave", "subject": subject,
                "paragraphs": [f"Please note that I will not be able to come to the office{when_s}{reason_s}.",
                               "I can be reached by phone for anything urgent. Thank you for your understanding."]}
    late = re.match(r"(?i)^(?:i\s+)?(?:will|'ll|shall|might|may)\s+be\s+(?:a\s+(?:bit|little)\s+)?(?:late|delayed)\b\s*(.*)$", action.strip())
    if late:
        rest = late.group(1)
        reason, rest = _take(REASON, rest, 1)
        m = re.search(r"\s*,\s*(.+)$", rest)  # "..., car broke down"
        if m and not reason:
            reason, rest = m.group(1), rest[: m.start()]
        when, rest = _take_when(rest)
        when_s = f" {_when_text(when)}" if when else ""
        reason_s = f", {_reason_text(reason)}" if reason else ""
        return {"intent": "leave", "subject": "Late Arrival" + (f" – {_title_subject(_when_text(when))}" if when else ""),
                "paragraphs": [f"Please note that I will be arriving late{when_s}{reason_s}. I will be in as soon as I can "
                               "and will catch up on anything pending.",
                               "Thank you for your understanding."]}
    action = re.sub(r"(?i)^(?:approve|sanction|grant)\s+(?:me\s+)?(?:my\s+)?(?=(?:a\s+)?(?:leave|day off|half day)\b)", "request ", action.strip())
    # "i have a doctor appointment on friday so need half day" -> leave, with the first part as the reason
    because = re.match(r"(?i)^(.+?)[,]?\s+(?:so|and so|therefore|hence|that is why|thats why)\s+(?:i\s+)?(?:need|want|would like|"
                       r"request|have to take|will take|am taking)\s+(?:a\s+)?((?:leave|half day|day off|time off)\b.*)$", action)
    if because:
        cause, action = because.group(1), because.group(2)
        w, cause = _take_when(cause)
        action = f"{action} {w} because {cause}" if w else f"{action} because {cause}"
    # "I have the day off tomorrow", "tomorrow is my holiday", "I am off tomorrow" -> "I will be on leave tomorrow"
    action = re.sub(r"(?i)^(?:i\s+have|i've\s+got|i\s+have\s+got)\s+(?:the\s+|a\s+)?(?:day\s+off|leave|holiday|off)\b", "I will be on leave", action.strip())
    action = re.sub(rf"(?i)^((?:today|tomorrow|{DAY})(?:\s+and\s+(?:today|tomorrow|{DAY}))?)\s+(?:is|are|will be)\s+my\s+(?:holiday|leave|day off|off(?:\s+day)?)\b",
                    r"I will be on leave \1", action)
    action = re.sub(r"(?i)^i\s+(?:am|will be)\s+off\b", "I will be on leave", action)
    a = re.sub(r"(?i)^(?:i\s+)?(?:would like to|want to|wanna|need to|have to|want|need|require|request(?:ing)?|"
               r"apply(?:ing)? for|take|taking|get)\s+(?:a\s+|an\s+|for\s+)?", "", action.strip()).strip()
    notice = re.match(r"(?i)^(?:i\s+)?(?:am|will be|'ll be|shall be|would be)\s+on\s+", action.strip())
    if not (LEAVE.match(a) or notice and LEAVE.search(action)):
        return None
    rest = re.sub(r"(?i)^(?:i\s+)?(?:am|will be|'ll be|shall be|would be)\s+on\s+", "", a)
    reason, rest = _take(REASON, rest, 1)
    m = re.search(rf"(?i)\bfrom\s+(.+?)\s+(?:to|till|until)\s+(.+?)(?=$|[,;.])", rest)
    whens = []
    if m:
        whens.append(f"from {_when_text(m.group(1))} to {_when_text(m.group(2))}")
        rest = rest[: m.start()] + rest[m.end():]
    while True:
        w, rest2 = _take_when(rest)
        if not w:
            break
        whens.append(_when_text(w))
        rest = rest2
    kind = LEAVE.search(rest)
    what = kind.group(0).lower() if kind else "leave"
    what = {"day off": "a day off", "off day": "a day off", "half day": "a half day's leave", "holiday": "leave",
            "days off": "some days off", "time off": "some time off"}.get(what, "leave")
    when = " ".join(whens)
    if when and re.match(rf"(?i){DAY}$|\d", when):
        when = "on " + when
    reason_s = f", {_reason_text(reason)}" if reason else ""
    when_s = f" {when}" if when else ""
    label = "Leave Notification" if notice else "Leave Request"
    when_subject = _title_subject(re.sub(r"(?i)^(?:on|from|for)\s+", "", when))
    subject = f"{label} – {when_subject}" if when else label
    if notice:
        paras = [f"Please note that I will be on {what.replace('a day off', 'leave').replace('some ', '')}{when_s}{reason_s}.",
                 "I will make sure any pending work is covered in my absence, and I can be reached by phone for anything urgent."]
    else:
        paras = [f"I would like to request {what}{when_s}{reason_s}.",
                 "I will make sure any pending work is handed over and covered in my absence. I would be grateful for your approval."]
    return {"intent": "leave", "subject": subject, "paragraphs": paras}


def _apology(action: str) -> dict | None:
    m = re.match(r"^(?:i\s+am\s+|i'm\s+|im\s+|(?:my\s+)?(?:sincere\s+)?)?(?:sorry|apologi[sz]e|apologies)\b(?:\s+(?:for|about|that|regarding))?\s*(.*)$", action, re.I)
    if not m:
        return None
    thing = _strip_end(tidy(m.group(1)))
    thing = re.sub(r"(?i)^to\s+(?:the\s+)?(?:\w+\s+){0,2}?for\s+", "", thing)  # "apologise to the guest for X" -> "X"
    thing = re.sub(r"(?i)^(?:the|my)\s+", lambda x: x.group(0).lower(), thing)
    if thing and not re.match(r"(?i)(the|my|our|any|this|that|not|being|\w+ing)\b", thing):
        thing = "the " + thing
    if re.match(r"(?i)not\b", thing):
        thing = "not " + thing[4:]
    topic = _title_subject(re.sub(r"(?i)^(?:the|my|our)\s+", "", thing))
    subject = "Apology" + (f" – {topic}" if thing else "")
    return {"intent": "apology", "subject": subject,
            "paragraphs": [f"Please accept my sincere apologies for {_lower_first(thing) or 'the inconvenience caused'}. "
                           "I understand the inconvenience this may have caused, and I am taking steps to ensure it does "
                           "not happen again.",
                           "Thank you for your patience and understanding."]}


def _complaint(action: str) -> dict | None:
    m = re.match(r"^(?:i\s+(?:want|would like|wish)\s+to\s+)?(?:(?:make|raise|file|lodge|register)\s+(?:a\s+)?)?complain(?:t)?s?\s+(?:about|regarding|against|on|of)\s+(.+)$", action, re.I)
    if not m:
        return None
    thing = _strip_end(tidy(m.group(1)))
    if not re.match(r"(?i)(the|a|an|our|my|your|this|these|\d)\b", thing):
        thing = "the " + thing
    return {"intent": "complaint", "subject": "Complaint – " + _title_subject(re.sub(r"(?i)^(?:the|a|an|our|my|your)\s+", "", thing)),
            "paragraphs": [f"I would like to bring to your attention a concern regarding {_lower_first(_you(thing))}.",
                           "I would appreciate it if this could be looked into and resolved at the earliest. Kindly let me "
                           "know the steps being taken."]}


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
    # "(can you) tell me when the chairs will arrive" -> a polite question.
    m = re.match(r"(?i)^(?:please\s+)?(?:tell|inform|update|let)\s+(?:me|us)(?:\s+know)?\s+((?:when|if|whether|what|why|how|where|who|which)\b.+)$", a)
    if m:
        q = _you(m.group(1))
        return {"intent": "question", "subject": _subject(m.group(1), query=True),
                "paragraphs": [f"Could you please let me know {_lower_first(q)}?", "I look forward to hearing from you."]}
    if verb in ("tell", "ask", "instruct", "direct", "request", "urge", "advise") and link == "to" or (
            not verb and IMPERATIVE.match(a)):
        a = _you(a) if verb else a
        a2 = re.sub(r"(?i)^(?:please|kindly)\s+", "", a)
        body = f"Please {_lower_first(a2)}."
        subject = _subject(a2)
        return {"intent": "instruction", "subject": subject,
                "paragraphs": [body, "Kindly treat this as a priority and confirm once it has been done."]}
    # "will be late tomorrow" / "can not come" are statements, not questions ("will you ..." is one).
    statement = re.match(r"(?i)^(?:will|would|can|could|should|am|was|have|has|did|do)\s+(?!you|we|they|he|she|it|the|this|that|"
                         r"there|i\b|your|our|my|all|any|someone|anyone)\w", a) and not action.strip().endswith("?")
    if not statement and (QUESTION.match(a) or action.strip().endswith("?") or link in ("if", "whether", "why", "when", "what", "how")):
        q = a
        if link in ("if", "whether", "why", "when", "what", "how"):
            q = f"{link} {_lower_first(_you(a))}"
            body = f"Could you please let me know {q}?"
            a = q  # the subject is built from the whole question ("why the report was not shared")
        elif re.match(r"(?i)^(?:why|when|where|how|what|who|which|whether|if)\s+(?:the|my|our|your|this|that|these|those|he|she|"
                      r"they|it|you|we|there|\w+'s)\b", q):
            # "why the cleaning was not done?" (statement word order) -> "Could you please let me know why ...?"
            body = f"Could you please let me know {_lower_first(_strip_end(q).rstrip('?'))}?"
        else:
            body = sentence(q).rstrip(".") + ("" if q.endswith("?") else "?")
        return {"intent": "question", "subject": _subject(a, query=True),
                "paragraphs": [body, "I look forward to hearing from you."]}
    if link in ("about", "regarding", "re", "on", "of", "for"):
        topic = _lower_first(a)
        return {"intent": "inform", "subject": _subject(a),
                "paragraphs": [f"I am writing to you regarding {topic}, and would appreciate the opportunity to discuss it "
                               "with you.",
                               "Please let me know a time that suits you."]}
    # A statement: "inform X that ...", or plain text.
    stmt = _lower_first(a)
    if verb in ("inform", "notify", "tell", "update", "warn") or link == "that" or re.match(r"(?i)^that\b", a):
        stmt = re.sub(r"(?i)^that\s+", "", stmt)
        body = f"Please note that {stmt}."
    else:
        return _freeform(a)
    return {"intent": "inform", "subject": _subject(re.sub(r"(?i)^that\s+", "", a)),
            "paragraphs": [body + " Kindly plan accordingly.", QUESTIONS]}


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
    # A sentence typed without "I": "need the report by friday" -> "I need ..."
    (r"^(need|want|have to|would like|cannot|could not|did not|am going to|"
     r"will(?!\s+(?:you|we|they|he|she|it|this|that|these|the|there|all|everyone)\b))\b", lambda m: "I " + m.group(1).lower()),
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
    (r"\bsend me\b", "share with me"), (r"\btell me\b", "inform me"),
    (r"\bcan you\b", "could you"), (r"\bthanks a lot\b", "thank you very much"), (r"\bthanks\b", "thank you"),
    (r"\bsorry\b", "I apologise"),
    (r"\bfix(ed)?\b(?=\s+(?:the |this |that |these |those |my |our |your |all )?(?:\w+ )?(?:issues?|problems?|errors?|bugs?|matters?|complaints?|quer(?:y|ies)|discrepanc(?:y|ies)|mistakes?)\b)",
     lambda m: "resolved" if m.group(1) else "resolve"),
    (r"\bfix\b", "repair"), (r"\bfixed\b", "repaired"), (r"\bbuy\b", "purchase"),
    (r"\bbought\b", "purchased"), (r"\ba lot of\b", "a large number of"), (r"\blots of\b", "a large number of"),
    (r"\bstuff\b", "items"), (r"\blate coming\b", "late arrival"), (r"\bcoming late\b", "late arrival"),
    (r"\b(today|tomorrow|now) itself\b", r"\1"),
    (r"^(the [\w ]{2,40}?) (?:has|have) not (?:come|arrived|been received) yet\b",
     lambda m: "I have not yet received " + m.group(1)[:1].lower() + m.group(1)[1:]),
    (r"\bget (the [^.,;]{2,40}?) (fixed|repaired)\b", r"have \1 repaired"),
    (r"\bget (it|this|them|these|the \w+(?: \w+)?) (fixed|repaired)\b", r"have \1 repaired"),
    (r"\bget (it|this|them|these|the \w+(?: \w+)?) (resolved|sorted)\b", r"have \1 resolved"),
    (r"\bget (it|this|them|these|the \w+) (done|completed|finished)\b", r"have \1 completed"),
    (r"\bits (done|ready|complete|completed|working|fixed|resolved|finished|over|available)\b", r"it is \1"),
    (r"\bthere (?:is|are) (?:a )?lots? of\b", "there are numerous"), (r"\blots? of\b", "numerous"),
    (r"\b(is|are) not (\w+ing) since\b", lambda m: ("has" if m.group(1).lower() == "is" else "have") + f" not been {m.group(2)} since"),
    (r"\bI want (?=(?:the|a|an|all|your|this|these)\b)", "I would like to request "),
    (r"\bwhen it is done\b", "once it has been completed"),
    (r"\bhelp\b(?=\s+(?:me|us)\b)", "assist"), (r"\bmake sure\b", "ensure"),
    (r"\bkindly kindly\b", "kindly"), (r"\bplease kindly\b", "kindly"), (r"\bkindly please\b", "kindly"),
    (r"\bvery very\b", "very"), (r"\breally\s+", ""), (r"\bjust\s+(?=[a-z])", ""), (r"\bbasically,?\s+", ""),
    # "is not working since 2 days" -> "has not been working for the past 2 days"
    (r"\b(is|are) not (\w+ing) (?=since (?:\d+|two|three|four|five|six|seven|a few|few|several) )",
     lambda m: ("has" if m.group(1).lower() == "is" else "have") + f" not been {m.group(2)} "),
    (r"\bsince (\d+|two|three|four|five|six|seven|a few|few|several) (days?|weeks?|months?|hours?)\b", r"for the past \1 \2"),
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


GREETING_LEAD = re.compile(r"^(?:hi|hello|hey|dear|salam|salaam|assalam\w*(?:\s+o\s+alaikum)?|aoa|good (?:morning|afternoon|evening))"
                           r"\b(?:\s+(?!i\b|we\b|pls\b|please\b|kindly\b)[a-z]+){0,2}\s*[,!.:-]\s*", re.I)


def _split_sentences(text: str) -> list[str]:
    text = re.sub(r"(?i),\s+(?=(?:please|pls|plz|kindly)\b)", ". ", text.strip())
    text = re.sub(r"(?i),\s+(?=(?:get|have|make)\s+(?:it|them|this|these)\s+\w+ed\b)", ". ", text)  # "..., get it fixed"
    parts = re.split(r"(?<=[.!?])\s+|\n+", text)
    out = []
    for p in parts:
        p = GREETING_LEAD.sub("", p.strip(" -*•\t")).strip(" -*•\t")  # "Salam, I will ..." -> "I will ..."
        if p:
            out.append(p)
    return out


def _polish_sentence(s: str) -> str:
    s = formalize(tidy(s))
    m = re.match(r"(?i)^(also|and|then|plus)\s+(.*)$", s)
    lead = ""
    if m:
        lead, s = "Additionally, ", m.group(2)
    imperative = IMPERATIVE.match(s) or re.match(r"(?i)have (?:it|them|this|these|the \w+) \w+ed\b", s)
    if imperative and not re.match(r"(?i)(please|kindly)\b", s):
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
    asks = any(re.match(r"(?i)(?:additionally,\s+)?(?:please|kindly|could you|would you|can you)\b(?!\s+(?:find|note|see|refer))", s)
               or s.endswith("?") for s in polished)
    closing = "Thank you for your prompt attention to this." if asks else QUESTIONS
    return {"intent": "message", "subject": subject, "paragraphs": paras + [closing]}


def signature_block(sig: dict | str | None) -> str:
    if isinstance(sig, str) or sig is None:
        sig = {"name": sig or ""}
    lines = [str(sig.get(k) or "").strip() for k in ("name", "title", "company", "phone")]
    return "Best regards,\n" + "\n".join(x for x in lines if x)


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
        extra = " ".join(_polish_sentence(x) for x in sents[1:])
    else:
        action = sents[0]  # one sentence, without a typed greeting ("Salam, ...")
    # Tidy the instruction once (spelling, shorthand) before matching templates.
    action = re.sub(r"(?i)^(?:can|could|would|will)\s+you\s+(?:please\s+|kindly\s+)?", "", action).rstrip(" ?")
    action_t = tidy(action)
    if not re.match(r"(?i)^\s*(?:hold|stop|withhold|freeze|block|release|resume|deduct|cut|increase|revise|pay|process)\b", action_t):
        action_t = names_in(action_t)
    out = _leave(action_t) or _apology(action_t) or _complaint(action_t)
    if not out and verb == "remind":
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
    return any(fn(t) for fn in (_leave, _apology, _complaint, _salary, _meeting, _approval, _explanation, _follow_up,
                                _request_doc)) or bool(
        _reminder(t, verb) or _thanks(t, verb))


def _finish(out: dict, p: dict, recipient_names, my_name) -> dict:
    names = list(recipient_names or [])
    hello = greeting(names) if names else ("Dear All," if any(re.search(r"(?i)\b(all|team|staff|everyone|heads)\b", x) for x in p["to"]) else "Dear Sir/Madam,")
    paragraphs = [formalize(re.sub(r"[ \t]+", " ", x).strip()) for x in out["paragraphs"] if x and x.strip()]
    body = hello + "\n\n" + "\n\n".join(paragraphs) + "\n\n" + signature_block(my_name)
    subject = re.sub(r"\s+", " ", out["subject"]).strip(" –-:")[:120] or "Message"
    return {"subject": subject, "body": body.strip(), "intent": out["intent"]}


# ---------------------------------------------------------------------------
# "Give a task": an assignment email, and the task it creates

_VERBS = ("send share submit prepare provide complete finish finalise finalize arrange organise organize check inspect "
          "review verify repair fix resolve clean update install replace order purchase buy book cancel confirm collect "
          "deliver pay clear approve schedule investigate handle process issue transfer hire recruit train assign "
          "allocate count audit reconcile print remove shift move return implement coordinate maintain increase reduce "
          "stop plan settle secure lock call contact visit attend follow make ensure get bring take keep fill "
          "draft write design create set close open distribute inform compile upload download email").split()
_DOUBLE = {"stop", "plan", "get", "set", "put", "ship", "drop", "chat", "run", "shop", "submit", "commit", "cut"}


def _gerund(v: str) -> str:
    if v.endswith("ie"):
        return v[:-2] + "ying"
    if v in _DOUBLE:
        return v + v[-1] + "ing"
    if v.endswith("e") and not v.endswith(("ee", "ye", "oe")):
        return v[:-1] + "ing"
    return v + "ing"


GERUNDS = {_gerund(v): v for v in _VERBS}

TASK_LEAD = [
    # give a task to qasim to/of send(ing) the report
    re.compile(r"^(?:please\s+)?(?:give|assign|allot|hand)\s+(?:an?\s+|the\s+)?(?:new\s+)?task\s+to\s+(?P<who>.+?)\s*(?:\bto\b|\bof\b|\bfor\b|:|,|-|\bthat\b)\s*(?P<what>.+)$", re.I),
    # give qasim the task of ... / assign bilal a task to ...
    re.compile(r"^(?:please\s+)?(?:give|assign|allot)\s+(?P<who>(?:(?!(?:the|a|an|task)\b)\S+\s*){1,4}?)\s*(?:an?\s+|the\s+)?(?:new\s+)?task\s*(?:\bto\b|\bof\b|\bfor\b|:|,|-|\bthat\b)?\s*(?P<what>.+)$", re.I),
    # task for hr: update the sheet
    re.compile(r"^(?:task|new task)\s+(?:for|to)\s+(?P<who>.+?)\s*(?::|,|-|\bto\b)\s*(?P<what>.+)$", re.I),
    # assign the monthly audit to ahmed
    re.compile(r"^(?:please\s+)?assign\s+(?P<what>.+?)\s+to\s+(?P<who>[\w.@'-]+(?:\s+[\w.@'-]+)?)$", re.I),
]

_MONTHS = {m: i for i, m in enumerate("jan feb mar apr may jun jul aug sep oct nov dec".split(), 1)}
_DAYS = "monday tuesday wednesday thursday friday saturday sunday".split()


def resolve_due(when: str, today=None) -> str | None:
    """'by friday' / 'tomorrow' / '20 nov' / '21/11' (dd/mm) / 'end of the month' -> 'YYYY-MM-DD' (None if unclear)."""
    import calendar
    from datetime import date, timedelta
    today = today or date.today()
    w = re.sub(r"(?i)^(?:by|before|on|until|till|for|within|latest by|no later than)\s+", "", (when or "").strip().lower())
    w = re.sub(r"\s+(?:at|by|around)\s+.*$", "", w).strip(" .,")
    w = re.sub(r"\s+itself$", "", w)
    if not w:
        return None
    if w in ("today", "tonight", "the end of the day", "end of the day", "eod"):
        return today.isoformat()
    if w == "tomorrow":
        return (today + timedelta(days=1)).isoformat()
    if w == "day after tomorrow":
        return (today + timedelta(days=2)).isoformat()
    m = re.fullmatch(r"(\d+)\s+(day|days|week|weeks)", w)
    if m:
        return (today + timedelta(days=int(m.group(1)) * (7 if m.group(2).startswith("week") else 1))).isoformat()
    if re.fullmatch(r"(?:the\s+)?end\s+of\s+(?:the\s+|this\s+)?month|eom", w):
        return today.replace(day=calendar.monthrange(today.year, today.month)[1]).isoformat()
    if re.fullmatch(r"(?:the\s+)?end\s+of\s+(?:the\s+|this\s+)?week", w):
        return (today + timedelta(days=(4 - today.weekday()) % 7)).isoformat()  # Friday
    if w == "next week":
        return (today + timedelta(days=7 - today.weekday())).isoformat()  # next Monday
    m = re.fullmatch(rf"(this\s+|coming\s+|next\s+)?({'|'.join(_DAYS)})", w)
    if m:
        ahead = (_DAYS.index(m.group(2)) - today.weekday()) % 7 or 7
        return (today + timedelta(days=ahead)).isoformat()

    def build(d: int, mo: int, y: str | None) -> str | None:
        try:
            if y:
                return date(int(y) + (2000 if int(y) < 100 else 0), mo, d).isoformat()
            dt = date(today.year, mo, d)
            if dt < today - timedelta(days=60):  # "5 jan" written in November means next January
                dt = date(today.year + 1, mo, d)
            return dt.isoformat()
        except ValueError:
            return None

    m = re.fullmatch(r"(\d{1,2})(?:st|nd|rd|th)?\s+(?:of\s+)?([a-z]{3})[a-z]*\.?(?:,?\s+(\d{4}))?", w)
    if m and m.group(2) in _MONTHS:
        return build(int(m.group(1)), _MONTHS[m.group(2)], m.group(3))
    m = re.fullmatch(r"([a-z]{3})[a-z]*\.?\s+(\d{1,2})(?:st|nd|rd|th)?(?:,?\s+(\d{4}))?", w)
    if m and m.group(1) in _MONTHS:
        return build(int(m.group(2)), _MONTHS[m.group(1)], m.group(3))
    m = re.fullmatch(r"(\d{1,2})[/.-](\d{1,2})(?:[/.-](\d{2,4}))?", w)
    if m:
        return build(int(m.group(1)), int(m.group(2)), m.group(3))
    return None


def short_title(text: str, limit: int = 55) -> str:
    """Shorten at a natural break ('... and share it with accounts' -> first part), never mid-phrase."""
    t = _strip_end(re.sub(r"\s+", " ", text or "").strip())
    if len(t) <= limit:
        return t
    for sep in (r",\s+", r"\s+and\s+(?:then\s+)?", r"\s+(?:so that|because|as|which|who|since|after|before|while)\s+"):
        head = re.split(sep, t, maxsplit=1, flags=re.I)[0]
        if 12 <= len(head) <= limit:
            return _strip_end(head)
    cut = t[:limit].rsplit(" ", 1)[0]
    words = cut.split()
    while words and words[-1].lower() in SMALL_WORDS | {"the", "a", "an", "all", "your", "our", "my", "this", "that"}:
        words.pop()
    return " ".join(words)


def due_label(iso: str) -> str:
    """'Due Today' / 'Due Tomorrow' / 'Due Fri 20 Nov' (year only when it isn't this year)."""
    from datetime import date
    d, today = date.fromisoformat(iso), date.today()
    if d == today:
        return "Due Today"
    if (d - today).days == 1:
        return "Due Tomorrow"
    return f"Due {d.strftime('%a')} {d.day} {d.strftime('%b')}" + (f" {d.year}" if d.year != today.year else "")


def deadline_label(when: str) -> str:
    """'by friday' -> 'By Fri 20 Nov'; 'as soon as possible' -> 'Urgent'; 'by 5 pm' -> 'By 5 pm'."""
    w = (when or "").strip()
    if re.search(r"(?i)as soon as possible|asap|at the earliest|immediately|urgent", w):
        return "Urgent"
    iso = resolve_due(w)
    if iso:
        return due_label(iso).replace("Due ", "By ").replace("By Today", "Today").replace("By Tomorrow", "By Tomorrow")
    t = _when_text(w)
    return t[:1].upper() + t[1:]


def pretty_date(iso: str) -> str:
    from datetime import date
    d = date.fromisoformat(iso)
    return f"{d.strftime('%A')}, {d.day} {d.strftime('%B %Y')}"


def task_parse(note: str) -> dict:
    """{to, cc, title, when, extra}: who gets the task and what it is."""
    p = parse(note)
    sents = [x for x in _split_sentences(p["action"]) if not FILLER_SENTENCE.match(x.strip())] or [p["action"]]
    first, extra = sents[0], sents[1:]
    first = re.sub(r"(?i)^(?:can|could|would|will)\s+you\s+(?:please\s+|kindly\s+)?", "", first).strip().rstrip(" ?.")
    to = list(p["to"])
    for rx in TASK_LEAD:
        m = rx.match(first)
        if m:
            to += _split_people(m.group("who"))
            first = m.group("what")
            break
    else:
        first = re.sub(r"(?i)^(?:a\s+|the\s+)?(?:new\s+)?task\s*(?:of|to|for|:|-)?\s*", "", first)
    first = re.sub(r"(?i)^(?:to|of|for|that)\s+", "", first.strip())
    words = first.split(" ", 1)
    if words and words[0].lower() in GERUNDS:  # "sending the report" -> "send the report"
        first = GERUNDS[words[0].lower()] + (" " + words[1] if len(words) > 1 else "")
    first = re.sub(r"(?i)^(?:please|kindly|pls|plz)\s+", "", first)
    first = re.sub(r"(?i)^(?:he|she|they|you)\s+(?:should|must|will|has to|have to|needs? to)\s+", "", first)
    when, rest = _take_when(first)
    title = _strip_end(formalize(tidy(_you(rest))))
    title = re.sub(r"(?i)^(?:please|kindly)\s+", "", title)
    if not IMPERATIVE.match(title):  # a plain noun: "the monthly audit" -> "Monthly audit"
        title = re.sub(r"(?i)^(?:the|a|an)\s+", "", title)
    return {"to": _dedupe(to), "cc": p["cc"], "title": (title[:1].upper() + title[1:])[:200], "when": when, "extra": extra}


def task_email(note: str, recipient_names: list[str] | None = None, my_name: dict | str = "", due: str | None = None,
               importance: str = "normal", parsed: dict | None = None) -> dict:
    """{subject, body, intent: 'task', task: {title, due, importance}}. due: 'YYYY-MM-DD' picked by the user, if any."""
    t = parsed or task_parse(note)
    if not t["title"]:
        raise ValueError("empty")
    due = due or resolve_due(t["when"])
    due_text = pretty_date(due) if due else (sentence(_when_text(t["when"])).rstrip(".") if t["when"] else "")
    lines = [f"Task: {t['title']}"]
    if due_text:
        lines.append(f"Due date: {due_text}")
    if importance == "high":
        lines.append("Priority: High")
    paras = ["I would like to assign you the following task:", "\n".join(lines)]
    if t["extra"]:
        paras.append(" ".join(_polish_sentence(x) for x in t["extra"]))
    paras.append("Please confirm that you have received this task, and let me know once it has been completed"
                 + (" or if you foresee any delay." if due_text else "."))
    subject = f"Task: {_title_subject(short_title(t['title']))}" + (f" – {due_label(due)}" if due else "")
    names = list(recipient_names or [])
    hello = greeting(names) if names else "Dear Sir/Madam,"
    body = hello + "\n\n" + "\n\n".join(paras) + "\n\n" + signature_block(my_name)
    return {"subject": subject[:120], "body": body, "intent": "task",
            "task": {"title": t["title"], "due": due, "importance": "high" if importance == "high" else "normal"}}
