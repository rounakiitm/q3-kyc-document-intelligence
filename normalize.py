"""Normalize extracted KYC field values for consistent table display / scoring."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any


_DATE_FORMATS = (
    "%d-%m-%Y",
    "%d/%m/%Y",
    "%d.%m.%Y",
    "%Y-%m-%d",
    "%d-%m-%y",
    "%d/%m/%y",
    "%d %b %Y",
    "%d %B %Y",
    "%b %d, %Y",
    "%B %d, %Y",
)


def collapse_ws(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def title_name(text: str) -> str:
    # Preserve short ALLCAPS tokens (e.g. initials) while cleaning spacing.
    parts = []
    for w in collapse_ws(text).split(" "):
        if len(w) <= 2 and w.isupper():
            parts.append(w)
        else:
            parts.append(w.capitalize() if w.isupper() or w.islower() else w)
    return " ".join(parts)


def normalize_date(text: str) -> str | None:
    raw = collapse_ws(text)
    if not raw:
        return None
    # Already ISO-ish
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(raw, fmt).strftime("%d-%m-%Y")
        except ValueError:
            continue
    # Digits only ddmmyyyy / yyyymmdd
    digits = re.sub(r"\D", "", raw)
    if len(digits) == 8:
        for fmt in ("%d%m%Y", "%Y%m%d"):
            try:
                return datetime.strptime(digits, fmt).strftime("%d-%m-%Y")
            except ValueError:
                continue
    return raw


def normalize_aadhaar(text: str) -> str:
    digits = re.sub(r"\D", "", text)
    if len(digits) == 12:
        return f"{digits[:4]} {digits[4:8]} {digits[8:]}"
    return collapse_ws(text)


def normalize_pan(text: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", text.upper())


def normalize_ifsc(text: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", text.upper())


def normalize_account(text: str) -> str:
    return re.sub(r"\D", "", text)


def normalize_amount(text: str) -> str:
    raw = collapse_ws(text).replace(",", "")
    m = re.search(r"(\d+(?:\.\d+)?)", raw)
    if not m:
        return raw
    num = m.group(1)
    if "." in num:
        return f"{float(num):,.2f}"
    return f"{int(num):,}"


def normalize_field(name: str, value: Any) -> Any:
    """Return a normalized string value, or None if unreadable."""
    if value is None:
        return None
    text = collapse_ws(str(value))
    if not text or text.lower() in {"null", "none", "n/a", "-"}:
        return None

    key = (name or "").casefold()

    if "aadhaar" in key:
        return normalize_aadhaar(text)
    if key in {"pan number", "tin / pan"} or key.endswith("pan"):
        return normalize_pan(text)
    if "ifsc" in key:
        return normalize_ifsc(text)
    if "account number" in key or "bank account" in key:
        return normalize_account(text)
    if "amount" in key:
        return normalize_amount(text)
    if any(t in key for t in ("date", "valid till", "date of issue", "date of birth", "date of expiry")):
        return normalize_date(text)
    if any(
        t in key
        for t in (
            "name",
            "father",
            "proposer",
            "policyholder",
            "life assured",
            "agent",
            "nominee",
            "nationality",
            "place",
            "bank name",
            "address",
            "reason",
            "frequency",
            "relationship",
        )
    ):
        return title_name(text)
    if any(t in key for t in ("passport", "dl number", "mrz", "policy number", "application")):
        return collapse_ws(text).upper() if "mrz" in key or "dl" in key or "passport" in key else collapse_ws(text)

    return text


def normalize_result_fields(fields: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out = []
    for f in fields:
        raw = f.get("value")
        norm = normalize_field(str(f.get("name") or ""), raw)
        entry = dict(f)
        entry["raw_value"] = raw
        entry["value"] = norm
        entry["normalized"] = True
        out.append(entry)
    return out
