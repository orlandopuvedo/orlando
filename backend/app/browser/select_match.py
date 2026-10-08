"""Safe option matching for <select> and radio groups.

Order: exact → normalized (case/space/punctuation) → known equivalents → same word set → unique containment.
If nothing matches, or more than one option could match, the caller must ask for approval — never pick at random.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field

PLACEHOLDER = re.compile(r"^\s*(?:-+|—+|select(?: one| an option|\.\.\.|…)?|choose(?: one| an option)?|please (?:select|choose)(?: one)?|none selected)?\s*\.{0,3}\s*$", re.I)

EQUIVALENTS = [
    {"united states", "united states of america", "usa", "us", "u s", "u s a", "america"},
    {"united kingdom", "uk", "great britain", "gb", "u k"},
    {"full time", "fulltime", "full time employee", "permanent full time"},
    {"part time", "parttime"},
    {"contract", "contractor", "independent contractor", "freelance"},
    {"yes", "y", "true", "si", "sí"},
    {"no", "n", "false"},
    {"prefer not to say", "prefer not to answer", "i prefer not to answer", "i prefer not to say", "decline to self identify",
     "decline to answer", "i don t wish to answer", "i do not wish to answer", "decline", "choose not to disclose",
     "i choose not to disclose", "not specified"},
    {"male", "man"},
    {"female", "woman"},
    {"remote", "fully remote", "100 remote"},
]


def norm(s: str | None) -> str:
    s = unicodedata.normalize("NFKD", str(s or "")).encode("ascii", "ignore").decode().lower()
    s = re.sub(r"[^a-z0-9+]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def _canon(s: str) -> str | None:
    n = norm(s)
    for i, group in enumerate(EQUIVALENTS):
        if n in group:
            return f"eq{i}"
    return None


def is_placeholder(option: str) -> bool:
    return not norm(option) or bool(PLACEHOLDER.match(option or ""))


@dataclass
class OptionMatch:
    option: str | None
    method: str              # exact | normalized | equivalent | tokens | contains | ambiguous | none
    candidates: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.option is not None


def match_option(value: str | None, options: list[str]) -> OptionMatch:
    opts = [o for o in options if not is_placeholder(o)]
    if not value or not norm(value) or not opts:
        return OptionMatch(None, "none", [])
    if value in opts:
        return OptionMatch(value, "exact", [value])
    nv = norm(value)

    def decide(cands: list[str], method: str) -> OptionMatch | None:
        cands = list(dict.fromkeys(cands))
        if len(cands) == 1:
            return OptionMatch(cands[0], method, cands)
        if len(cands) > 1:
            return OptionMatch(None, "ambiguous", cands)
        return None

    for step, cands in (
        ("normalized", [o for o in opts if norm(o) == nv]),
        ("equivalent", [o for o in opts if _canon(o) and _canon(o) == _canon(value)]),
        ("tokens", [o for o in opts if set(norm(o).split()) == set(nv.split())]),
    ):
        r = decide(cands, step)
        if r:
            return r
    if len(nv) >= 3:
        cands = [o for o in opts if len(norm(o)) >= 3 and (re.search(rf"\b{re.escape(nv)}\b", norm(o)) or re.search(rf"\b{re.escape(norm(o))}\b", nv))]
        r = decide(cands, "contains")
        if r:
            return r
    return OptionMatch(None, "none", [])
