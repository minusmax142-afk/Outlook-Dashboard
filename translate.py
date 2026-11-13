"""
Any language -> English, before "Write for me" / "Make professional" turn it into a polished email.

    to_english(text) -> (english_text, info)   info = {"translated": bool, "languages": [...]}

How each line is handled (free Google services, no key needed):
    - English lines are left as they are and never leave this PC.
    - Roman Urdu / Roman Hindi ("qasim ko bolo salary rok do") is first written in Hindi script with Google
      Input Tools, then translated with Google Translate. Going through the script keeps the meaning right:
      sent as Roman text, Google often flips it ("tankhwah rok do" came back as "pay the salary").
    - Any other language or script (Urdu, Hindi, Arabic, Spanish, ...) goes straight to Google Translate.
Numbers, emails, codes (AC, SOP, PO) and month abbreviations are kept exactly as typed.
"""

from __future__ import annotations

import json
import re
import urllib.parse
import urllib.request
from functools import lru_cache

from errors import TranslationUnavailable

TIMEOUT = 8
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}

# Words that only appear in Roman Urdu / Hindi (common English words like "do", "main", "par", "to" left out).
ROMAN = set("""
ko ki ka ke kay ky hai hain hy hn hay hoon hun hu ho hon hoga hogi hogay hongay honge raha rahi rahe rahay rahega rahegi
se sy say mein mai mujhe mujhy mujh mera meri mere meray hum humein hamein hamara hamari aap ap apka apki apke tum tumhe
tumhara uska uski uske unka unki unke inka inki yeh ye woh wo wahan yahan
karo kro kar kardo kar do karna krna karni karein karen kijiye kijye karwao karwa karwana karwado krwao karao karado
bhejo bhejdo bhej bhejna bhejein bhejen bhijwa bhijwao mangwa mangwao mangwalo lelo lo dedo dena dein den diya diye
batao btao bata batana bolo bol kaho keh kehdo kahein samjhao dikhao rakho rakh rakhna lagao hatao nikalo roko rok
rokna rokdo kaato kaat kaatlo katlo kato lagwao badlo bulao bulwao milo mil chalo jao aao aa ja gaya gayi gaye
nahi nahin nai mat na haan han ji jee acha accha theek thik sahi galat zaroor zarur jaldi abhi kal aaj parson
subah sham shaam raat dopahar din dino roz hafta hafte mahina mahine saal baje bajay waqt der
liye lye wajah waja kyunke kyunki kyun kyu kya kab kaise kese kahan kitna kitni kitne koi kuch sab saare sare
aur bhi lekin magar phir pher sirf bas wala wali wale walay saath sath baad pehle pehlay tak taq
chahiye chaiye chahye chahta chahti zarurat zaroorat hoti hota hote thi tha thay
chutti chhutti chuti tankhwah tankhwa tankha tanakhwa paise paisay paisa raqam hisaab kharab kharaab
bimar beemar bukhar shaadi shadi ghar daftar dukaan kaam kam yaad dilao dilana shukriya meherbani maafi maaf
baare bare mutalliq hawale ilawa andar bahar upar neeche agla agle pichla pichle
lega legi lenge lengay dega degi denge karega karegi karenge jayega jayegi jaega aayega ayega aayegi hogaya hogya
sakta sakti sakte sakty sambhal sambhalega sambhal lega dekh dekhna dekho dekhlo pata maloom suno sunao
""".split())
VERB_ENDINGS = {"lega", "legi", "lenge", "dega", "degi", "denge", "karega", "karegi", "karenge", "jayega", "jayegi",
                "aayega", "ayega", "sakta", "sakti", "sakte", "sambhal", "dekho", "batao", "bolo", "karo", "dilao"}
STRONG_EXTRA = VERB_ENDINGS
STRONG = {"ko", "ki", "ka", "ke", "hai", "hain", "karo", "kar", "kardo", "nahi", "nahin", "mujhe", "chahiye", "se",
          "mein", "aur", "bhi", "tak", "liye", "bhejo", "batao", "bolo", "kal", "aaj", "mat", "wala", "wali", "raha",
          "rahi", "theek", "thik", "jaldi", "abhi", "kya", "kyun", "hoga", "rahega", "dein", "do", "lo", "dilao"}
MONTH_ABBR = {"jan", "feb", "mar", "apr", "jun", "jul", "aug", "sep", "sept", "oct", "nov", "dec"}
CODES = {"ac": "AC", "hr": "HR", "sop": "SOP", "sops": "SOPs", "po": "PO", "gm": "GM", "agm": "AGM", "md": "MD",
         "ceo": "CEO", "cfo": "CFO", "cctv": "CCTV", "pos": "POS", "kpi": "KPI", "pdf": "PDF", "vip": "VIP",
         "vat": "VAT", "gst": "GST", "ntn": "NTN", "eobi": "EOBI", "pkr": "PKR", "rs": "Rs.", "it": "IT", "fnb": "F&B",
         "led": "LED", "tv": "TV", "wifi": "WiFi", "cv": "CV", "id": "ID", "abc": "ABC"}

