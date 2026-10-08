"""Deterministic multi-page, frame-aware fake browser for agent tests (no network, no real sites)."""
from __future__ import annotations

from app.browser import detectors
from app.browser.base import BrowserAgent, FrameInfo


class FakeBrowser(BrowserAgent):
    """pages: url -> html. transitions: (context, button_text) -> next page key.
    context is the current top URL, or the frame id (= iframe src) for actions inside a frame.
    frames: iframe src -> page key (None = inaccessible frame)."""

    def __init__(self, pages: dict[str, str], transitions: dict | None = None, frames: dict | None = None,
                 url_aliases: dict | None = None):
        self.pages = pages
        self.transitions = transitions or {}
        self.frame_pages = dict(frames or {})
        self.url_aliases = url_aliases or {}
        self.url: str | None = None
        self.actions: list[tuple] = []
        self.closed = False

    # navigation
    def open_page(self, url):
        self.actions.append(("open", url))
        self.url = self.url_aliases.get(url, url)
        if self.url not in self.pages:
            raise RuntimeError(f"404 {url}")

    def navigate(self, url):
        self.open_page(url)

    def current_url(self):
        return self.url

    def page_html(self):
        return self.pages[self.url]

    def list_frames(self):
        out = []
        for fr in detectors.extract_form(self.page_html())["iframes"]:
            src = fr["src"]
            key = self.frame_pages.get(src, "__missing__")
            out.append(FrameInfo(id=src, url=src, accessible=key not in (None, "__missing__")))
        return out

    def frame_html(self, frame_id):
        return self.pages[self.frame_pages[frame_id]]

    # actions
    def _apply(self, context: str, html: str, verb: str, selector: str, value):
        self.actions.append((verb, selector, value) if context == self.url else (verb, selector, value, context))
        form = detectors.extract_form(html)
        if verb == "select":
            f = next((f for f in form["fields"] if f["selector"] == selector), None)
            if f is None or value not in f["options"]:
                raise ValueError(f"select_option: no option labelled {value!r} for {selector}")
        if verb == "click":
            b = next((b for b in form["buttons"] if b["selector"] == selector), None)
            if b is None:
                raise ValueError(f"no element {selector}")
            nxt = self.transitions.get((context, b["text"]))
            if nxt is not None:
                if context == self.url:
                    self.url = nxt
                else:
                    self.frame_pages[context] = nxt

    def frame_act(self, frame_id, verb, selector, value=None):
        self._apply(frame_id, self.frame_html(frame_id), verb, selector, value)

    def click(self, selector):
        self._apply(self.url, self.page_html(), "click", selector, None)

    def type(self, selector, text):
        self._apply(self.url, self.page_html(), "type", selector, text)

    def select(self, selector, value):
        self._apply(self.url, self.page_html(), "select", selector, value)

    def check(self, selector):
        self._apply(self.url, self.page_html(), "check", selector, None)

    def upload_file(self, selector, path):
        self._apply(self.url, self.page_html(), "upload", selector, path)

    def close(self):
        self.closed = True

    # helpers for assertions
    def typed(self) -> dict:
        return {a[1]: a[2] for a in self.actions if a[0] in ("type", "select")}

    def did(self, verb: str) -> list[tuple]:
        return [a for a in self.actions if a[0] == verb]
