"""Playwright implementation of BrowserAgent (optional dependency: pip install -r requirements-browser.txt).

Runs a *visible* persistent browser profile by default so YOU log in yourself; the agent never handles passwords.
"""
from __future__ import annotations

from app.browser.base import BrowserAgent
from app.config import get_settings


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
        self._ctx = self._pw.chromium.launch_persistent_context(str(s.browser_user_data_dir), **kwargs)
        self._page = self._ctx.pages[0] if self._ctx.pages else self._ctx.new_page()

    def open_page(self, url: str) -> None:
        self._page.goto(url, wait_until="domcontentloaded", timeout=45000)
        self._page.wait_for_timeout(1500)

    def navigate(self, url: str) -> None:
        self.open_page(url)

    def page_html(self) -> str:
        return self._page.content()

    def current_url(self) -> str:
        return self._page.url

    def click(self, selector: str) -> None:
        self._page.click(selector, timeout=10000)

    def type(self, selector: str, text: str) -> None:
        self._page.fill(selector, text, timeout=10000)

    def select(self, selector: str, value: str) -> None:
        self._page.select_option(selector, label=value, timeout=10000)

    def upload_file(self, selector: str, path: str) -> None:
        self._page.set_input_files(selector, path, timeout=10000)

    def close(self) -> None:
        try:
            self._ctx.close()
        finally:
            self._pw.stop()
