"""Salary parsing and normalization to monthly USD."""
from __future__ import annotations

import re
from dataclasses import dataclass

PERIOD_TO_MONTH = {"hour": 160.0, "day": 21.67, "week": 4.33, "month": 1.0, "year": 1 / 12}

DEFAULT_USD_RATES = {
    "USD": 1.0, "EUR": 1.08, "GBP": 1.27, "CAD": 0.73, "AUD": 0.66, "NZD": 0.60, "CHF": 1.12,
    "MXN": 0.055, "BRL": 0.18, "COP": 0.00025, "ARS": 0.001, "CLP": 0.0011, "PEN": 0.27, "INR": 0.012,
    "PHP": 0.017, "SGD": 0.74, "JPY": 0.0067, "SEK": 0.095, "NOK": 0.094, "DKK": 0.145, "PLN": 0.25,
}

CURRENCY_SYMBOLS = {"$": "USD", "€": "EUR", "£": "GBP", "₹": "INR", "¥": "JPY", "₱": "PHP"}
CURRENCY_CODES = "|".join(DEFAULT_USD_RATES.keys())


@dataclass
class ParsedSalary:
    min: float | None
    max: float | None
    currency: str | None
    period: str | None


_PERIOD_PATTERNS = [
    ("hour", r"(per|an|a|/)\s*(hour|hr)\b|hourly|/h\b"),
    ("day", r"(per|a|/)\s*day\b|daily"),
    ("week", r"(per|a|/)\s*(week|wk)\b|weekly"),
    ("month", r"(per|a|/)\s*(month|mo)\b|monthly|/mes|mensual"),
    ("year", r"(per|a|/)\s*(year|yr|annum)\b|annual|annually|yearly|p\.?a\.?\b"),
]

_NUM = r"(\d{1,3}(?:[,\s.]\d{3})+|\d+(?:\.\d+)?)\s*([kK])?"
_RANGE_RE = re.compile(
    r"(?P<cur1>[$€£₹¥₱]|\b(?:" + CURRENCY_CODES + r")\b)?\s*" + _NUM.replace("(", "(?P<a>", 1).replace("([kK])", "(?P<ak>[kK])", 1)
    + r"\s*(?:-|–|—|to|and|a)\s*(?P<cur2>[$€£₹¥₱]|\b(?:" + CURRENCY_CODES + r")\b)?\s*"
    + _NUM.replace("(", "(?P<b>", 1).replace("([kK])", "(?P<bk>[kK])", 1),
)
_SINGLE_RE = re.compile(
    r"(?P<cur>[$€£₹¥₱]|\b(?:" + CURRENCY_CODES + r")\b)\s*" + _NUM.replace("(", "(?P<a>", 1).replace("([kK])", "(?P<ak>[kK])", 1)
)


def _to_number(raw: str, k: str | None) -> float:
    s = raw.strip()
    # "2.500" (European thousands) vs "2.5"
    if re.fullmatch(r"\d{1,3}(?:[.,\s]\d{3})+", s):
        s = re.sub(r"[.,\s]", "", s)
    else:
        s = s.replace(",", "")
    value = float(s)
    if k:
        value *= 1000
    return value


def _currency(sym: str | None) -> str | None:
    if not sym:
        return None
    sym = sym.strip()
    return CURRENCY_SYMBOLS.get(sym, sym.upper() if sym.upper() in DEFAULT_USD_RATES else None)


def _guess_period(context: str, value: float) -> str:
    c = context.lower()
    for period, pattern in _PERIOD_PATTERNS:
        if re.search(pattern, c):
            return period
    # Heuristic by magnitude
    if value < 200:
        return "hour"
    if value < 20000:
        return "month"
    return "year"


def parse_salary(text: str | None) -> ParsedSalary | None:
    """Extract the first plausible salary (range) from free text."""
    if not text:
        return None
    for m in _RANGE_RE.finditer(text):
        cur = _currency(m.group("cur1")) or _currency(m.group("cur2"))
        bk = m.group("bk")
        ak = m.group("ak") or bk  # "$60-80k" → both thousands
        try:
            a = _to_number(m.group("a"), ak)
            b = _to_number(m.group("b"), bk)
        except ValueError:
            continue
        if not cur and not (ak or bk):
            continue  # "3-5 years" etc.
        if a <= 0 or b <= 0 or b < a or b > a * 5:
            continue
        ctx = text[m.start() : m.end() + 40]
        return ParsedSalary(a, b, cur or "USD", _guess_period(ctx, b))
    for m in _SINGLE_RE.finditer(text):
        cur = _currency(m.group("cur"))
        try:
            a = _to_number(m.group("a"), m.group("ak"))
        except ValueError:
            continue
        if a < 5:
            continue
        ctx = text[m.start() : m.end() + 40]
        return ParsedSalary(a, None, cur or "USD", _guess_period(ctx, a))
    return None


def to_monthly_usd(amount: float | None, currency: str | None, period: str | None, rates: dict | None = None) -> float | None:
    if amount is None:
        return None
    rates = rates or DEFAULT_USD_RATES
    rate = rates.get((currency or "USD").upper())
    if rate is None:
        return None
    factor = PERIOD_TO_MONTH.get(period or "year", 1 / 12)
    return round(amount * factor * rate, 2)
