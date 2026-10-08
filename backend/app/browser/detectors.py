"""Pure HTML detectors used by the browser agent (testable without a browser).

`extract_form()` turns a page (or frame) into structured fields, radio groups, buttons, iframes and
validation errors. Elements tagged by the Playwright agent with `data-ajh-id` / `data-ajh-hidden`
get exact selectors and visibility information.
"""
from __future__ import annotations

import hashlib
import re
from html.parser import HTMLParser

from app.services.detection import detect_video_requirement
from app.services.text_utils import html_to_text

# Interactive challenges only. Passive/invisible reCAPTCHA scripts (common on ATS forms) are handled by the browser
# itself; if they escalate to a visible challenge, these markers appear and the agent stops. Nothing is ever solved/bypassed.
CAPTCHA_MARKUP = [r"recaptcha/(?:api2|enterprise)/(?:anchor|bframe)", r"hcaptcha\.com/captcha", r"<[^>]*class=[\"'][^\"']*h-captcha",
                  r"cf-turnstile", r"challenges\.cloudflare\.com", r"arkoselabs|funcaptcha", r"px-captcha"]
CAPTCHA_TEXT = [r"verify (?:that )?you(?:'re| are) (?:a )?human", r"are you a robot", r"press (?:&|and) hold",
                r"(?:complete|solve) the captcha", r"captcha (?:is )?required"]
TWO_FA_PATTERNS = [r"autocomplete=[\"']one-time-code", r"verification code", r"two[- ]factor", r"2-step verification",
                   r"authenticator app", r"enter the code (?:we )?sent", r"one-time (?:pass)?code", r"security code"]
ERROR_PATTERNS = [r"this field is required", r"\bis required\b", r"can'?t be blank", r"cannot be blank", r"please (?:complete|fill|enter|select|provide)\b",
                  r"\binvalid (?:email|phone|value|format)", r"there (?:was|were) (?:a |an )?(?:problem|errors?) with your (?:application|submission)"]
REQUIRED_MARK = re.compile(r"\s*(\*|✱|\(required\)|required)\s*$", re.I)


def _strip_scripts(html: str) -> str:
    return re.sub(r"<(script|style|noscript)[^>]*>.*?</\1>", " ", html or "", flags=re.S | re.I)


def html_text(html: str) -> str:
    return html_to_text(_strip_scripts(html))


def page_title(html: str) -> str:
    m = re.search(r"<title[^>]*>(.*?)</title>", html or "", re.S | re.I)
    return re.sub(r"\s+", " ", m.group(1)).strip() if m else ""


def detect_captcha(html: str) -> bool:
    low = (html or "").lower()
    if any(re.search(p, low) for p in CAPTCHA_MARKUP):
        return True
    for tag in re.findall(r"<[^>]*class=[\"'][^\"']*g-recaptcha[^>]*>", low):
        if "invisible" not in tag:  # visible checkbox widget
            return True
    text = html_text(html).lower()
    return any(re.search(p, text) for p in CAPTCHA_TEXT)


def detect_passive_captcha(html: str) -> bool:
    low = (html or "").lower()
    return bool(re.search(r"recaptcha/(?:api|enterprise)\.js|grecaptcha|g-recaptcha", low))


def detect_login(html: str) -> bool:
    low = (html or "").lower()
    has_password = re.search(r"<input[^>]+type=[\"']?password", low) is not None
    text = html_text(html).lower()
    sign_in = re.search(r"\b(sign in|log in|login|iniciar sesi[oó]n)\b", text) is not None
    return has_password or (sign_in and re.search(r"to (?:continue|apply)|sign in to apply|log in to apply|join to apply", text) is not None)


def detect_2fa(html: str) -> bool:
    low = (html or "").lower()
    if re.search(TWO_FA_PATTERNS[0], low):
        return True
    text = html_text(html).lower()
    return any(re.search(p, text) for p in TWO_FA_PATTERNS[1:])


def detect_video(html: str) -> bool:
    return detect_video_requirement(html_text(html)).required


def detect_errors(html: str) -> list[str]:
    text = html_text(html)
    found = []
    for line in text.splitlines():
        if any(re.search(p, line, re.I) for p in ERROR_PATTERNS) and len(line) < 200:
            found.append(line.strip())
    return list(dict.fromkeys(found))[:10]


def clean_label(text: str) -> tuple[str, bool]:
    t = re.sub(r"\s+", " ", text or "").strip(" :")
    required = bool(REQUIRED_MARK.search(t)) or "*" in t or "✱" in t
    t = REQUIRED_MARK.sub("", t)
    t = t.replace("*", "").replace("✱", "").strip(" :")
    return t, required


