"""BrowserAgent abstraction. Implementations must NEVER bypass CAPTCHAs, anti-bot systems, logins, 2FA or rate limits."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field

from app.browser import detectors


@dataclass
class FormField:
    selector: str
    tag: str
    type: str
    name: str | None
    label: str
    required: bool = False
    options: list[str] = field(default_factory=list)


@dataclass
class FrameInfo:
    id: str            # implementation-specific frame handle id
    url: str
    accessible: bool = True


@dataclass
class PageInspection:
    url: str
    title: str
    text: str
    fields: list[FormField]
    captcha: bool
    login: bool
    two_factor: bool
    video_required: bool
    file_uploads: list[FormField]
    submit_selector: str | None


class HumanInterventionRequired(RuntimeError):
    def __init__(self, reason: str, kind: str = "blocked"):
        super().__init__(reason)
        self.reason, self.kind = reason, kind


class BrowserAgent(ABC):
    """Abstract browser automation interface.

    `frame=None` always means the top-level document. Frame-aware methods have safe defaults so that
    simple implementations (and test fakes) only need the core verbs.
    """

    @abstractmethod
    def open_page(self, url: str) -> None: ...

    @abstractmethod
    def navigate(self, url: str) -> None: ...

    @abstractmethod
    def page_html(self) -> str: ...

    @abstractmethod
    def current_url(self) -> str: ...

    @abstractmethod
    def click(self, selector: str) -> None: ...

    @abstractmethod
    def type(self, selector: str, text: str) -> None: ...

    @abstractmethod
    def select(self, selector: str, value: str) -> None: ...

    @abstractmethod
    def upload_file(self, selector: str, path: str) -> None: ...

    @abstractmethod
    def close(self) -> None: ...

    # ---- frame-aware verbs (default: top document only)
    def list_frames(self) -> list[FrameInfo]:
        return []

    def frame_html(self, frame_id: str) -> str:
        raise HumanInterventionRequired("This browser agent cannot read embedded frames.")

    def act(self, verb: str, selector: str, value: str | None = None, frame: str | None = None) -> None:
        """Dispatch an action to the top document or a frame."""
        if frame is not None:
            self.frame_act(frame, verb, selector, value)
            return
        if verb == "type":
            self.type(selector, value or "")
        elif verb == "select":
            self.select(selector, value or "")
        elif verb == "check":
            self.check(selector)
        elif verb == "upload":
            self.upload_file(selector, value or "")
        elif verb == "click":
            self.click(selector)
        else:
            raise ValueError(f"Unknown verb {verb}")

    def frame_act(self, frame_id: str, verb: str, selector: str, value: str | None = None) -> None:
        raise HumanInterventionRequired("This browser agent cannot act inside embedded frames.")

    def check(self, selector: str) -> None:
        self.click(selector)

    def wait_for_settle(self) -> None:
        """Wait for navigation / re-render after an action."""

    # ---- shared, implementation-independent logic
    def extract_text(self) -> str:
        return detectors.html_text(self.page_html())

    def detect_captcha(self) -> bool:
        return detectors.detect_captcha(self.page_html())

    def detect_login(self) -> bool:
        return detectors.detect_login(self.page_html())

    def detect_2fa(self) -> bool:
        return detectors.detect_2fa(self.page_html())

    def detect_video_requirement(self) -> bool:
        return detectors.detect_video(self.page_html())

    def detect_file_upload(self) -> list[FormField]:
        return [f for f in self.inspect_page().fields if f.type == "file"]

    def inspect_page(self) -> PageInspection:
        html = self.page_html()
        fields = [FormField(**f) for f in detectors.extract_fields(html)]
        return PageInspection(
            url=self.current_url(), title=detectors.page_title(html), text=detectors.html_text(html)[:5000], fields=fields,
            captcha=detectors.detect_captcha(html), login=detectors.detect_login(html), two_factor=detectors.detect_2fa(html),
            video_required=detectors.detect_video(html), file_uploads=[f for f in fields if f.type == "file"],
            submit_selector=detectors.find_submit(html),
        )

    def request_human_approval(self, reason: str, kind: str = "blocked") -> None:
        raise HumanInterventionRequired(reason, kind)

    def submit(self, selector: str | None, approved: bool, frame: str | None = None) -> None:
        if not approved:
            raise HumanInterventionRequired("Final submission requires your approval.", "final_submit")
        if not selector:
            raise HumanInterventionRequired("Could not find the submit button — please submit manually.")
        self.act("click", selector, frame=frame)
