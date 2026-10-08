"""Pure HTML detectors used by the browser agent (testable without a browser)."""
from __future__ import annotations

import re
from html.parser import HTMLParser

from app.services.detection import detect_video_requirement
from app.services.text_utils import html_to_text

CAPTCHA_PATTERNS = [r"g-recaptcha", r"recaptcha/api", r"hcaptcha", r"h-captcha", r"cf-turnstile", r"challenges\.cloudflare\.com",
                    r"verify (?:that )?you(?:'re| are) (?:a )?human", r"are you a robot", r"captcha", r"arkoselabs|funcaptcha",
                    r"press (?:&|and) hold", r"px-captcha"]
TWO_FA_PATTERNS = [r"autocomplete=[\"']one-time-code", r"verification code", r"two[- ]factor", r"2-step verification",
                   r"authenticator app", r"enter the code (?:we )?sent", r"one-time (?:pass)?code", r"security code"]


def html_text(html: str) -> str:
    return html_to_text(re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", html or "", flags=re.S | re.I))


def page_title(html: str) -> str:
    m = re.search(r"<title[^>]*>(.*?)</title>", html or "", re.S | re.I)
    return re.sub(r"\s+", " ", m.group(1)).strip() if m else ""


def detect_captcha(html: str) -> bool:
    low = (html or "").lower()
    return any(re.search(p, low) for p in CAPTCHA_PATTERNS)


def detect_login(html: str) -> bool:
    low = (html or "").lower()
    has_password = re.search(r"<input[^>]+type=[\"']?password", low) is not None
    sign_in = re.search(r"\b(sign in|log in|login|iniciar sesi[oó]n)\b", low) is not None
    return has_password or (sign_in and re.search(r"to (?:continue|apply)|sign in to apply|log in to apply|join to apply", low) is not None)


def detect_2fa(html: str) -> bool:
    low = (html or "").lower()
    return any(re.search(p, low) for p in TWO_FA_PATTERNS)


def detect_video(html: str) -> bool:
    return detect_video_requirement(html_text(html)).required


class _FormParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.fields: list[dict] = []
        self.labels_for: dict[str, str] = {}
        self._label_for: str | None = None
        self._label_text: list[str] = []
        self._in_label = False
        self._last_text = ""
        self._select: dict | None = None
        self._option_open = False
        self.buttons: list[dict] = []
        self._button: dict | None = None

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "label":
            self._in_label, self._label_for, self._label_text = True, a.get("for"), []
        elif tag in ("input", "textarea", "select"):
            typ = (a.get("type") or ("textarea" if tag == "textarea" else "select" if tag == "select" else "text")).lower()
            if typ in ("hidden", "submit", "button", "image", "reset"):
                if typ == "submit":
                    self.buttons.append({"selector": _selector(tag, a), "text": a.get("value") or "submit"})
                return
            label = a.get("aria-label") or a.get("placeholder") or ""
            if self._in_label and not self._label_for:
                label = " ".join(self._label_text).strip() or label
            f = {"selector": _selector(tag, a), "tag": tag, "type": typ, "name": a.get("name"), "id": a.get("id"),
                 "label": label, "required": "required" in a or a.get("aria-required") == "true", "options": [],
                 "prev_text": self._last_text}
            self.fields.append(f)
            if tag == "select":
                self._select = f
        elif tag == "option" and self._select is not None:
            self._option_open = True
        elif tag == "button":
            self._button = {"selector": _selector(tag, a), "text": "", "type": (a.get("type") or "submit").lower()}

    def handle_endtag(self, tag):
        if tag == "label":
            if self._label_for:
                self.labels_for[self._label_for] = " ".join(self._label_text).strip()
            self._in_label = False
        elif tag == "select":
            self._select = None
        elif tag == "option":
            self._option_open = False
        elif tag == "button" and self._button is not None:
            if self._button["type"] == "submit":
                self.buttons.append(self._button)
            self._button = None

    def handle_data(self, data):
        txt = data.strip()
        if not txt:
            return
        if self._in_label:
            self._label_text.append(txt)
        if self._option_open and self._select is not None:
            self._select["options"].append(txt)
        if self._button is not None:
            self._button["text"] += txt
        self._last_text = txt[:200]


def _selector(tag: str, a: dict) -> str:
    if a.get("id"):
        return f"#{a['id']}"
    if a.get("name"):
        return f"{tag}[name=\"{a['name']}\"]"
    if a.get("aria-label"):
        return f"{tag}[aria-label=\"{a['aria-label']}\"]"
    return tag


def extract_fields(html: str) -> list[dict]:
    p = _FormParser()
    p.feed(html or "")
    out = []
    for f in p.fields:
        label = p.labels_for.get(f.get("id") or "", "") or f["label"] or f.get("prev_text") or f.get("name") or ""
        out.append({"selector": f["selector"], "tag": f["tag"], "type": f["type"], "name": f.get("name"), "label": label.strip(),
                    "required": f["required"], "options": f["options"]})
    return out


def find_submit(html: str) -> str | None:
    p = _FormParser()
    p.feed(html or "")
    for b in p.buttons:
        if re.search(r"submit|apply|send|enviar|postular", b["text"], re.I):
            return b["selector"]
    return p.buttons[0]["selector"] if p.buttons else None