def _attr_sel(tag: str, a: dict, index: int) -> str:
    if a.get("data-ajh-id"):
        return f'[data-ajh-id="{a["data-ajh-id"]}"]'
    if a.get("id"):
        return f'[id="{a["id"]}"]'
    typ = (a.get("type") or "").lower()
    if a.get("name"):
        if typ in ("radio", "checkbox") and a.get("value") is not None:
            return f'input[name="{a["name"]}"][value="{a["value"]}"]'
        return f'{tag}[name="{a["name"]}"]'
    if a.get("aria-label"):
        return f'{tag}[aria-label="{a["aria-label"]}"]'
    return f"{tag} >> nth={index}"


class _FormParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.items: list[dict] = []          # inputs/selects/textareas in document order
        self.buttons: list[dict] = []
        self.iframes: list[dict] = []
        self.labels_for: dict[str, str] = {}
        self._label: dict | None = None      # {"for", "texts", "items"}
        self._legend_stack: list[str] = []
        self._in_legend = False
        self._legend_text: list[str] = []
        self._pending: list[str] = []        # text since the previous control (fallback label: Lever-style div labels)
        self._select: dict | None = None
        self._option: dict | None = None
        self._button: dict | None = None
        self._textarea: dict | None = None
        self._skip = 0
        self._tag_counts: dict[str, int] = {}

    def _count(self, tag: str) -> int:
        n = self._tag_counts.get(tag, 0)
        self._tag_counts[tag] = n + 1
        return n

    def handle_starttag(self, tag, attrs):
        a = {k: (v if v is not None else "") for k, v in attrs}
        if tag in ("script", "style", "noscript"):
            self._skip += 1
            return
        if tag == "fieldset":
            self._legend_stack.append("")
        elif tag == "legend":
            self._in_legend, self._legend_text = True, []
        elif tag == "label":
            self._label = {"for": a.get("for"), "texts": [], "items": []}
        elif tag == "iframe":
            self.iframes.append({"src": a.get("src") or "", "id": a.get("id"), "name": a.get("name"), "title": a.get("title")})
        elif tag in ("input", "select", "textarea"):
            idx = self._count(tag)
            typ = (a.get("type") or ("textarea" if tag == "textarea" else "select" if tag == "select" else "text")).lower()
            hidden = a.get("data-ajh-hidden") == "1" or "hidden" in a or "display:none" in (a.get("style") or "").replace(" ", "")
            if typ in ("submit", "button", "image", "reset"):
                if typ == "submit" or typ == "button":
                    self.buttons.append({"selector": _attr_sel(tag, a, idx), "text": a.get("value") or typ, "type": typ,
                                         "disabled": "disabled" in a, "hidden": hidden})
                return
            if typ == "hidden":
                return
            item = {"tag": tag, "type": typ, "attrs": a, "selector": _attr_sel(tag, a, idx), "hidden": hidden,
                    "pending": " ".join(self._pending)[-200:], "legend": self._legend_stack[-1] if self._legend_stack else "",
                    "options": [], "selected": None, "value": a.get("value") or "",
                    "required_attr": "required" in a or a.get("aria-required") == "true", "label_texts": None}
            self._pending = []
            self.items.append(item)
            if self._label is not None:
                self._label["items"].append(item)
            if tag == "select":
                self._select = item
            if tag == "textarea":
                self._textarea = item
        elif tag == "option" and self._select is not None:
            self._option = {"text": "", "value": a.get("value"), "selected": "selected" in a}
        elif tag == "button":
            idx = self._count("button")
            self._button = {"attrs": a, "text": "", "type": (a.get("type") or "submit").lower(), "idx": idx,
                            "disabled": "disabled" in a,
                            "hidden": a.get("data-ajh-hidden") == "1" or "display:none" in (a.get("style") or "").replace(" ", "")}

    def handle_endtag(self, tag):
        if tag in ("script", "style", "noscript"):
            self._skip = max(0, self._skip - 1)
            return
        if tag == "legend":
            self._in_legend = False
            if self._legend_stack:
                self._legend_stack[-1] = " ".join(self._legend_text).strip()
            self._pending = []
        elif tag == "fieldset":
            if self._legend_stack:
                self._legend_stack.pop()
        elif tag == "label" and self._label is not None:
            text = " ".join(self._label["texts"]).strip()
            if self._label["for"]:
                self.labels_for[self._label["for"]] = text
            for it in self._label["items"]:
                it["label_texts"] = text
            had_items = bool(self._label["items"])
            self._label = None
            self._pending = [] if had_items else ([text] if text else [])
        elif tag == "option" and self._option is not None and self._select is not None:
            text = self._option["text"].strip()
            self._select["options"].append(text)
            if self._option["selected"]:
                self._select["selected"] = text
            self._option = None
        elif tag == "select":
            self._select = None
        elif tag == "textarea":
            self._textarea = None
        elif tag == "button" and self._button is not None:
            b = self._button
            a = b["attrs"]
            text = re.sub(r"\s+", " ", b["text"]).strip()
            if a.get("data-ajh-id"):
                sel = f'[data-ajh-id="{a["data-ajh-id"]}"]'
            elif a.get("id"):
                sel = f'[id="{a["id"]}"]'
            elif text:
                sel = f'button:has-text("{text}")'
            else:
                sel = f"button >> nth={b['idx']}"
            self.buttons.append({"selector": sel, "text": text or a.get("aria-label") or "", "type": b["type"],
                                 "disabled": b["disabled"], "hidden": b["hidden"]})
            self._button = None

    def handle_data(self, data):
        if self._skip:
            return
        txt = data.strip()
        if not txt:
            return
        if self._option is not None:
            self._option["text"] += data
            return
        if self._button is not None:
            self._button["text"] += " " + txt
            return
        if self._textarea is not None:
            self._textarea["value"] += txt
            return
        if self._in_legend:
            self._legend_text.append(txt)
            return
        if self._label is not None:
            self._label["texts"].append(txt)
            return
        self._pending.append(txt)
        if len(self._pending) > 12:
            self._pending = self._pending[-12:]


