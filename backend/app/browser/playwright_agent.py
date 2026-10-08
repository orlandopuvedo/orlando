"""Playwright implementation of BrowserAgent (optional dependency: pip install -r requirements-browser.txt).

Runs a *visible* persistent browser profile by default so YOU log in yourself; the agent never handles passwords.
Before reading a document the agent tags form controls with `data-ajh-id` (unique, stable per page) and
`data-ajh-hidden` (computed visibility) so selectors are exact and invisible controls are not "filled".
"""
from __future__ import annotations

from app.browser.base import BrowserAgent, FrameInfo, HumanInterventionRequired
from app.config import get_settings

TAG_JS = """() => {
  let n = window.__ajhN || 0;
  for (const el of document.querySelectorAll('input,select,textarea,button')) {
    if (!el.hasAttribute('data-ajh-id')) el.setAttribute('data-ajh-id', String(++n));
    const st = window.getComputedStyle(el);
    const r = el.getBoundingClientRect();
    const hidden = st.display === 'none' || st.visibility === 'hidden' || (r.width === 0 && r.height === 0);
    el.setAttribute('data-ajh-hidden', hidden ? '1' : '0');
  }
  window.__ajhN = n;
  return n;
}"""


class PlaywrightBrowserAgent(BrowserAgent):
    def __init__(self, headless: bool | None = None):
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as e:  # pragma: no cover
            raise RuntimeError("Playwright not installed. Run: pip install -r requirements-browser.txt") from e
        s = get_settings()
        self._pw = sync_playwright().start()
        kwargs = {"headless": s.browser_headless if headless is None else headless}
        if s.browser_executable_path:
            kwargs["executable_path"] = s.browser_executable_path
        s.browser_user_data_dir.mkdir(parents=True, exist_ok=True)
        try:
            self._ctx = self._pw.chromium.launch_persistent_context(str(s.browser_user_data_dir), **kwargs)
        except Exception:
            self._pw.stop()
            raise
        self._page = self._ctx.pages[0] if self._ctx.pages else self._ctx.new_page()

    # ---- navigation
    def open_page(self, url: str) -> None:
        self._page.goto(url, wait_until="domcontentloaded", timeout=45000)
        self.wait_for_settle()

    def navigate(self, url: str) -> None:
        self.open_page(url)

    def wait_for_settle(self) -> None:
        try:
            self._page.wait_for_load_state("domcontentloaded", timeout=15000)
            self._page.wait_for_load_state("networkidle", timeout=6000)
        except Exception:
            pass  # SPAs may never reach networkidle; a short fixed wait below covers re-renders
        self._page.wait_for_timeout(800)

    def current_url(self) -> str:
        return self._page.url

    # ---- documents
    def _frame(self, frame_id: str | None):
        if frame_id is None:
            return self._page
        frames = self._page.frames
        idx = int(frame_id)
        if idx >= len(frames):
            raise HumanInterventionRequired("An embedded application frame disappeared — please finish manually.")
        return frames[idx]

    def page_html(self) -> str:
        try:
            self._page.evaluate(TAG_JS)
        except Exception:
            pass
        return self._page.content()

    def list_frames(self) -> list[FrameInfo]:
        out = []
        for i, fr in enumerate(self._page.frames):
            if fr == self._page.main_frame:
                continue
            try:
                fr.evaluate("1")
                ok = True
            except Exception:
                ok = False  # detached or not scriptable — reported as inaccessible, never forced
            out.append(FrameInfo(id=str(i), url=fr.url, accessible=ok))
        return out

    def frame_html(self, frame_id: str) -> str:
        fr = self._frame(frame_id)
        try:
            fr.evaluate(TAG_JS)
            return fr.content()
        except Exception as e:
            raise HumanInterventionRequired(f"Embedded application frame is not accessible ({e}).") from e

    # ---- actions
    def frame_act(self, frame_id: str, verb: str, selector: str, value: str | None = None) -> None:
        self._do(self._frame(frame_id), verb, selector, value)

    def _do(self, target, verb: str, selector: str, value: str | None) -> None:
        loc = target.locator(selector).first
        if verb == "type":
            loc.fill(value or "", timeout=10000)
        elif verb == "select":
            loc.select_option(label=value, timeout=10000)
        elif verb == "check":
            loc.check(timeout=10000)
        elif verb == "upload":
            loc.set_input_files(value, timeout=10000)
        elif verb == "click":
            loc.click(timeout=10000)
        else:
            raise ValueError(verb)

    def click(self, selector: str) -> None:
        self._do(self._page, "click", selector, None)

    def type(self, selector: str, text: str) -> None:
        self._do(self._page, "type", selector, text)

    def select(self, selector: str, value: str) -> None:
        self._do(self._page, "select", selector, value)

    def check(self, selector: str) -> None:
        self._do(self._page, "check", selector, None)

    def upload_file(self, selector: str, path: str) -> None:
        self._do(self._page, "upload", selector, path)

    def close(self) -> None:
        try:
            self._ctx.close()
        finally:
            self._pw.stop()