# Whole tokens: email | word | number/date | anything else (punctuation, spaces)
TOKEN = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+|[A-Za-z][A-Za-z']*|\d[\d,./:-]*(?:st|nd|rd|th|am|pm)?|[^A-Za-z\d]+")


def _words(line: str) -> list[str]:
    return re.findall(r"[a-z']+", line.lower())


def is_roman_urdu(line: str, nearby: bool = False) -> bool:
    """nearby: another line of the same note is Roman Urdu, so one Urdu word is enough here."""
    words = _words(line)
    if not words:
        return False
    hits = sum(1 for w in words if w in ROMAN)
    strong = sum(1 for w in words if (w in STRONG or w in STRONG_EXTRA) and w not in ("do", "lo"))
    if nearby and hits >= 1:
        return True
    return strong >= 1 and (hits >= 2 or hits / len(words) >= 0.25)


def _foreign_script(line: str) -> bool:
    """Letters outside basic Latin: Urdu/Arabic script, Hindi, Chinese, accented European letters, ..."""
    return any(ch.isalpha() and ord(ch) > 127 for ch in line)


def _get(url: str, data: bytes | None = None):
    req = urllib.request.Request(url, data=data, headers=UA)
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        return json.loads(r.read().decode("utf-8"))


@lru_cache(maxsize=512)
def _to_hindi_script(words: str) -> str:
    q = urllib.parse.urlencode({"text": words, "itc": "hi-t-i0-und", "num": 1})
    d = _get("https://inputtools.google.com/request?" + q)
    if not d or d[0] != "SUCCESS":
        raise ValueError("transliteration failed")
    return d[1][0][1][0]


@lru_cache(maxsize=512)
def _translate(text: str, source: str = "auto") -> tuple[str, str]:
    body = urllib.parse.urlencode({"client": "gtx", "sl": source, "tl": "en", "dt": "t", "q": text}).encode()
    d = _get("https://translate.googleapis.com/translate_a/single", data=body)
    out = "".join(part[0] for part in (d[0] or []) if part and part[0])
    return out.strip(), (d[2] if len(d) > 2 and isinstance(d[2], str) else source)


def _keep(tok: str) -> bool:
    """Tokens passed through unchanged: emails, numbers, codes (AC, SOP), month abbreviations, ALL-CAPS words."""
    low = tok.lower()
    return ("@" in tok or tok[:1].isdigit() or low in CODES or low in MONTH_ABBR
            or (len(tok) >= 2 and tok.isupper()))


def _roman_line(line: str) -> str:
    """Roman Urdu line -> Hindi script (words only; protected tokens and punctuation kept) -> English."""
    parts, run = [], []

    def flush():
        if run:
            parts.append(_to_hindi_script(" ".join(run)))
            run.clear()

    for tok in TOKEN.findall(line):
        if re.fullmatch(r"[A-Za-z][A-Za-z']*", tok) and not _keep(tok):
            run.append(tok.lower())
        elif tok.isspace():
            continue
        else:
            flush()
            low = tok.lower()
            parts.append(CODES.get(low, tok.capitalize() if low in MONTH_ABBR else tok))
    flush()
    hindi = " ".join(parts)
    hindi = re.sub(r"\s+([,.;:!?)])", r"\1", hindi)
    english, _ = _translate(hindi, "hi")
    return english


# Fix-ups for phrasings Google Translate tends to produce from Urdu/Hindi.
AFTER = [
    # "Give warning to Kamran if he is late" (kamran ko late aane par warning do) -> "... for late arrival"
    (r"(?i)\b(warn(?:ing)?\s+(?:to\s+)?[^.,;]+?)\s+(?:if|that|when)\s+(?:he|she|they)\s+(?:is|are|was|were|will be|comes?|came)\s+late\b",
     r"\1 for late arrival"),
    (r"(?i)^give\s+(?:a\s+)?warning\b", "issue a warning"),
    (r"(?i)\bget it done\b", "have it completed"),
]


def _after(text: str) -> str:
    for rx, rep in AFTER:
        text = re.sub(rx, rep, text)
    return text


def to_english(text: str) -> tuple[str, dict]:
    """Translate every non-English line; English lines are returned untouched (and are not sent anywhere)."""
    out, langs = [], []
    lines = (text or "").split("\n")
    roman_note = any(is_roman_urdu(x) for x in lines)
    try:
        for line in lines:
            if not line.strip():
                out.append(line)
            elif is_roman_urdu(line, nearby=roman_note):
                out.append(_after(_roman_line(line)))
                langs.append("Roman Urdu/Hindi")
            elif _foreign_script(line):
                english, lang = _translate(line.strip())
                out.append(_after(english) if lang != "en" else line)
                if lang != "en":
                    langs.append(lang)
            else:
                out.append(line)
    except (OSError, ValueError, KeyError, IndexError, TypeError) as err:
        raise TranslationUnavailable(
            "Couldn't translate your note: the free translation service isn't reachable right now "
            f"({type(err).__name__}). Check your internet connection and try again, or write the note in English."
        ) from None
    names = {"ur": "Urdu", "hi": "Hindi", "pa": "Punjabi", "ar": "Arabic", "fa": "Persian", "es": "Spanish",
             "fr": "French", "de": "German", "zh-CN": "Chinese", "tr": "Turkish"}
    langs = list(dict.fromkeys(names.get(x, x) for x in langs))
    return "\n".join(out), {"translated": bool(langs), "languages": langs}