CONSENT_RE = re.compile(r"\b(agree|consent|terms|privacy|acknowledge|certify|i confirm|confirm that|accept|authori[sz]e|gdpr|policy)\b", re.I)


def _label_for(it: dict, labels_for: dict) -> str:
    a = it["attrs"]
    if a.get("id") and labels_for.get(a["id"]):
        return labels_for[a["id"]]
    if it.get("label_texts"):
        return it["label_texts"]
    return a.get("aria-label") or a.get("placeholder") or it.get("pending") or a.get("name") or ""


def _sig(*parts) -> str:
    return hashlib.sha1("|".join(str(p) for p in parts).encode()).hexdigest()[:10]


def extract_form(html: str) -> dict:
    """Structured view of one document: {fields, buttons, iframes, errors}."""
    p = _FormParser()
    p.feed(html or "")
    fields: list[dict] = []
    radio_groups: dict[str, dict] = {}
    for it in p.items:
        a = it["attrs"]
        raw_label = _label_for(it, p.labels_for)
        label, req_mark = clean_label(raw_label)
        required = it["required_attr"] or req_mark
        if it["type"] == "radio":
            name = a.get("name") or it["selector"]
            g = radio_groups.get(name)
            if g is None:
                glabel, greq = clean_label(it["legend"] or it["pending"] or name)
                g = {"type": "radio_group", "tag": "input", "name": name, "label": glabel, "required": greq or required,
                     "options": [], "option_selectors": {}, "hidden": it["hidden"], "selector": f'input[type="radio"][name="{name}"]',
                     "value": ""}
                radio_groups[name] = g
                fields.append(g)
            opt = label or a.get("value") or ""
            g["options"].append(opt)
            g["option_selectors"][opt] = it["selector"]
            g["required"] = g["required"] or required
            g["hidden"] = g["hidden"] and it["hidden"]
            if "checked" in a:
                g["value"] = opt
            continue
        if it["type"] == "checkbox" and it["legend"]:
            glabel, greq = clean_label(it["legend"])
            label = f"{glabel} — {label}" if label and label != glabel else glabel
            required = required or (greq and len([x for x in p.items if x["attrs"].get("name") == a.get("name")]) == 1)
        f = {"type": it["type"], "tag": it["tag"], "name": a.get("name"), "label": label, "required": required,
             "options": it["options"], "selector": it["selector"], "hidden": it["hidden"],
             "value": it["selected"] if it["tag"] == "select" else ("checked" if "checked" in a else "") if it["type"] == "checkbox" else it["value"],
             "accept": a.get("accept") or ""}
        if it["type"] == "checkbox":
            f["consent"] = bool(CONSENT_RE.search(label))
        fields.append(f)
    for f in fields:
        f["key"] = _sig(f["type"], re.sub(r"\W+", " ", f["label"].lower()).strip(), "|".join(f.get("options") or []))
    return {"fields": fields, "buttons": p.buttons, "iframes": p.iframes, "errors": detect_errors(html)}


# ---------------------------------------------------------------- backwards-compatible helpers
def extract_fields(html: str) -> list[dict]:
    out = []
    for f in extract_form(html)["fields"]:
        if f["type"] == "radio_group":
            continue
        out.append({"selector": f["selector"], "tag": f["tag"], "type": f["type"], "name": f.get("name"), "label": f["label"],
                    "required": f["required"], "options": f.get("options") or []})
    return out


def find_submit(html: str) -> str | None:
    buttons = extract_form(html)["buttons"]
    for b in buttons:
        if re.search(r"submit|apply|send|enviar|postular", b["text"], re.I):
            return b["selector"]
    return buttons[0]["selector"] if buttons else None
